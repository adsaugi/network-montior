#!/usr/bin/env python3
"""
Homelab Dashboard Backend Server - REAL-TIME Edition
- /api/data  : Snapshot JSON (on-demand)
- /api/stream: Server-Sent Events push every 1 second (real-time)
- Proxmox VE: Delta-based throughput (netin/netout bytes diff / elapsed = actual KB/s)
- Windows NIC: Real-time host NIC stats via PowerShell Get-NetAdapterStatistics
- ARP table : Background refresh every 8s
"""
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import psutil
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http import cookies
import secrets
import hashlib
import traffic_db

# Initialize persistent SQLite traffic database
traffic_db.init_db()

def load_dotenv(env_path=None):
    if env_path is None:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass

load_dotenv()

PORT     = int(os.getenv("PORT", "3000"))
PVE_HOST = os.getenv("PVE_HOST", "192.168.1.99:8006")
PVE_USER = os.getenv("PVE_USER", "root@pam")
PVE_PASS = os.getenv("PVE_PASS", "")
GATEWAY  = os.getenv("GATEWAY", "192.168.1.1")
SUBNET   = os.getenv("SUBNET", "192.168.1.")

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode    = ssl.CERT_NONE

LAYOUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layout.json")

def load_layout():
    if os.path.exists(LAYOUT_FILE):
        try:
            with open(LAYOUT_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            return {}
    return {}

def save_layout(layout_data):
    try:
        with open(LAYOUT_FILE, "w", encoding="utf-8") as f:
            json.dump(layout_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[Layout] Error saving: {e}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# Shared state (written by background threads, read by HTTP handler)
# ─────────────────────────────────────────────────────────────────────────────
state = {
    "ticket":      None,
    "csrf":        None,
    "ticket_ts":   0,

    # VM list with live rx/tx (KB/s)
    "vms":         [],
    "pve_ips":     [],   # IPs known to be Proxmox VMs (for gateway dedup)
    "pve_error":   None,

    # ARP-discovered gateway clients
    "arp_devices": [],

    # Tailscale nodes
    "tailscale_nodes": [],

    # Host NIC real throughput (KB/s) and total bytes
    "host_rx":       0.0,
    "host_tx":       0.0,
    "host_rx_bytes": 0,
    "host_tx_bytes": 0,
    "traffic_stats": traffic_db.get_traffic_summary(),

    # Delta-tracking for Proxmox VMs: {vm_id: (netin_bytes, netout_bytes, timestamp)}
    "_vm_prev":    {},

    # Saved node coordinates synced across all devices
    "layout":      load_layout(),
}

# Lock for reading/writing shared state safely
_lock = threading.Lock()

# SSE client set: list of open wfile objects
_sse_clients = []
_sse_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Proxmox helpers
# ─────────────────────────────────────────────────────────────────────────────
def pve_login():
    url  = f"https://{PVE_HOST}/api2/json/access/ticket"
    body = urllib.parse.urlencode({"username": PVE_USER, "password": PVE_PASS}).encode()
    req  = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=6) as r:
        d = json.loads(r.read())["data"]
    with _lock:
        state["ticket"]    = d["ticket"]
        state["csrf"]      = d["CSRFPreventionToken"]
        state["ticket_ts"] = time.time()
    print("[PVE] Login OK")

def pve_get(path):
    with _lock:
        ticket = state["ticket"]
        csrf   = state["csrf"]
        ts     = state["ticket_ts"]
    if not ticket or (time.time() - ts) > 5400:
        pve_login()
        with _lock:
            ticket = state["ticket"]
            csrf   = state["csrf"]
    url = f"https://{PVE_HOST}/api2/json{path}"
    req = urllib.request.Request(url, headers={
        "Cookie":               f"PVEAuthCookie={ticket}",
        "CSRFPreventionToken":  csrf,
    })
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=6) as r:
        return json.loads(r.read())["data"]

def _calc_speed(vm_id, raw_rx, raw_tx, now):
    """Return (rx_kbps, tx_kbps, delta_rx, delta_tx) using byte-delta / elapsed, update prev."""
    with _lock:
        prev = state["_vm_prev"].get(vm_id)

    if prev is None:
        with _lock:
            state["_vm_prev"][vm_id] = (raw_rx, raw_tx, now)
        return 0.0, 0.0, 0, 0

    p_rx, p_tx, p_ts = prev
    elapsed = now - p_ts
    if elapsed <= 0:
        return 0.0, 0.0, 0, 0

    d_rx = raw_rx - p_rx if raw_rx >= p_rx else raw_rx
    d_tx = raw_tx - p_tx if raw_tx >= p_tx else raw_tx

    rx_kbps = max(0.0, d_rx / elapsed / 1024)
    tx_kbps = max(0.0, d_tx / elapsed / 1024)

    with _lock:
        state["_vm_prev"][vm_id] = (raw_rx, raw_tx, now)

    return round(rx_kbps, 1), round(tx_kbps, 1), int(d_rx), int(d_tx)


