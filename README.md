# 🌐 Network Monitor & Homelab Real-Time Topology Dashboard

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)
[![Architecture](https://img.shields.io/badge/Architecture-Homelab%20%2F%20Zero--Trust-cyan.svg)](#arsitektur--cara-kerja)
[![UI](https://img.shields.io/badge/Theme-Cyberpunk%20Canvas-neon.svg)](#fitur-utama)

Dashboard visual interaktif pemantau topologi jaringan, node server homelab, throughput bandwidth real-time, dan status mesh network (Tailscale/LAN) yang dilengkapi dengan sistem keamanan **Zero-Leak 2FA Telegram Gate** dan **24H IP Shield**.

---

## 📑 Daftar Isi
1. [Tentang Project](#tentang-project)
2. [Fitur Utama](#fitur-utama)
3. [Arsitektur & Cara Kerja](#arsitektur--cara-kerja)
4. [Prasyarat Sistem (Prerequisites)](#prasyarat-sistem-prerequisites)
5. [Panduan Instalasi & Deploy](#panduan-instalasi--deploy)
   - [Langkah 1: Clone Repository](#langkah-1-clone-repository)
   - [Langkah 2: Setup Python Virtual Environment](#langkah-2-setup-python-virtual-environment)
   - [Langkah 3: Konfigurasi Environment (.env)](#langkah-3-konfigurasi-environment-env)
   - [Langkah 4: Jalankan Server](#langkah-4-jalankan-server)
   - [Langkah 5: Konfigurasi Auto-Start (Systemd Service)](#langkah-5-konfigurasi-auto-start-systemd-service)
   - [Langkah 6: Konfigurasi Reverse Proxy Nginx (Opsional)](#langkah-6-konfigurasi-reverse-proxy-nginx-opsional)
6. [Fitur Keamanan & Cara Membuka IP Terkunci](#fitur-keamanan--cara-membuka-ip-terkunci)
7. [Dokumentasi API](#dokumentasi-api)
8. [Struktur File](#struktur-file)
9. [Troubleshooting](#troubleshooting)

---

## 🎯 Tentang Project

Project ini dibangun untuk memberikan visibilitas penuh atas ekosistem homelab dan jaringan multi-node secara real-time tanpa membebani browser atau server. Menggunakan arsitektur streaming hemat resource (Server-Sent Events), dashboard menampilkan peta topologi node dinamis yang interaktif berbasis HTML5 Canvas, mulai dari Router Gateway, Proxmox VE Hypervisor (QEMU VM & LXC Containers), Tailscale VPN Mesh Peers, hingga perangkat klien di jaringan lokal (ARP scanning).

---

## 🚀 Fitur Utama

- 🎨 **Interactive Canvas Topology Map**: 
  - Visualisasi grafis node dinamis (Router, Server, VM, LXC, Tailscale, Client LAN).
  - Drag-and-drop node dengan auto-save koordinat ke `layout.json`.
  - Dukungan Zoom (Scroll), Pan (Drag Canvas), dan Collapse/Expand cluster node.
  - Switch tema Dark Mode (Cyberpunk Black) & Light Mode.

- ⚡ **Real-Time Bandwidth & Throughput (1s SSE Push)**:
  - Streaming data metrik per detik menggunakan endpoint Server-Sent Events (`/api/stream`).
  - Menghitung delta transfer data aktual (KB/s upload/download) per interface dan VM.
  - Grafik mini sparkline real-time saat hover node.

- 📊 **Persistent Bandwidth & Historical Traffic (SQLite WAL)**:
  - Menyimpan total pemakaian bandwidth secara permanen di database lokal SQLite (`traffic.db`).
  - **Aman dari Reboot**: Data penggunaan tidak hilang saat server, host Proxmox, VM, atau dashboard di-restart berkat delta-tracking logic.
  - **Filter Waktu Dinamis**: Pantau pemakaian **Hari Ini (Today)**, **7 Hari (Week)**, **Bulan Ini (Month)**, atau **Sepanjang Waktu (All-Time)** langsung dari top bar.
  - **Breakdown Modal & Visualizer**: Klik widget USAGE di header untuk membuka rincian statistik komprehensif dan tabel riwayat pemakaian harian 30 hari terakhir dengan visualisasi rasio RX/TX.
  - Endpoint API baru: `/api/traffic/stats` & `/api/traffic/history`.

- 🖥️ **Integrasi Penuh Proxmox VE API**:
  - Auto-discovery VM QEMU dan Container LXC langsung dari cluster Proxmox.
  - Membaca statistik network interface (`netin`/`netout`), memory, CPU, dan status aktif.

- 🔗 **Tailscale Mesh VPN Integration**:
  - Membaca status node Tailscale aktif secara remote via SSH / local CLI.
  - Menampilkan IP Tailscale, nama perangkat, throughput bytes, dan status koneksi peer.

- 🔍 **Local ARP Scanner & Device Discovery**:
  - Auto-scan subnet lokal (`/proc/net/arp`) secara berkala untuk memetakan perangkat WiFi & LAN.
  - Identifikasi MAC Vendor dan hostname perangkat.

- 🛡️ **Zero-Leak 2FA Telegram Gate & 24H IP Shield**:
  - **Tahap 1**: Master Password Gate (diverifikasi menggunakan SHA-256 hash).
  - **Tahap 2**: 2FA OTP 6 digit yang dikirim langsung ke bot Telegram pribadi (kedaluwarsa 60 detik).
  - **Rate Limiting**: Maksimal 5x percobaan password sebelum throttle.
  - **24H Lockdown**: Jika gagal OTP 2x, IP penyerang langsung dikunci selama 24 jam dengan tampilan locked screen.
  - **Tool Emergency Unlock**: Script CLI `unlock_ip.py` untuk menginspeksi atau membuka kunci IP yang terblokir.

---

## 🏗️ Arsitektur & Cara Kerja

```
                                 [ Browser Klien ]
                                         │
                         HTTPS / WSS (Nginx Reverse Proxy)
                                         │
                                 ┌───────▼────────┐
                                 │   PORT: 3000   │
                                 │   server.py    │
                                 └───────┬────────┘
                                         │
          ┌──────────────────────────────┼──────────────────────────────┐
          │                              │                              │
   ┌──────▼──────┐               ┌───────▼───────┐             ┌────────▼────────┐
   │ Proxmox VE  │               │   Tailscale   │             │   Subnet LAN    │
   │  API (8006) │               │ VPN Mesh Node │             │  ARP Table Scan │
   │ (QEMU / LXC)│               │ (SSH Status)  │             │ (/proc/net/arp) │
   └─────────────┘               └───────────────┘             └─────────────────┘
          │
          ▼
   [ 2FA Security ] ──> Telegram Bot API (Push OTP ke HP Admin)
```

1. **Frontend**: Merender canvas topologi, mendengarkan event stream `/api/stream`, dan mengupdate state node setiap detik.
2. **Backend**: Thread background mengumpulkan metrik dari Proxmox VE API, Tailscale, dan file sistem Linux, lalu mendistribusikannya ke semua klien web yang terhubung.
3. **Auth Guard**: Melindungi seluruh static asset dan API di balik cookie terenkripsi (`topology_session`) dengan flag `HttpOnly` dan `SameSite=Lax`.

---

## 💻 Prasyarat Sistem (Prerequisites)

- **OS**: Linux (Debian 11/12, Ubuntu 20.04/22.04/24.04, Proxmox VE Host/LXC)
- **Python**: Versi `3.9` atau lebih baru
- **sshpass** *(hanya jika membaca status Tailscale dari server remote via SSH)*:
  ```bash
  sudo apt update && sudo apt install -y sshpass
  ```

---

## 📦 Panduan Instalasi & Deploy

### Langkah 1: Clone Repository
```bash
git clone https://github.com/adsaugi/network-montior.git
cd network-montior
```

### Langkah 2: Setup Python Virtual Environment
Gunakan virtual environment agar dependensi Python terisolasi rapi:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Langkah 3: Konfigurasi Environment (`.env`)
Salin file template `.env.example` menjadi `.env`:
```bash
cp .env.example .env
nano .env
```

Sesuaikan parameter berikut:
```ini
PORT=3000

# Proxmox VE API
PVE_HOST=192.168.1.99:8006
PVE_USER=root@pam
PVE_PASS=PasswordProxmoxLo

# Subnet & Gateway
GATEWAY=192.168.1.1
SUBNET=192.168.1.

# Tailscale Integration (Remote Host VPN)
TS_SSH_USER=root
TS_SSH_PASS=PasswordHostVPN
TS_SSH_HOST=192.168.1.104

# 2FA Telegram Bot & Chat ID
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

# SHA-256 Hash Master Password
# Contoh cara generate hash: echo -n "PasswordRahasiaLo" | sha256sum
MASTER_PASSWORD_HASH=a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3
```

> **Tips Generate Password Hash**:
> Jalankan perintah berikut di terminal untuk mendapatkan string SHA-256 dari password yang ingin lo pakai:
> ```bash
> echo -n "PasswordPilihanLo" | sha256sum | awk '{print $1}'
> ```

---

### Langkah 4: Jalankan Server (Testing Manual)
Untuk menguji coba apakah konfigurasi sudah berjalan dengan benar:
```bash
./venv/bin/python server.py
```
Akses dashboard di browser lo:
```
http://<IP_SERVER>:3000
```

---

### Langkah 5: Konfigurasi Auto-Start (Systemd Service)
Agar dashboard selalu berjalan di background dan otomatis menyala saat server reboot:

1. Buat file service systemd:
   ```bash
   sudo nano /etc/systemd/system/topology.service
   ```
2. Tempelkan konfigurasi berikut (sesuaikan path folder jika berbeda):
   ```ini
   [Unit]
   Description=Homelab Real-Time Topology & Network Monitor Dashboard
   After=network.target

   [Service]
   Type=simple
   User=xs
   WorkingDirectory=/home/xs/deploy_server/tailscale-dashboard
   ExecStart=/home/xs/deploy_server/tailscale-dashboard/venv/bin/python server.py
   Restart=always
   RestartSec=3
   EnvironmentFile=-/home/xs/deploy_server/tailscale-dashboard/.env

   [Install]
   WantedBy=multi-user.target
   ```
3. Aktifkan dan jalankan servicenya:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now topology.service
   sudo systemctl status topology.service
   ```

---

### Langkah 6: Konfigurasi Reverse Proxy Nginx (Opsional)
Jika lo ingin mengakses dashboard via domain atau subdomain dengan SSL HTTPS (misal `topology.domain.com`):

```nginx
server {
    listen 80;
    server_name topology.domain.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;

        # Header standard
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Wajib untuk Server-Sent Events (SSE) /api/stream
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

---

## 🔒 Fitur Keamanan & Cara Membuka IP Terkunci

Jika ada pengguna atau lo sendiri salah memasukkan kode OTP 2x berturut-turut, sistem akan mengunci IP tersebut selama 24 jam dengan respon HTTP 423 Locked.

### Manajemen IP Terkunci (`unlock_ip.py`)
Gunakan utility CLI `unlock_ip.py` dari terminal server:

1. **Melihat daftar IP yang sedang terkunci**:
   ```bash
   python3 unlock_ip.py list
   ```
2. **Membuka kunci IP tertentu**:
   ```bash
   python3 unlock_ip.py unlock 192.168.1.50
   ```
3. **Membuka kunci semua IP sekaligus**:
   ```bash
   python3 unlock_ip.py clear
   ```

---

## 📡 Dokumentasi API

| Endpoint | Method | Autentikasi | Keterangan |
|---|---|---|---|
| `/` | `GET` | Sesi Login | Halaman utama visualizer topologi jaringan. |
| `/api/login` | `POST` | Public | Submit master password untuk request kode OTP Telegram. |
| `/api/verify-otp`| `POST` | Public | Validasi 6-digit OTP Telegram & menerbitkan cookie sesi. |
| `/api/resend-otp`| `POST` | Public | Kirim ulang OTP baru ke Telegram jika kedaluwarsa. |
| `/api/logout` | `POST` | Sesi Login | Menghapus sesi dan menghancurkan cookie login. |
| `/api/stream` | `GET` | Sesi Login | **Server-Sent Events (SSE)** data metrik real-time setiap 1 detik. |
| `/api/data` | `GET` | Sesi Login | Snapshot JSON data topologi (on-demand). |
| `/api/layout` | `GET/POST`| Sesi Login | Mengambil atau menyimpan koordinat custom posisi node. |
| `/api/traffic/stats` | `GET` | Sesi Login | Ringkasan akumulasi traffic (Hari ini, 7 hari, Bulan ini, All-time). |
| `/api/traffic/history`| `GET` | Sesi Login | Riwayat breakdown harian pemakaian bandwidth (30 hari terakhir). |

---

## 📁 Struktur File

```
tailscale-dashboard/
├── app.js                 # Engine frontend canvas renderer, dragging, panning & visualizer
├── index.html             # UI utama dashboard topologi
├── style.css              # Styling CSS tema cyberpunk dark & light
├── traffic_db.py          # Modul manajemen database SQLite persistensi bandwidth
├── traffic.db             # File database SQLite lokal (auto-created saat server running)
├── server.py              # Server backend HTTP + SSE streamer + Proxmox/Tailscale aggregator
├── layout.json            # File persistensi koordinat tata letak node
├── topology_login.html    # Form login master key & input OTP Telegram (cyber neon)
├── topology_locked.html   # Layar tampilan peringatan 24 jam IP lockout
├── unlock_ip.py           # Tool CLI untuk membuka blokir IP secara instan
├── start.sh               # Runner script dengan auto-restart dan log rotator
├── requirements.txt       # Daftar package Python yang dibutuhkan
├── .env.example           # Template environment variable
├── .gitignore             # Proteksi file credentials, venv, dan logs
└── systemd/
    └── topology.service   # Template unit file systemd daemon
```

---

## 🛠️ Troubleshooting

- **Topologi tidak muncul / Loading terus menerus**:
  Pastikan Nginx reverse proxy menonaktifkan buffering (`proxy_buffering off;`) agar stream SSE `/api/stream` tidak tertahan di buffer proxy.
- **Node Tailscale Offline**:
  Pastikan host tempat dashboard berjalan bisa SSH ke node Tailscale tanpa interaksi manual (`StrictHostKeyChecking=no`).
- **Gagal Login Telegram OTP**:
  Pastikan `TELEGRAM_BOT_TOKEN` valid dan lo sudah pernah menekan `/start` pada bot tersebut dengan akun yang memiliki `TELEGRAM_CHAT_ID` yang sesuai.

---

## 📄 License
Didistribusikan di bawah lisensi MIT. Silakan gunakan dan modifikasi untuk kebutuhan homelab lo sendiri!
