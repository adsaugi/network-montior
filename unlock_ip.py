#!/usr/bin/env python3
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCKED_FILE = os.getenv("LOCKED_IPS_FILE", os.path.join(BASE_DIR, ".locked_ips.json"))

def list_locked():
    if not os.path.exists(LOCKED_FILE):
        print("No locked IPs recorded.")
        return
    with open(LOCKED_FILE, "r") as f:
        data = json.load(f)
    if not data:
        print("No currently locked IPs.")
        return
    print("=== CURRENTLY LOCKED IPs (TOPOLOGY 24H LOCK) ===")
    now = time.time()
    for ip, info in list(data.items()):
        unlock = info.get("unlock_time", 0)
        remaining = int(unlock - now)
        if remaining > 0:
            hrs = remaining // 3600
            mins = (remaining % 3600) // 60
            print(f"IP: {ip} | Reason: {info.get('reason')} | Sisa waktu: {hrs} jam {mins} menit ({remaining} detik)")
        else:
            print(f"IP: {ip} | EXPIRED (sudah otomatis terbuka)")

def unlock(ip):
    if not os.path.exists(LOCKED_FILE):
        print("No locked file exists.")
        return
    with open(LOCKED_FILE, "r") as f:
        data = json.load(f)
    if ip in data:
        del data[ip]
        with open(LOCKED_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"IP {ip} berhasil dibuka (unlocked)!")
    else:
        print(f"IP {ip} tidak sedang terkunci.")

def clear_all():
    with open(LOCKED_FILE, "w") as f:
        json.dump({}, f)
    print("Semua IP berhasil dibuka kuncinya!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        list_locked()
        print("\nPenggunaan:")
        print("  python3 unlock_ip.py list")
        print("  python3 unlock_ip.py unlock <IP>")
        print("  python3 unlock_ip.py clear")
    elif sys.argv[1] in ("list", "show"):
        list_locked()
    elif sys.argv[1] in ("unlock", "unblock") and len(sys.argv) > 2:
        unlock(sys.argv[2])
    elif sys.argv[1] in ("clear", "reset"):
        clear_all()
