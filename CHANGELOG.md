# 📋 Changelog

Semua perubahan penting pada project **Network Monitor & Homelab Real-Time Topology Dashboard** akan didokumentasikan di file ini.

Format changelog mengikuti pedoman [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) dan project ini menganut [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.1.0] - 2026-11-15

### 🚀 Ditambahkan (Added)
- **Persistent Bandwidth Storage (SQLite WAL)**:
  - Implementasi modul `traffic_db.py` menggunakan SQLite embedded database (tanpa dependensi eksternal tambahan).
  - Mode SQLite WAL (`PRAGMA journal_mode=WAL`) & synchronous normal untuk operasi I/O super cepat dan tahan crash / mati lampu (ACID compliant).
  - Skema tabel `traffic_hourly` yang mengagregasi data transfer per jam dan per tanggal secara otomatis.
- **Delta-Tracking Anti Reboot Reset**:
  - Algoritma delta tracking tingkat interface dan VM Proxmox.
  - Membedakan pertambahan bytes normal vs reboot counter rollover ($RX_{current} < RX_{previous}$) sehingga data total tidak pernah ter-reset kembali ke 0 saat server, host Proxmox, VM, ataupun daemon dashboard direstart.
  - Auto-seeding baseline saat pertama kali diinstal agar total pemakaian berjalan tidak hilang.
- **Interactive Top Bar View Switcher**:
  - Filter rentang waktu pemantauan di top bar:
    - **HARI INI (Today)**
    - **7 HARI (Last 7 Days)**
    - **BULAN INI (Current Month)**
    - **ALL-TIME (Sepanjang Waktu)**
  - Pilihan periode tersimpan otomatis di `localStorage` browser pengguna.
- **Traffic Usage Breakdown Modal**:
  - Klik pada widget `USAGE (RX/TX)` di header membuka dialog modal analitik cyberpunk dengan animasi glassmorphism.
  - 4 Kartu metrik interaktif (Hari Ini, 7 Hari Terakhir, Bulan Ini, Total All-Time) dengan rincian total download (RX) dan upload (TX).
  - Tabel riwayat harian 30 hari terakhir lengkap dengan progress bar visualisasi rasio traffic download vs upload.
  - Dukungan tombol keyboard `Escape` dan klik backdrop untuk menutup modal.
- **Endpoint API Baru**:
  - `GET /api/traffic/stats`: Menghasilkan ringkasan penggunaan bandwidth per periode waktu (Today, Week, Month, All-time).
  - `GET /api/traffic/history`: Menghasilkan data array riwayat penggunaan harian selama 30 hari terakhir.
- **Payload SSE Real-Time**:
  - Integrasi objek `trafficStats` langsung ke dalam stream SSE (`/api/stream`) dan data snapshot (`/api/data`).

### 🔧 Diperbaiki & Dioptimalkan (Fixed & Improved)
- Pemisahan kalkulasi kecepatan live throughput (Mbps/Kbps) dari nilai akumulasi byte historis agar nilai total usage tidak fluktuatif atau ter-overwrite secara acak.
- Menambahkan aturan ignore `*.db`, `*.db-wal`, `*.db-shm` ke `.gitignore` untuk menjaga integritas database lokal.

---

## [v1.0.0] - 2026-11-15

### 🚀 Initial Release
- Interactive HTML5 Canvas Topology Map dengan dukungan drag-and-drop, zoom, pan, dan multi-select lasso.
- Real-Time 1s Server-Sent Events (SSE) data push.
- Proxmox VE API integration (auto-discovery QEMU VM & LXC Containers).
- Tailscale Mesh VPN integration via SSH CLI parsing.
- Local ARP Table Scanner (`/proc/net/arp`).
- Zero-Leak 2FA Telegram Gate & 24H IP Shield dengan utility CLI `unlock_ip.py`.
- Dark Mode (Cyberpunk Black) & Light Mode switch.
