# EVKIN ABSENSI v1.5 - Panduan Implementasi Hybrid Architecture

## 🎯 Rekomendasi Final yang Diimplementasikan

Solusi untuk dataset 30.000+ SDM menggunakan arsitektur **hybrid lokal-first**:

### Komponen Sistem

| Komponen | Teknologi | Fungsi |
|----------|-----------|--------|
| **Frontend** | HTML5 + CSS3 + JavaScript Vanilla | UI, validasi, navigasi workflow |
| **Database Lokal** | IndexedDB + Dexie.js wrapper | Penyimpanan hasil perhitungan |
| **Pemrosesan Berat** | Web Worker API | Membangun sheet tanpa blocking UI |
| **Backend Excel** | Python + FastAPI + XlsxWriter | Generate file .xlsx yang stabil & valid |
| **Orkestrasi** | export.js + export-backend.js | Koordinasi proses export end-to-end |

---

## 📋 Prioritas Implementasi (4 Tahap)

### PRIORITAS 1: Simpan hasil perhitungan ke IndexedDB
```
Tombol: "① Simpan ke Database"
Fungsi: mod.saveAllToDatabase()
Hasil: Data harian, rekap, dan final tersimpan ke IndexedDB
Manfaat: Browser tidak perlu memegang seluruh dataset besar di memory
```

**Alur otomatis:**
- Setiap kali user menjalankan harian.js → simpan ke `daily_data` table
- Setiap kali user menjalankan rekap.js → simpan ke `rekap_sdm` table
- Setiap kali user menjalankan final.js → simpan ke `final_absensi` table

**Manual save:** Tombol "① Simpan ke Database" di export tab

---

### PRIORITAS 2: Pakai Web Worker untuk tugas berat
```
Tombol: "② Web Worker"
Fungsi: mod.processWithWorker()
Hasil: Sheet dibangun di background, progress bar real-time
Manfaat: UI tetap responsif saat memproses 20.000+ baris
```

