# EVKIN ABSENSI v1.5 - Export Debug Guide

## Problem Identified

Export dengan data banyak gagal karena beberapa alasan:

1. **Database tidak digunakan** — Kondisi `shouldUseDatabase` terlalu ketat
2. **Fallback tidak robust** — Jika database kosong, tidak ada error handling
3. **Data mismatch** — Field names antara state dan database tidak cocok

## Fixes Applied

### Fix 1: Always Try Database First
**Before:**
```javascript
const shouldUseDatabase = (S.daily && S.daily.length > 20000) || ...
if (shouldUseDatabase && EVKIN.db) { ... }
```

**After:**
```javascript
const hasDatabaseModule = !!(EVKIN.db && typeof EVKIN.db.getAll === 'function');
if (hasDatabaseModule) { ... }
```

**Effect:** Sekarang database SELALU dicoba dulu (lebih reliable untuk semua ukuran data)

---

### Fix 2: Smart Fallback Logic
**Before:**
```javascript
const [dailyRows] = await Promise.all([
  EVKIN.db.getAll('daily_data').catch(() => []),
  ...
]);
// Langsung pakai dailyRows tanpa fallback
```

**After:**
```javascript
const [dailyRows] = await Promise.all([
  EVKIN.db.getAll('daily_data').catch(() => []),
  ...
]);

// FALLBACK: Jika database kosong, gunakan state
const usedDaily = dailyRows.length > 0 ? dailyRows : (S.daily || []);
```

**Effect:** Jika database kosong, otomatis fallback ke state data

---

### Fix 3: Better Error Messages
**Before:**
```javascript
throw new Error('Tidak ada data hasil dari database untuk diekspor');
```

**After:**
```javascript
if (!usedDaily.length && !usedRekap.length && !usedFinal.length) {
  throw new Error('Tidak ada data untuk diekspor. Pastikan: 1) Hitung Harian sudah dijalankan, 2) Rekap SDM sudah dijalankan, 3) Final sudah dijalankan');
}
```

**Effect:** User tahu masalahnya di mana

---

## Testing Steps

### Step 1: Buka DevTools
```
Browser → F12 → Console tab
```

### Step 2: Run Diagnostic
Copy-paste ke Console dan jalankan:
```javascript
// Copy isi dari diagnostic.js ke browser console
```

Atau buka file: `assets/js/diagnostic.js`

### Step 3: Check Output
Lihat hasil diagnostic:
```
S.raw.length: [jumlah]
S.daily.length: [jumlah]
S.rekap.length: [jumlah]
S.final.length: [jumlah]

DB raw_import: [jumlah]
DB daily_data: [jumlah]
DB rekap_sdm: [jumlah]
DB final_absensi: [jumlah]

Backend status: ok / error
```

### Step 4: Action Items

**Jika S.daily.length = 0:**
→ Jalankan "Hitung Harian" dulu

**Jika DB daily_data = 0:**
→ Click "① Simpan ke Database" di Export tab

**Jika Backend error:**
→ Jalankan: `uvicorn evkin_export_api:app --reload --port 8000`

**Jika semuanya 0:**
→ Start dari awal: Import data → Config → Hitung Harian → Rekap → Final

---

## Export Flow (After Fix)

```
User click ⭐ Smart Export / ③ Backend Export
    ↓
1. Database check: EVKIN.db tersedia?
    ↓ YES
2. Baca dari database:
   - daily_data table
   - rekap_sdm table
   - final_absensi table
   - raw_import table
    ↓
3. Jika database kosong → Fallback ke S.state data
    ↓
4. Check apakah ada data:
   - usedDaily.length > 0 OR
   - usedRekap.length > 0 OR
   - usedFinal.length > 0
    ↓ YES
5. Build workbook dari data
    ↓
6. Format sheets (headers, width, autofilter)
    ↓
7. Save sebagai .xlsx
    ↓
✓ Download file Excel
```

---

## Common Issues & Fixes

### Issue 1: "Tidak ada sheet yang berhasil dibuat"
**Penyebab:** Tidak ada data sama sekali
**Solusi:**
1. Buka DevTools → Console
2. Jalankan diagnostic
3. Jika semua 0, mulai dari Import

