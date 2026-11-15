#!/usr/bin/env python3
"""
Lightweight Client Traffic Reporter
Runs on any client (PC, Linux, Laptop, or Android phone via Termux)
to report network throughput and byte deltas directly to the Tailscale Dashboard.
"""

import sys
import time
import json
import socket
import os
try:
    import urllib.request as urlreq
except ImportError:
    pass

# Dashboard Server IP / URL (Change if running from outside LAN or over Tailscale)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://192.168.1.100:3000/api/client/report")
DEVICE_NAME = os.environ.get("DEVICE_NAME", socket.gethostname())
REPORT_INTERVAL = float(os.environ.get("REPORT_INTERVAL", "3.0"))

def get_net_bytes():
    """
    Returns (rx_bytes, tx_bytes) across primary network interfaces.
    """
    rx_total = 0
    tx_total = 0

    # 1. Linux & Android Termux: /proc/net/dev
    if os.path.exists("/proc/net/dev"):
        try:
            with open("/proc/net/dev", "r") as f:
                for line in f.readlines()[2:]:
                    parts = line.split(":")
                    if len(parts) != 2:
                        continue
                    iface = parts[0].strip()
                    if iface == "lo" or "docker" in iface or "veth" in iface:
                        continue
                    cols = parts[1].split()
                    if len(cols) >= 9:
                        rx_total += int(cols[0])
                        tx_total += int(cols[8])
            return rx_total, tx_total
        except Exception:
            pass

    # 2. psutil fallback (Windows, macOS, Linux)
    try:
        import psutil
        counters = psutil.net_io_counters(pernic=True)
        for iface, s in counters.items():
            if "loopback" in iface.lower() or "pseudo" in iface.lower() or "vethernet" in iface.lower():
                continue
            rx_total += s.bytes_recv
            tx_total += s.bytes_sent
        return rx_total, tx_total
    except ImportError:
        pass

    return 0, 0

def main():
    print(f"[*] Starting Traffic Reporter for: {DEVICE_NAME}")
    print(f"[*] Target Dashboard: {DASHBOARD_URL}")
    print(f"[*] Interval: {REPORT_INTERVAL}s")

    prev_rx, prev_tx = get_net_bytes()
    prev_time = time.time()

    while True:
        time.sleep(REPORT_INTERVAL)
        now = time.time()
        elapsed = now - prev_time
        cur_rx, cur_tx = get_net_bytes()

        if elapsed <= 0 or (cur_rx == 0 and cur_tx == 0):
            continue

        rx_delta = max(0, cur_rx - prev_rx)
        tx_delta = max(0, cur_tx - prev_tx)
        rx_kbps = round((rx_delta / elapsed) / 1024, 1)
        tx_kbps = round((tx_delta / elapsed) / 1024, 1)

        prev_rx, prev_tx = cur_rx, cur_tx
        prev_time = now

        payload = json.dumps({
            "name": DEVICE_NAME,
            "rx_delta": rx_delta,
            "tx_delta": tx_delta,
            "rx_kbps": rx_kbps,
            "tx_kbps": tx_kbps
        }).encode("utf-8")

        try:
            req = urlreq.Request(
                DASHBOARD_URL,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urlreq.urlopen(req, timeout=3) as resp:
                pass
            print(f"[{time.strftime('%H:%M:%S')}] Sent: RX {rx_kbps} KB/s | TX {tx_kbps} KB/s")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Report error: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