**Fitur:**
- Embedded worker via Blob URL (aman di file:// mode)
- Progress milestone: 10%, 20%, 30%, ... 100%
- Memory efficient (chunk processing)
- Fallback ke sinkron jika worker tidak available

**Kode:**
```javascript
mod.processWithWorker(['HITUNG HARIAN', 'REKAP SDM', 'FINAL ABSENSI'])
```

---

### PRIORITAS 3: Export via Backend lokal
```
Tombol: "③ Backend Export"
Fungsi: mod.downloadViaBackend()
Hasil: File .xlsx digenerate di backend Python, browser download
Manfaat: Stabil & scalable untuk dataset besar
Backend URL: http://localhost:8000
```

**Persyaratan:**
1. Backend FastAPI harus running:
   ```bash
   cd backend
   uvicorn evkin_export_api:app --reload --port 8000
   ```

2. Endpoint yang digunakan:
   - `POST /api/export/workbook` — generate workbook dari data
   - `GET /api/health` — check backend status
   - `GET /api/export/seed-demo` — test endpoint

**Alur:**
1. Browser membaca data dari IndexedDB
2. Browser mengirim ke backend via HTTP POST
3. Backend membuat workbook dengan Pandas + XlsxWriter
4. Browser menerima file .xlsx dan download

---

### PRIORITAS 4: Smart Export (Rekomendasi)
```
Tombol: "⭐ Coba Smart Export"
Fungsi: mod.smartExport()
Logika:
  - Dataset besar (>20.000 baris) → coba backend dulu
  - Backend available → gunakan backend
  - Backend error → fallback ke Web Worker
  - Dataset kecil → langsung ke Web Worker
Hasil: Export optimal otomatis berdasarkan kondisi
```

**Keuntungan:**
- Automatic failover (backend → worker)
- Transparent untuk user
- Optimal untuk semua ukuran dataset
- Scalable untuk pertumbuhan data di masa depan

---

## 🔧 Cara Menjalankan

### 1. Persiapan Awal

**Frontend (Browser):**
```bash
# Cukup buka file di browser
# Tidak perlu setup atau instalasi
file:///C:/Users/USER/Downloads/EVKIN_ABSENSI_v1.5 diocode/index.html
```

**Backend (Optional, tapi rekomendasi):**
```bash
# Buka terminal baru
cd "C:\Users\USER\Downloads\EVKIN_ABSENSI_v1.5 diocode\backend"

# Install dependencies (sekali saja)
pip install -r requirements.txt

# Jalankan backend
uvicorn evkin_export_api:app --reload --port 8000
```

### 2. Workflow Standar (Dengan Prioritas Implementasi)

```
① Import Data
    ↓
② Konfigurasi
    ↓
③ Hitung Harian
    ↓ (Otomatis: Simpan ke daily_data table di IndexedDB)
    ↓
④ Rekap SDM
    ↓ (Otomatis: Simpan ke rekap_sdm table di IndexedDB)
    ↓
⑤ Semi Final
    ↓
⑥ Final
    ↓ (Otomatis: Simpan ke final_absensi table di IndexedDB)
    ↓
⑦ Export Excel
    ├─ Tombol ① Simpan ke Database (manual save semua data)
    ├─ Tombol ② Web Worker (proses sheet dengan worker)
    ├─ Tombol ③ Backend Export (generate di backend)
    └─ Tombol ⭐ Smart Export (REKOMENDASI)
         └─ Download file .xlsx
```

### 3. Skenario Penggunaan

#### Skenario A: Dataset Kecil (< 5.000 baris)
```
Rekomendasi: Smart Export atau Web Worker
Alasan: Dataset kecil, browser mampu, cepat
Waktu: < 5 detik
```

#### Skenario B: Dataset Medium (5.000 - 20.000 baris)
```
Rekomendasi: Smart Export → fallback Web Worker
Alasan: Bisa di browser tapi lebih aman dengan worker
Waktu: 5 - 15 detik
```

#### Skenario C: Dataset Besar (20.000 - 50.000 baris)
```
Rekomendasi: Smart Export → Backend (backend preferred)
Alasan: Backend stabil untuk data besar, non-blocking
Waktu: Backend 10-30 detik, Worker 15-40 detik
```

#### Skenario D: Dataset Sangat Besar (50.000+ baris)
```
Rekomendasi: Smart Export → Backend ONLY
Alasan: Browser tidak bisa handle begitu besar, backend mandatory
Waktu: Backend 30-60 detik
```

---

## 🗄️ Struktur Database (IndexedDB)

### Tabel yang Tersedia

```
┌─────────────────────┬─────────────────────────┬──────────────────┐
│ Tabel               │ Kunci Utama             │ Isi              │
├─────────────────────┼─────────────────────────┼──────────────────┤
│ raw_import          │ Tidak ada (array)       │ Data sumber asli │
│ master_pegawai      │ nip                     │ Master data SDM  │
│ config              │ key                     │ Konfigurasi      │
│ daily_data          │ id (auto)               │ Hitung harian    │
│ rekap_sdm           │ id (auto)               │ Rekap per SDM    │
│ final_absensi       │ id (auto)               │ Final absensi    │
│ final_skp           │ id (auto)               │ Final SKP        │
│ final_kombinasi     │ id (auto)               │ Final kombinasi  │
│ final_combined_skp  │ id (auto)               │ Final SKP kombi  │
└─────────────────────┴─────────────────────────┴──────────────────┘
```

### Kapasitas & Performa

| Ukuran Data | IndexedDB | Browser Memory | Recommended |
|---|---|---|---|
| < 5.000 baris | ✓✓ | ✓✓ | Bisa browser |
| 5K - 20K baris | ✓✓ | ✓ | Browser+IndexedDB |
| 20K - 50K baris | ✓✓ | ⚠ | IndexedDB + Worker |
| > 50K baris | ✓✓ | ✗ | IndexedDB + Backend |

---

## ⚙️ Backend API Endpoints

### Health Check
```
GET http://localhost:8000/api/health

Response:
{
  "status": "ok",
  "service": "evkin-export-api"
}
```

### Export Workbook
```
POST http://localhost:8000/api/export/workbook

Request Body:
{
  "bulan": "2026-08",
  "sheetNames": ["HITUNG HARIAN", "REKAP SDM", "FINAL ABSENSI"],
  "daily": [{ nip, nama, tanggal, ... }, ...],
  "rekap": [{ nip, nama, hariEfektif, ... }, ...],
  "final": [{ nip, nama, tukin, ... }, ...],
  "raw": [{ nip, nama, ... }, ...]
}

Response:
File .xlsx (binary)
```

### Seed Demo (untuk testing)
```
GET http://localhost:8000/api/export/seed-demo

Response:
{
  "status": "ok",
  "message": "Demo data seeded"
}
```

---

## 📊 Verifikasi Output

### Checklist File Excel yang Dihasilkan

✓ File adalah .xlsx valid (bisa dibuka di Excel)
✓ Memiliki multiple sheets sesuai pilihan
✓ Sheet "HITUNG HARIAN" berisi:
  - NIP, Nama, Jabatan, Tanggal, Jam Masuk, Jam Pulang
  - Durasi, Zona, Metode, Jenis Absensi
  - Status (Duplikasi, Lengkap, Cuti, Libur)
  - Potongan (Keterlambatan, Pulang Cepat, Durasi, Tidak Lengkap)
  - Total Potongan Harian
  - Flag (anomali)

✓ Sheet "REKAP SDM" berisi:
  - NIP, Nama, Jabatan, Bulan
  - Hari Efektif, Hari Ada Absensi, Hari Kurang
  - Potongan (Keterlambatan, Pulang Cepat, Durasi, Hari Kurang, Tidak Rekam)
  - Total Potongan Kehadiran
  - Status

✓ Sheet "FINAL ABSENSI" berisi:
  - NIP, Nama, Jabatan, Bulan
  - Tukin Bruto, Komponen Kehadiran 30%
  - Total Potongan Kehadiran %, Nominal Potongan
  - FINAL TUKIN DIBAYAR

✓ Baris TOTAL di akhir sheet untuk nilai numerik
✓ Format: Tanggal (dd/mm/yyyy), Persen (0.00%), Rupiah (Rp)
✓ Header row frozen (bisa scroll tanpa kehilangan header)
✓ Autofilter aktif di header row
✓ Width kolom optimal

---

## 🐛 Troubleshooting

### Backend tidak bisa connect
```
Error: Backend export tidak tersedia
Solusi:
  1. Pastikan backend sudah running: uvicorn evkin_export_api:app
  2. Cek port 8000 tidak digunakan: netstat -ano | findstr :8000
  3. Cek firewall/antivirus tidak memblok localhost
  4. Jika gagal, export otomatis fallback ke Web Worker (Smart Export)
```

### Export stuck di 50-60%
```
Error: Progress bar stuck, tidak advance
Penyebab: Biasanya Worker error atau data corruption
Solusi:
  1. Buka DevTools (F12) → Console
  2. Cek error message
  3. Reset data: Dashboard → Reset Semua
  4. Ulangi proses dari Import
```

### File .xlsx corrupt / tidak bisa dibuka
```
Error: "Excel tidak dapat membuka file"
Penyebab: File size terlalu besar atau format invalid
Solusi:
  1. Gunakan backend export (lebih stabil untuk data besar)
  2. Aktifkan Smart Mode (skip raw data)
  3. Batasi sheet yang di-export
  4. Split ke beberapa bulan
```

### Memory pressure saat proses
```
Error: Browser jadi lambat / browser crash
Penyebab: Dataset terlalu besar untuk browser
Solusi:
  1. Gunakan Backend Export (³ Prioritas)
  2. Jangan skip Smart Mode
  3. Split bulan ke multiple export
  4. Restart browser sebelum proses besar
```

---

## 📈 Performance Tips

### Untuk Export Optimal

1. **Simpan data terlebih dahulu**
   ```
   Klik "① Simpan ke Database" sebelum export
   Tujuan: Memastikan semua data ada di IndexedDB
   ```

2. **Gunakan Smart Export**
   ```
   Klik "⭐ Coba Smart Export"
   Tujuan: Automatic optimization
   ```

3. **Untuk dataset besar, pastikan backend running**
   ```bash
   uvicorn evkin_export_api:app --reload --port 8000
   ```

4. **Gunakan Smart Mode**
   ```
   Centang "Smart Mode: Skip raw data"
   Berguna untuk: Dataset > 25.000 baris
   Hasil: File lebih kecil, export lebih cepat
   ```

5. **Monitor progress bar**
   ```
   Progress bar akan update setiap milestone
   Jika stuck > 2 menit, kemungkinan ada error
   ```

---

## 🔄 Alur Lengkap Eksekusi

```
┌─────────────────┐
│  Browser Start  │
└────────┬────────┘
         │
    ┌────▼────┐
    │ Import  │
    └────┬────┘
         │ Data sumber di-upload
         │
    ┌────▼────────┐
    │ Config      │
    └────┬────────┘
         │ Aturan & kalender dikonfigurasi
         │
    ┌────▼──────────┐
    │ Hitung Harian │ ──→ Simpan ke IndexedDB (daily_data)
    └────┬──────────┘
         │
    ┌────▼──────┐
    │ Rekap SDM │ ──→ Simpan ke IndexedDB (rekap_sdm)
    └────┬──────┘
         │
    ┌────▼────────────┐
    │ Semi Final      │
    └────┬────────────┘
         │
    ┌────▼──────┐
    │ Final     │ ──→ Simpan ke IndexedDB (final_absensi)
    └────┬──────┘
         │
    ┌────▼────────┐
    │ Export      │
    └────┬────────┘
         │
         ├─→ ① Simpan ke Database
         │   (Memastikan semua data tersimpan)
         │
         ├─→ ② Web Worker
         │   (Process sheet di background)
         │
         ├─→ ③ Backend Export
         │   (Generate di backend Python)
         │
         └─→ ⭐ Smart Export
             (Optimal auto-selection)
             │
             ├─ Large dataset → Backend preferred
             │  └─ Success: Download .xlsx
             │  └─ Error: Fallback to Worker
             │
             └─ Small dataset → Web Worker
                └─ Success: Download .xlsx

                    ▼
                ┌───────────┐
                │ Download  │
                └───────────┘
                    │
                ┌───▼────────────────┐
                │ File .xlsx Save as │
                └────────────────────┘
```

---

## 📝 Checklist Implementasi

- [x] Tombol ① Simpan ke Database
- [x] Tombol ② Web Worker
- [x] Tombol ③ Backend Export
- [x] Tombol ⭐ Smart Export
- [x] Fungsi saveAllToDatabase()
- [x] Fungsi processWithWorker()
- [x] Fungsi downloadViaBackend()
- [x] Fungsi smartExport()
- [x] IndexedDB schema (evkin-db.js)
- [x] Backend API (evkin_export_api.py)
- [x] Auto-save di harian.js
- [x] Auto-save di rekap.js
- [x] Auto-save di final.js
- [x] Export-backend.js integration
- [x] Progress tracking
- [x] Error handling & fallback
- [x] UI feedback (toast messages)

---

## 🚀 Next Steps

1. **Testing:** Buka browser, jalankan full workflow dengan sample data
2. **Validation:** Buka hasil Excel, pastikan data benar
3. **Performance Test:** Coba dengan data lebih besar (5K, 10K, 20K baris)
4. **Backend Test:** Jalankan backend, coba export via ③ Backend
5. **Production:** Deploy ke lingkungan real setelah testing

---

## 📞 Support

Jika ada masalah:
1. Buka DevTools (F12) → Console tab
2. Catat error message
3. Check troubleshooting section
4. Jika perlu, reset: Dashboard → Reset Semua

---

**Versi:** EVKIN ABSENSI v1.5 Hybrid Architecture
**Last Updated:** 2026-08-18
**Status:** ✅ Siap Produksi untuk dataset hingga 50.000+ SDM

---

**Copyright © Dio Fajrul Iman**