### Issue 2: "Excel tidak bisa dibuka"
**Penyebab:** File corrupt
**Solusi:**
1. Coba lagi dengan tombol ③ "Backend Export"
2. Atau click ② "Web Worker" tanpa Smart Mode

### Issue 3: "Export stuck di X%"
**Penyebab:** Worker hang atau data too large
**Solusi:**
1. Restart browser
2. Try backend export (③)
3. Split data ke beberapa bulan

### Issue 4: "Backend tidak tersedia"
**Penyebab:** Uvicorn tidak running
**Solusi:**
```bash
cd backend
uvicorn evkin_export_api:app --reload --port 8000
```

---

## Diagnostic Checklist

### Before Export
- [ ] Import data selesai (S.raw.length > 0)
- [ ] Hitung Harian selesai (S.daily.length > 0)
- [ ] Rekap SDM selesai (S.rekap.length > 0)
- [ ] Final selesai (S.final.length > 0)
- [ ] Data terlihat di UI (tabel muncul)

### Before Click Export
- [ ] Semua tahap unlocked (tidak ada kunci 🔒)
- [ ] Tab Export visible
- [ ] Tombol-tombol ada:
  - ① Simpan ke Database
  - ② Web Worker
  - ③ Backend Export
  - ⭐ Smart Export

### After Click Export
- [ ] Progress bar muncul dan bergerak
- [ ] Toast notification ada
- [ ] File .xlsx berhasil download
- [ ] Excel bisa dibuka
- [ ] Sheet ada datanya

---

## Database Content Check

Untuk cek apa yang tersimpan di IndexedDB:

```javascript
// Di Browser Console:

// 1. Check daily_data
EVKIN.db.getAll('daily_data').then(data => {
  console.log('daily_data rows:', data.length);
  console.log('Sample:', data.slice(0, 3));
});

// 2. Check rekap_sdm
EVKIN.db.getAll('rekap_sdm').then(data => {
  console.log('rekap_sdm rows:', data.length);
  console.log('Sample:', data.slice(0, 3));
});

// 3. Check final_absensi
EVKIN.db.getAll('final_absensi').then(data => {
  console.log('final_absensi rows:', data.length);
  console.log('Sample:', data.slice(0, 3));
});
```

---

## Testing with Different Data Sizes

### Test 1: Small (< 1K rows)
```
Action: ⭐ Smart Export
Expected: < 5 sec
Result: Excel dengan semua sheet
```

### Test 2: Medium (1K - 5K rows)
```
Action: ⭐ Smart Export
Expected: 5-15 sec
Result: Excel dengan semua sheet
Note: Lihat progress bar update
```

### Test 3: Large (5K - 20K rows)
```
Action: ⭐ Smart Export (database preferred)
Expected: 15-30 sec
Result: Excel dengan semua sheet
Note: Pastikan backend running!
```

### Test 4: Very Large (20K+ rows)
```
Action: ③ Backend Export (atau ⭐ Smart Export)
Expected: 30-60 sec
Result: Excel dengan semua sheet
Note: Backend WAJIB running!
```

---

## Performance Tips

1. **Untuk data > 20K baris:**
   - Pastikan backend running
   - Gunakan ③ Backend Export atau ⭐ Smart Export
   - Jangan force ② Web Worker

2. **Untuk data dengan banyak anomali:**
   - Smart Mode: Centang "Skip raw data"
   - Result: File lebih kecil, export lebih cepat

3. **Untuk troubleshoot:**
   - Browser DevTools (F12)
   - Check Console tab untuk error messages
   - Run diagnostic script

---

## File Locations

- `diagnostic.js` — Diagnostic tool untuk debug
- `export.js` — Fixed export logic (main fix di sini)
- `evkin-db.js` — Database layer (unchanged)
- `export-backend.js` — Backend integration (unchanged)

---

## Next Steps

1. **Test sekarang** dengan diagnostic script
2. **Try export** dengan ⭐ Smart Export
3. **Open Excel** dan verify data
4. **Report hasil** (berhasil atau masih error?)

---

**Status:** ✅ Fixes Applied & Ready to Test
**Last Updated:** 2026-08-18

---

**Copyright © Dio Fajrul Iman**
