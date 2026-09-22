# Evkin Tools Diocode v.1.5 — Cara Pakai di HTTP

Aplikasi ini sudah diubah ke mode DuckDB master-only dan dapat dijalankan melalui HTTP untuk komunikasi frontend-backend yang benar.

## 1) Jalankan backend

Pilih salah satu cara:

- Klik dua kali: `START_EVKIN_TOOLS_HTTP.bat`
- Atau jalankan manual:

Launcher akan memilih Python virtual environment jika tersedia, menjalankan backend
yang juga menyajikan frontend, menunggu health check, lalu membuka browser.

## 2) Buka aplikasi di browser

Buka URL berikut:

```text
http://127.0.0.1:8000
```

Jika backend tidak aktif, browser akan menampilkan error atau tidak bisa menjalankan workflow.

## 3) Aktifkan backend di UI

Setelah aplikasi terbuka, gunakan tombol backend di halaman aplikasi untuk mengaktifkan koneksi ke DuckDB master.

## 4) Fitur database master

Data workflow utama disimpan di:

```text
backend\data\EVKIN_MASTER.duckdb
```

Semua state workflow utama diproses via backend, bukan melalui localStorage atau IndexedDB.

## 5) Health check

URL health:

```text
http://127.0.0.1:8000/api/workflow/health
```

Expected response:

```json
{"status":"ok","ready":true,...}
```

## 6) Hentikan backend

Tekan Ctrl + C di jendela terminal backend.

Catatan:
- Jika port 8000 sudah dipakai aplikasi lain, hentikan aplikasi tersebut terlebih dahulu.
- Aplikasi HTTP lebih aman dan konsisten untuk workflow master DB dibandingkan mode file://.