def _get_qemu_ip(nn, vmid):
    """Try QEMU guest agent to get VM's first non-loopback IPv4."""
    try:
        ifaces = pve_get(f"/nodes/{nn}/qemu/{vmid}/agent/network-get-interfaces")
        # ifaces is usually {"result": [...]}
        iface_list = ifaces if isinstance(ifaces, list) else ifaces.get("result", [])
        for iface in iface_list:
            name = iface.get("name", "")
            if name in ("lo", "lo0"):
                continue
            for addr in iface.get("ip-addresses", []):
                ip = addr.get("ip-address", "")
                if addr.get("ip-address-type") == "ipv4" and not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    return None


def _get_lxc_ip(nn, vmid):
    """Get LXC container IP from its network interfaces config."""
    try:
        ifaces = pve_get(f"/nodes/{nn}/lxc/{vmid}/interfaces")
        if isinstance(ifaces, list):
            for iface in ifaces:
                ip = iface.get("inet", "").split("/")[0]
                if ip and not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    return None


_vm_ip_cache = {}

def fetch_pve_vms():
    try:
        nodes = pve_get("/nodes")
        vms   = []
        now   = time.time()
        pve_ips = set()   # collect all known VM IPs for gateway dedup
        total_pve_rx = 0
        total_pve_tx = 0
        batch_delta_rx = 0
        batch_delta_tx = 0

        with _lock:
            had_prev = bool(state["_vm_prev"])

        for node in nodes:
            nn = node["node"]

            # ── QEMU ──────────────────────────────────────────────────────
            try:
                for vm in pve_get(f"/nodes/{nn}/qemu"):
                    vid     = f"qemu-{vm['vmid']}"
                    raw_rx  = int(vm.get("netin",  0))
                    raw_tx  = int(vm.get("netout", 0))
                    total_pve_rx += raw_rx
                    total_pve_tx += raw_tx
                    rx, tx, d_rx, d_tx = _calc_speed(vid, raw_rx, raw_tx, now)
                    batch_delta_rx += d_rx
                    batch_delta_tx += d_tx
                    
                    ip = _vm_ip_cache.get(vid)
                    if not ip and vm.get("status") == "running":
                        ip = _get_qemu_ip(nn, vm["vmid"])
                        if ip: _vm_ip_cache[vid] = ip
                    
                    if ip: pve_ips.add(ip)
                    
                    vms.append({
                        "id":       vid,
                        "name":     vm.get("name", f"VM-{vm['vmid']}"),
                        "vmid":     vm["vmid"],
                        "type":     "QEMU VM",
                        "status":   vm.get("status", "stopped"),
                        "online":   vm.get("status") == "running",
                        "cpu":      round(float(vm.get("cpu", 0)) * 100, 1),
                        "memMB":    vm.get("mem",    0) // (1024*1024),
                        "maxMemMB": vm.get("maxmem", 0) // (1024*1024),
                        "rxKbps":   rx,
                        "txKbps":   tx,
                        "ip":       ip or "",
                        "node":     nn,
                    })
            except Exception as e:
                print(f"[PVE] QEMU err: {e}")

            # ── LXC ───────────────────────────────────────────────────────
            try:
                for ct in pve_get(f"/nodes/{nn}/lxc"):
                    vid    = f"lxc-{ct['vmid']}"
                    raw_rx = int(ct.get("netin",  0))
                    raw_tx = int(ct.get("netout", 0))
                    total_pve_rx += raw_rx
                    total_pve_tx += raw_tx
                    rx, tx, d_rx, d_tx = _calc_speed(vid, raw_rx, raw_tx, now)
                    batch_delta_rx += d_rx
                    batch_delta_tx += d_tx
                    
                    ip = _vm_ip_cache.get(vid)
                    if not ip and ct.get("status") == "running":
                        ip = _get_lxc_ip(nn, ct["vmid"])
                        if ip: _vm_ip_cache[vid] = ip
                        
                    if ip: pve_ips.add(ip)
                    vms.append({
                        "id":       vid,
                        "name":     ct.get("name", f"CT-{ct['vmid']}"),
                        "vmid":     ct["vmid"],
                        "type":     "LXC Container",
                        "status":   ct.get("status", "stopped"),
                        "online":   ct.get("status") == "running",
                        "cpu":      round(float(ct.get("cpu", 0)) * 100, 1),
                        "memMB":    ct.get("mem",    0) // (1024*1024),
                        "maxMemMB": ct.get("maxmem", 0) // (1024*1024),
                        "rxKbps":   rx,
                        "txKbps":   tx,
                        "ip":       ip or "",
                        "node":     nn,
                    })
            except Exception as e:
                print(f"[PVE] LXC err: {e}")

        # Update persistent traffic stats in SQLite
        if not had_prev:
            traffic_db.seed_initial_if_empty(total_pve_rx, total_pve_tx)
        elif batch_delta_rx > 0 or batch_delta_tx > 0:
            traffic_db.record_delta(batch_delta_rx, batch_delta_tx)

        stats = traffic_db.get_traffic_summary()

        with _lock:
            state["vms"]          = vms
            state["pve_ips"]      = list(pve_ips)
            state["pve_error"]    = None
            state["pve_rx_bytes"] = total_pve_rx
            state["pve_tx_bytes"] = total_pve_tx
            state["host_rx_bytes"] = stats["all"]["rx"]
            state["host_tx_bytes"] = stats["all"]["tx"]
            state["traffic_stats"] = stats
        print(f"[PVE] {len(vms)} VMs refreshed, IPs: {list(pve_ips)}")

    except Exception as e:
        print(f"[PVE] API fetch error (ignoring to prevent UI flicker): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Host NIC real-time (Cross-Platform using psutil)
# ─────────────────────────────────────────────────────────────────────────────
_nic_prev = {}   # (rx_bytes, tx_bytes, ts)

def get_host_nic_speeds():
    """
    Query host NICs via Proxmox VM sums, compute delta throughput.
    Returns (total_rx_kbps, total_tx_kbps).
    """
    global _nic_prev
    try:
        now = time.time()
        
        with _lock:
            rx_b = state.get("pve_rx_bytes", 0)
            tx_b = state.get("pve_tx_bytes", 0)
        
        total_rx = total_tx = 0.0

        if _nic_prev:
            p_rx, p_tx, p_ts = _nic_prev.get("all", (0, 0, 0))
            elapsed = now - p_ts
            if elapsed > 0:
                total_rx = max(0, rx_b - p_rx) / elapsed / 1024
                total_tx = max(0, tx_b - p_tx) / elapsed / 1024

        _nic_prev["all"] = (rx_b, tx_b, now)

        return round(total_rx, 1), round(total_tx, 1)

    except Exception as e:
        print(f"[NIC] Error reading psutil stats: {e}")
        return 0.0, 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ARP table
# ─────────────────────────────────────────────────────────────────────────────
APPLE_OUI = {
    "0c:85:e1","da:13:16","2a:61:f5","62:66:6b","7a:e3:c8",
    "ea:11:43","ba:01:d1","42:24:50","3c:22:fb","f0:d1:a9",
    "8c:85:90","a4:c3:f0","bc:d0:74","04:4b:ed","14:7d:da",
    "ac:de:48","00:cd:fe","a8:be:27","78:fd:94","dc:a9:04",
}
ANDROID_OUI = {
    "5c:ba:ef","f8:17:2d","76:98:07","34:4d:f7","a4:50:46",
    "28:98:7b","d4:a3:3d","d0:f8:8c","00:9e:c8","90:f1:aa",
}
SKIP_IPS = {GATEWAY, "192.168.1.99", "192.168.1.255"}

def read_arp():
    try:
        devices = []
        if os.name == "nt":
            out = subprocess.check_output("arp -a", shell=True, timeout=4).decode("utf-8", errors="ignore")
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 2: continue
                ip  = parts[0].strip()
                mac = parts[1].strip().lower().replace("-", ":")
                if not ip.startswith(SUBNET) or ip in SKIP_IPS or mac in ("ff:ff:ff:ff:ff:ff", ""):
                    continue
                _add_arp_device(devices, ip, mac)
        else:
            out = subprocess.check_output(["ip", "neigh"], timeout=4).decode("utf-8", errors="ignore")
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 5 or parts[4] == "FAILED": continue
                ip = parts[0].strip()
                mac = parts[4].strip().lower()
                if not ip.startswith(SUBNET) or ip in SKIP_IPS or mac in ("ff:ff:ff:ff:ff:ff", ""):
                    continue
                _add_arp_device(devices, ip, mac)
                
        with _lock:
            state["arp_devices"] = devices
        print(f"[ARP] {len(devices)} gateway devices")
    except Exception as e:
        print(f"[ARP] Error: {e}")

def _add_arp_device(devices, ip, mac):
    pref = mac[:8]
    if pref in APPLE_OUI:
        kind = "apple";   label = f"iPhone/iPad ({ip})"
    elif pref in ANDROID_OUI:
        kind = "android"; label = f"Android ({ip})"
    else:
        kind = "device";  label = f"Wi-Fi Client ({ip})"

    devices.append({
        "id":     f"gw-{ip.replace('.', '-')}",
        "ip":     ip,
        "mac":    mac,
        "name":   label,
        "type":   kind,
        "online": True,
        "rxKbps": 0,
        "txKbps": 0,
    })

# ─────────────────────────────────────────────────────────────────────────────
# Tailscale integration (Remote via SSH)
# ─────────────────────────────────────────────────────────────────────────────
_ts_prev = {}
TS_SSH_USER = os.getenv("TS_SSH_USER", "root")
TS_SSH_PASS = os.getenv("TS_SSH_PASS", "")
TS_SSH_HOST = os.getenv("TS_SSH_HOST", "192.168.1.104")

def fetch_tailscale():
    try:
        # We use sshpass to fetch the tailscale status from the remote VPN VM
        cmd = [
            "sshpass", "-p", TS_SSH_PASS,
            "ssh", "-o", "StrictHostKeyChecking=no", f"{TS_SSH_USER}@{TS_SSH_HOST}",
            "tailscale status --json"
        ]
        out = subprocess.check_output(cmd, timeout=8).decode("utf-8")
        data = json.loads(out)
        
        nodes = []
        now = time.time()
        
        def process_node(n, is_self=False):
            if not n: return
            ip = n.get("TailscaleIPs", [""])[0] if n.get("TailscaleIPs") else ""
            rx_b = int(n.get("RxBytes", 0))
            tx_b = int(n.get("TxBytes", 0))
            
            # calculate speed
            rx_kbps = tx_kbps = 0.0
            prev = _ts_prev.get(ip)
            if prev:
                p_rx, p_tx, p_ts = prev
                elapsed = now - p_ts
                if elapsed > 0:
                    rx_kbps = max(0, rx_b - p_rx) / elapsed / 1024
                    tx_kbps = max(0, tx_b - p_tx) / elapsed / 1024
            
            _ts_prev[ip] = (rx_b, tx_b, now)
            
            # Some versions of Tailscale report 0 for Rx/Tx on status, but we try anyway.
            # We enforce online status based on 'Online' key
            is_online = n.get("Online", False)
            if is_self:
                is_online = True
                
            # Extract cleaner name from DNSName (e.g. 'windows10-server.domain.ts.net.' -> 'windows10-server')
            dns_name = n.get("DNSName", "")
            if dns_name and "." in dns_name:
                clean_name = dns_name.split(".")[0]
            else:
                clean_name = n.get("HostName", "Unknown")
                
            if clean_name.lower() == "localhost":
                return
                
            nodes.append({
                "id": f"ts-{n.get('ID', ip)}",
                "name": clean_name,
                "ip": ip,
                "online": is_online,
                "rxKbps": round(rx_kbps, 1),
                "txKbps": round(tx_kbps, 1),
                "isSelf": is_self
            })
            
        # Add Self
        process_node(data.get("Self"), is_self=True)
        # Add Peers
        peers = data.get("Peer", {})
        for pk, pv in peers.items():
            process_node(pv, is_self=False)
            
        with _lock:
            state["tailscale_nodes"] = nodes
            
    except Exception as e:
        print(f"[Tailscale] Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SSE broadcast helpers
# ─────────────────────────────────────────────────────────────────────────────
def _build_payload():
    with _lock:
        return {
            "ok":         True,
            "ts":         time.time(),
            "vms":        state["vms"],
            "pveIPs":     state["pve_ips"],
            "arpDevices": state["arp_devices"],
            "tailscale":  state["tailscale_nodes"],
            "pveError":    state["pve_error"],
            "hostRx":      state["host_rx"],
            "hostTx":      state["host_tx"],
            "hostRxBytes": state["host_rx_bytes"],
            "hostTxBytes": state["host_tx_bytes"],
            "trafficStats": state.get("traffic_stats", {}),
            "layout":      state.get("layout", {}),
        }

def _broadcast(payload_bytes):
    msg = b"data: " + payload_bytes + b"\n\n"
    dead = []
    with _sse_lock:
        clients = list(_sse_clients)
    for wf in clients:
        try:
            wf.write(msg)
            wf.flush()
        except Exception:
            dead.append(wf)
    if dead:
        with _sse_lock:
            for d in dead:
                if d in _sse_clients:
                    _sse_clients.remove(d)


# ─────────────────────────────────────────────────────────────────────────────
# Real-time refresh loop  (runs every 2 s)
# ─────────────────────────────────────────────────────────────────────────────
def realtime_loop():
    """
    Every 2 seconds:
      1. Poll Proxmox VMs (compute delta throughput)
      2. Poll host NIC via PowerShell
      3. Broadcast SSE to all connected clients
    """
    pve_tick  = 0   # refresh Proxmox every 2 s
    arp_tick  = 0   # refresh ARP every 8 s
    nic_tick  = 0   # host NIC every 2 s (same as loop)

    while True:
        now = time.time()
        t_start = now

        # ── Host NIC ──────────────────────────────────────────────────────
        rx_kbps, tx_kbps = get_host_nic_speeds()
        with _lock:
            state["host_rx"] = rx_kbps
            state["host_tx"] = tx_kbps

        # ── Proxmox VMs ───────────────────────────────────────────────────
        if now - pve_tick >= 2:
            fetch_pve_vms()
            pve_tick = now

        # ── ARP ───────────────────────────────────────────────────────────
        if now - arp_tick >= 8:
            read_arp()
            fetch_tailscale()
            arp_tick = now

        # ── SSE broadcast ─────────────────────────────────────────────────
        payload = _build_payload()
        _broadcast(json.dumps(payload).encode())

        elapsed = time.time() - t_start
        sleep_for = max(0.1, 2.0 - elapsed)
        time.sleep(sleep_for)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Handler
# ─────────────────────────────────────────────────────────────────────────────
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg":  "image/svg+xml",
}


# ─────────────────────────────────────────────────────────────────────────────
# ZERO-LEAK 2FA TELEGRAM AUTH & 24H IP LOCKOUT (TOPOLOGY GATE)
# ─────────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DEFAULT_HASH = os.getenv("MASTER_PASSWORD_HASH", "")

LOGIN_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topology_login.html")
LOCKED_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topology_locked.html")
LOCKED_IPS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".locked_ips.json")

SESSIONS = {}
PENDING_OTPS = {}
FAILED_PASSWORD_ATTEMPTS = {}
MAX_PASSWORD_ATTEMPTS = 5
PASSWORD_LOCKOUT_WINDOW = 300

MAX_OTP_ATTEMPTS = 2
IP_LOCK_DURATION = 86400  # 24 hours
LOCKED_IPS = {}
OTP_FAILURES = {}

def load_locked_ips():
    global LOCKED_IPS
    if os.path.exists(LOCKED_IPS_FILE):
        try:
            with open(LOCKED_IPS_FILE, "r") as f:
                LOCKED_IPS = json.load(f)
        except Exception:
            LOCKED_IPS = {}

def save_locked_ips():
    try:
        with open(LOCKED_IPS_FILE, "w") as f:
            json.dump(LOCKED_IPS, f, indent=2)
    except Exception:
        pass

load_locked_ips()

def is_ip_locked_24h(ip):
    if not ip or ip in ("127.0.0.1", "::1", "localhost") or str(ip).startswith("127."):
        return False, "", ""
    now = time.time()
    if ip in LOCKED_IPS:
        info = LOCKED_IPS[ip]
        unlock_time = info.get("unlock_time", 0)
        if now < unlock_time:
            remaining_sec = int(unlock_time - now)
            hours = remaining_sec // 3600
            mins = (remaining_sec % 3600) // 60
            time_str = f"{hours} jam {mins} menit" if hours > 0 else f"{mins} menit"
            return True, time_str, info.get("reason", "Salah OTP 2x")
        else:
            del LOCKED_IPS[ip]
            save_locked_ips()
    return False, "", ""

def lock_ip_24h(ip, reason="Gagal input OTP 2x berturut-turut"):
    if not ip or ip in ("127.0.0.1", "::1", "localhost") or str(ip).startswith("127."):
        print(f"[!] Refusing to lock loopback IP: {ip}")
        return
    now = time.time()
    unlock_time = now + IP_LOCK_DURATION
    LOCKED_IPS[ip] = {
        "unlock_time": unlock_time,
        "locked_at": now,
        "reason": reason
    }
    save_locked_ips()

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    alert_msg = (
        f"🔒 <b>[TOPOLOGY GATE - IP TERKUNCI 24 JAM]</b>\n"
        f"Terdeteksi salah input OTP Telegram 2x di Topology Gateway:\n"
        f"• <b>IP Pengunjung:</b> <code>{ip}</code>\n"
        f"• <b>Waktu:</b> <code>{now_str}</code>\n"
        f"• <b>Target:</b> <code>topology.xaiserv.my.id</code>\n"
        f"• <b>Status:</b> <b>LOCKED (Terkunci 24 Jam)</b>\n\n"
        f"⏳ <i>Kunci akan terbuka otomatis setelah 24 jam.</i>"
    )
    send_telegram_async(alert_msg)

def send_telegram_sync(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            pass
        return True
    except Exception:
        return False

def send_telegram_async(text):
    threading.Thread(target=send_telegram_sync, args=(text,), daemon=True).start()

def is_password_rate_limited(ip):
    now = time.time()
    attempts = FAILED_PASSWORD_ATTEMPTS.get(ip, [])
    recent = [t for t in attempts if now - t < PASSWORD_LOCKOUT_WINDOW]
    FAILED_PASSWORD_ATTEMPTS[ip] = recent
    return len(recent) >= MAX_PASSWORD_ATTEMPTS

def record_password_failure(ip):
    now = time.time()
    attempts = FAILED_PASSWORD_ATTEMPTS.get(ip, [])
    attempts.append(now)
    FAILED_PASSWORD_ATTEMPTS[ip] = [t for t in attempts if now - t < PASSWORD_LOCKOUT_WINDOW]

def clear_password_failures(ip):
    if ip in FAILED_PASSWORD_ATTEMPTS:
        del FAILED_PASSWORD_ATTEMPTS[ip]

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Quiet

    def get_client_ip(self):
        # 1. Cloudflare official connecting IP
        cf_ip = self.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()

        # 2. X-Real-IP
        xreal = self.headers.get("X-Real-IP")
        if xreal:
            return xreal.strip()

        # 3. X-Forwarded-For (take last IP if multiple, as upstream proxies append)
        xfwd = self.headers.get("X-Forwarded-For")
        if xfwd:
            parts = [p.strip() for p in xfwd.split(",") if p.strip()]
            if parts:
                return parts[-1]

        return self.client_address[0]

    def is_https(self):
        proto = self.headers.get("X-Forwarded-Proto", "").lower()
        if proto == "https":
            return True
        cf_visitor = self.headers.get("CF-Visitor", "")
        if "https" in cf_visitor.lower():
            return True
        if self.headers.get("X-Forwarded-Ssl", "").lower() == "on":
            return True
        return False

    def is_authenticated(self):
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return False
        try:
            c = cookies.SimpleCookie(cookie_header)
            token = c.get("topology_session")
            if token and token.value in SESSIONS:
                expire_time = SESSIONS[token.value]
                if time.time() < expire_time:
                    return True
                else:
                    del SESSIONS[token.value]
        except Exception:
            pass
        return False

    def send_locked_page(self, client_ip, time_left):
        self.send_response(423)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        content = ""
        if os.path.exists(LOCKED_HTML_PATH):
            with open(LOCKED_HTML_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace("{{ client_ip }}", client_ip).replace("{{ time_left }}", time_left)
        else:
            content = f"<h1>423 LOCKED</h1><p>IP {client_ip} terkunci 24 jam. Sisa: {time_left}</p>"
        self.wfile.write(content.encode("utf-8"))

    def do_GET(self):
        client_ip = self.get_client_ip()

        # Check if IP locked
        locked, time_left, reason = is_ip_locked_24h(client_ip)
        if locked:
            if self.path.startswith("/api/"):
                self.send_response(423)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": f"[IP_LOCKED] // IP TERKUNCI (Sisa: {time_left})"}).encode())
                return
            self.send_locked_page(client_ip, time_left)
            return

        # Logout route
        if self.path in ("/logout", "/api/logout"):
            sec_attr = "; Secure" if self.is_https() else ""
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"topology_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax{sec_attr}")
            self.end_headers()
            return

        path = self.path.split("?")[0]

        # If authenticated -> normal endpoints
        if self.is_authenticated():
            if path == "/api/stream":
                self.serve_sse()
            elif path == "/api/data":
                self.serve_json()
            elif path == "/api/layout":
                self.serve_layout()
            elif path == "/api/traffic/stats":
                self.serve_traffic_stats()
            elif path == "/api/traffic/history":
                self.serve_traffic_history()
            elif path in ("/", "/index.html"):
                self.serve_static("index.html", "text/html; charset=utf-8")
            else:
                fname = path.lstrip("/")
                ext = os.path.splitext(fname)[1].lower()
                ctype = _MIME.get(ext, "application/octet-stream")
                self.serve_static(fname, ctype)
            return

        # NOT AUTHENTICATED:
        # Static assets needed for login page (css/js) allowed
        fname = path.lstrip("/")
        ext = os.path.splitext(fname)[1].lower()
        if ext in (".css", ".js", ".svg", ".woff", ".woff2", ".ttf") and path not in ("/api/stream", "/api/data"):
            ctype = _MIME.get(ext, "application/octet-stream")
            self.serve_static(fname, ctype)
            return

        # API calls without session -> 401 Unauthorized
        if path.startswith("/api/"):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": "Unauthorized // Sesi login diperlukan"}).encode())
            return

        # Serve Login Page
        if os.path.exists(LOGIN_HTML_PATH):
            with open(LOGIN_HTML_PATH, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(401)
        self.end_headers()

    def do_POST(self):
        client_ip = self.get_client_ip()

        # Check if IP locked
        locked, time_left, reason = is_ip_locked_24h(client_ip)
        if locked:
            self.send_response(423)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": f"[IP_LOCKED] // IP TERKUNCI SELAMA 24 JAM (Sisa: {time_left})"
            }).encode("utf-8"))
            return

        # 1. Step 1: Login with Master Password
        if self.path == "/api/login":
            if is_password_rate_limited(client_ip):
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "[RATE_LIMITED] // TERLALU BANYAK PERCOBAAN. TERKUNCI SELAMA 5 MENIT."
                }).encode("utf-8"))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8", "replace")
            try:
                data = json.loads(body)
                pwd = data.get("password", "")
                remember = bool(data.get("remember", False))
            except Exception:
                parsed = urllib.parse.parse_qs(body)
                pwd = parsed.get("password", [""])[0]
                remember = False

            input_hash = hashlib.sha256(pwd.encode("utf-8")).hexdigest()

            if secrets.compare_digest(input_hash, DEFAULT_HASH):
                otp_code = "".join([secrets.choice("0123456789") for _ in range(6)])
                otp_token = secrets.token_urlsafe(24)
                expires_at = time.time() + 180

                PENDING_OTPS[otp_token] = {
                    "code": otp_code,
                    "expires": expires_at,
                    "remember": remember,
                    "attempts": 0
                }

                OTP_FAILURES[client_ip] = 0

                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                tg_msg = (
                    f"🔐 <b>[REAL-TIME TOPOLOGY // 2FA GATEWAY]</b>\n"
                    f"Permintaan akses Peta Jaringan Homelab terdeteksi:\n"
                    f"• <b>IP Pengunjung:</b> <code>{client_ip}</code>\n"
                    f"• <b>Target:</b> <code>topology.xaiserv.my.id</code>\n"
                    f"• <b>Waktu:</b> <code>{now_str}</code>\n"
                    f"• <b>KODE OTP ANDA:</b> <code>{otp_code}</code>\n\n"
                    f"⚠️ <i>Maksimal 2x kesempatan. Jika salah 2x, IP terkunci 24 jam!</i>\n"
                    f"⏳ <i>Kode ini berlaku 3 menit.</i>"
                )
                send_telegram_async(tg_msg)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "require_otp": True,
                    "otp_token": otp_token,
                    "expires_in": 180
                }).encode("utf-8"))
            else:
                record_password_failure(client_ip)
                attempts_left = max(0, MAX_PASSWORD_ATTEMPTS - len(FAILED_PASSWORD_ATTEMPTS.get(client_ip, [])))
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err_msg = f"[ACCESS_DENIED] // MASTER KEY SALAH ({attempts_left} kesempatan tersisa)"
                if attempts_left == 0:
                    err_msg = "[RATE_LIMITED] // TERLALU BANYAK PERCOBAAN. TERKUNCI SELAMA 5 MENIT."
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": err_msg
                }).encode("utf-8"))
            return

        # 2. Step 2: Verify 6-digit OTP
        if self.path == "/api/verify-otp":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8", "replace")
            try:
                data = json.loads(body)
                otp_token = data.get("otp_token", "")
                user_code = str(data.get("code", "")).strip()
            except Exception:
                self.send_response(400)
                self.end_headers()
                return

            entry = PENDING_OTPS.get(otp_token)
            if not entry:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "[EXPIRED_OR_INVALID] // Sesi tidak ditemukan. Ulangi login."
                }).encode("utf-8"))
                return

            if time.time() > entry["expires"]:
                del PENDING_OTPS[otp_token]
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "[OTP_EXPIRED] // Kode sudah kedaluwarsa. Minta kode baru."
                }).encode("utf-8"))
                return

            if secrets.compare_digest(user_code, entry["code"]):
                # OTP MATCH!
                remember = entry.get("remember", False)
                del PENDING_OTPS[otp_token]
                clear_password_failures(client_ip)
                OTP_FAILURES.pop(client_ip, None)

                session_token = secrets.token_urlsafe(32)
                max_age = 2592000 if remember else 86400
                SESSIONS[session_token] = time.time() + max_age

                now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                send_telegram_async(
                    f"✅ <b>[REAL-TIME TOPOLOGY] 2FA Berhasil Diverifikasi!</b>\n"
                    f"• <b>IP:</b> <code>{client_ip}</code>\n"
                    f"• <b>Host:</b> <code>topology.xaiserv.my.id</code>\n"
                    f"• <b>Waktu:</b> <code>{now_str}</code>\n"
                    f"• <b>Sesi:</b> {'30 Hari' if remember else '24 Jam'}"
                )

                sec_attr = "; Secure" if self.is_https() else ""
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "Set-Cookie",
                    f"topology_session={session_token}; Path=/; HttpOnly; SameSite=Lax{sec_attr}; Max-Age={max_age}"
                )
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            else:
                current_fails = OTP_FAILURES.get(client_ip, 0) + 1
                OTP_FAILURES[client_ip] = current_fails
                entry["attempts"] += 1

                if current_fails >= MAX_OTP_ATTEMPTS:
                    del PENDING_OTPS[otp_token]
                    lock_ip_24h(client_ip, reason="Gagal input OTP Topology 2x berturut-turut")
                    self.send_response(423)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "[IP_LOCKED] // 2X SALAH INPUT OTP! IP ANDA TERKUNCI SELAMA 24 JAM."
                    }).encode("utf-8"))
                    return

                remaining = MAX_OTP_ATTEMPTS - current_fails
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": f"[INVALID_OTP] // KODE SALAH! Sisa {remaining}x kesempatan sebelum IP terkunci 24 jam."
                }).encode("utf-8"))
            return

        # 3. Resend OTP
        if self.path == "/api/resend-otp":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8", "replace")
            try:
                data = json.loads(body)
                otp_token = data.get("otp_token", "")
            except Exception:
                self.send_response(400)
                self.end_headers()
                return

            entry = PENDING_OTPS.get(otp_token)
            if not entry:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "Sesi tidak ditemukan"}).encode("utf-8"))
                return

            new_code = "".join([secrets.choice("0123456789") for _ in range(6)])
            entry["code"] = new_code
            entry["expires"] = time.time() + 180

            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            tg_msg = (
                f"🔄 <b>[TOPOLOGY // 2FA] KODE OTP BARU</b>\n"
                f"• <b>IP:</b> <code>{client_ip}</code>\n"
                f"• <b>Waktu:</b> <code>{now_str}</code>\n"
                f"• <b>KODE OTP:</b> <code>{new_code}</code>\n\n"
                f"⚠️ <i>Maksimal 2x input salah. Jika salah 2x, IP terkunci 24 jam!</i>"
            )
            send_telegram_async(tg_msg)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "expires_in": 180}).encode("utf-8"))
            return

        # 4. Logout
        if self.path == "/api/logout":
            cookie_header = self.headers.get("Cookie")
            if cookie_header:
                try:
                    c = cookies.SimpleCookie(cookie_header)
                    token = c.get("topology_session")
                    if token and token.value in SESSIONS:
                        del SESSIONS[token.value]
                except Exception:
                    pass

            sec_attr = "; Secure" if self.is_https() else ""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"topology_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax{sec_attr}")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            return

        # 5. Save / Reset Layout
        if self.path == "/api/layout":
            if not self.is_authenticated():
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "Unauthorized"}).encode("utf-8"))
                return
            self.handle_save_layout()
            return

        self.send_response(404)
        self.end_headers()

    def serve_layout(self):
        with _lock:
            cur_layout = state.get("layout", {})
        body = json.dumps({"ok": True, "layout": cur_layout}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def handle_save_layout(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8", "replace")
        try:
            req_data = json.loads(body)
            new_layout = req_data.get("layout", {})
            if isinstance(new_layout, dict):
                with _lock:
                    state["layout"] = new_layout
                save_layout(new_layout)

                # Broadcast updated payload via SSE so all connected devices sync instantly
                try:
                    payload = _build_payload()
                    _broadcast(json.dumps(payload).encode("utf-8"))
                except Exception:
                    pass

                res = json.dumps({"ok": True, "count": len(new_layout)}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(res)))
                self.end_headers()
                self.wfile.write(res)
                return
        except Exception as e:
            print(f"[Layout] Error handling save: {e}")

        err = json.dumps({"ok": False, "error": "Invalid payload"}).encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(err)))
        self.end_headers()
        self.wfile.write(err)

    def serve_sse(self):
        """
        Server-Sent Events endpoint.
        Client connects once; server pushes updates every ~2s forever.
        """
        self.send_response(200)
        self.send_header("Content-Type",  "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection",    "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        wf = self.wfile
        with _sse_lock:
            _sse_clients.append(wf)

        try:
            payload = _build_payload()
            msg = b"data: " + json.dumps(payload).encode() + b"\n\n"
            wf.write(msg)
            wf.flush()
        except Exception:
            pass

        try:
            while True:
                time.sleep(30)
                wf.write(b": heartbeat\n\n")
                wf.flush()
        except Exception:
            pass
        finally:
            with _sse_lock:
                if wf in _sse_clients:
                    _sse_clients.remove(wf)

    def serve_json(self):
        payload = _build_payload()
        body    = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control",  "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_traffic_stats(self):
        stats = traffic_db.get_traffic_summary()
        body = json.dumps({"ok": True, "stats": stats}).encode()
        self.send_response(200)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control",  "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_traffic_history(self):
        history = traffic_db.get_daily_history(30)
        body = json.dumps({"ok": True, "history": history}).encode()
        self.send_response(200)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control",  "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, fname, ctype):
        base  = os.path.dirname(os.path.abspath(__file__))
        fpath = os.path.join(base, fname)
        try:
            with open(fpath, "rb") as f:
                data = f.read()
            if fname.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type",   ctype)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")


if __name__ == "__main__":
    print(f"[*] Homelab Dashboard — Real-Time Edition")
    print(f"[*] Proxmox: {PVE_HOST}  Gateway: {GATEWAY}")

    # Initial load
    read_arp()
    try:
        pve_login()
        fetch_pve_vms()
    except Exception as e:
        print(f"[!] PVE initial error (will retry): {e}")

    # Pre-warm NIC delta (first call always returns 0 — run twice)
    get_host_nic_speeds()

    # Start real-time background loop
    threading.Thread(target=realtime_loop, daemon=True).start()
    print(f"[+] Real-time loop started (2s interval)")

    # Start HTTP server (threaded so SSE connections don't block each other)
    server = ThreadingHTTPServer(("", PORT), Handler)
    server.timeout = 1
    print(f"[+] Server ready -> http://localhost:{PORT}")
    print(f"[+] SSE stream   -> http://localhost:{PORT}/api/stream\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopped.")
