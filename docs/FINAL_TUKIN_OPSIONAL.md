# EVKIN — Final Tukin dengan SKP opsional

Implementasi 10–11 September 2026. Mesin absensi lama dipertahankan; Final Tukin baru memakai Rekap SDM terverifikasi, Master SDM sesuai periode, dan SKP opsional.

## FILES CHANGED

| File | Perubahan |
|---|---|
| `backend/final_tukin.py` | Normalisasi/import, engine Decimal, rekonsiliasi, versi snapshot, persistensi, deteksi perubahan, export, API |
| `backend/migrations/045_create_optional_final_tukin.py` | Migrasi additive dan idempotent |
| `backend/evkin_export_api.py` | Registrasi router dan migrasi startup |
| `backend/requirements.txt` | Menambahkan openpyxl untuk import/export .xlsx |
| `backend/application_reset.py` | Melindungi master aturan dan versi schema saat reset operasional |
| `assets/js/final-tukin.js` | Halaman Final, import mapping, preview, BNBA, detail, filter, riwayat, arsip |
| `assets/js/state.js` | Menu dan gating akses hasil tersimpan; SKP diberi label opsional |
| `assets/js/app.js` | Router dan daftar sidebar |
| `assets/css/style.css` | Style terisolasi untuk halaman baru |
| `index.html` | Memuat modul UI baru |
| `backend/tests/test_optional_final_tukin.py` | Test perhitungan, import, database, approval, versi, API, export |

Perubahan lokal yang sudah ada sebelum pekerjaan ini tidak dihapus atau di-reset.

## AUDIT

- Aplikasi utama: FastAPI `backend.evkin_export_api:app`; frontend JavaScript tanpa framework, router pada `assets/js/app.js`.
- Database utama: `backend/data/EVKIN_MASTER.duckdb`, atau `EVKIN_DUCKDB_PATH`.
- Workflow lama: `raw_import` → `hitung_harian` → verifikasi Semi Final → `rekap_sdm` → `final_absensi`.
- Potongan absensi bulanan: `rekap_sdm.total`; periode: `bulan`; verifikasi: `workflow_flags` dan state konfigurasi yang tersedia.
- Master SDM memakai `sdm_master`, histori assignment, histori profil Tukin dan status aktif. `SharedMasterService.snapshot_map()` mengutamakan profil sesuai periode. Bila bruto periode belum tersedia, gunakan profil Master SDM terkini sesuai workflow Final lama, dengan peringatan per SDM dan sumber bruto dalam snapshot/export. Tidak pernah fallback ke Excel SKP. Pada database asli, profil awal seluruh SDM berlaku 1 September 2026; fallback kompatibilitas ini diperlukan untuk Rekap Agustus.
- Assessment memakai `skp_assessment_monthly`; status PENDING_REVIEW, RECOMMENDED, RETURNED, APPROVED tetap dipertahankan.
- `tukin_combined.py` merupakan proyeksi gabungan lama. Tidak dijadikan dependency untuk mode Absensi Saja. Mesin baru tidak mengambil bruto dari Excel SKP maupun hasil historis.
- `state.js` sebelumnya sudah tidak mewajibkan SKP global. Sidebar juga memiliki daftar menu sendiri pada `app.js`, yang harus diperbarui bersama router.

## DATABASE CHANGES

Tabel baru: `skp_results`, `skp_import_batches`, `final_tukin_results`, `final_tukin_batches`, `master_skp_rules`, `final_tukin_schema`.

- SKP: unique `(nip, periode, source_type, import_batch_id)`; batch dipilih eksplisit saat Final.
- Final: unique `(nip, periode, mode, version)`; mode/version lain tidak dihapus.
- Angka Rupiah BIGINT; persentase DECIMAL; identitas dan hasil juga disimpan dalam JSON snapshot.
- Snapshot memiliki hash sumber; angka tersimpan tidak diperbarui saat source berubah.
- Import mencatat file, sheet, SHA-256, waktu, operator, baris asli, metadata indikator, dan daftar baris yang dikecualikan.
- Hapus Final memakai `archived_at` pada batch, setelah dialog konfirmasi. Tidak menghapus Master, absensi atau SKP.
- Migrasi tidak DROP/recreate tabel existing. Startup menjalankannya otomatis; entry point migrasi juga dapat dijalankan langsung.

Pemeriksaan migrasi pada database asli menunjukkan jumlah tabel sumber tidak berubah: 32.626 SDM, 32.626 histori profil Tukin, 1.563 Rekap SDM, 32.483 Assessment, 0 `final_absensi`, dan 0 `tukin_final_monthly` pada saat audit.

## NEW FEATURES / UI CHANGES

Menu **Final Tukin** dan **Hasil Perhitungan** ditambahkan. Menu Final/export lama tetap tersedia.

1. Selesaikan absensi sampai Rekap SDM dan verifikasi Semi Final.
2. Buka Final Tukin, pilih periode dan mode. Default **ABSENSI SAJA** menyembunyikan seluruh kontrol SKP.
3. Untuk **ABSENSI + SKP**, pilih Assessment APPROVED, import template, atau import eksternal dan batchnya.
4. Preview Matching menampilkan jumlah match, missing, duplicate, READY/HOLD dan alasan.
5. Proses Final menyimpan SDM READY sebagai FINALIZED; SDM HOLD memiliki pembayaran NULL. Seluruh batch tetap dapat diaudit.
6. Hasil Perhitungan menyediakan periode, mode, batch/version, provinsi, kabupaten/kota, jabatan, status, predikat, sumber, summary, pagination, dan detail saat baris diklik.
7. Data berubah ditandai OUTDATED / PERLU FINALISASI ULANG ketika hasil dibaca/di-export. Buat Versi Final Baru mempertahankan periode/mode/sumber batch yang sedang dibuka.

## CALCULATION LOGIC

Satu fungsi: `calculate_final_tukin(nip, periode, mode, attendance_result, employee_master, skp_result=None)`.

Seluruh perkalian finansial memakai Decimal, dengan ROUND_HALF_UP. Bruto dibulatkan ke Rupiah integer. Komponen kehadiran adalah bruto × 30% yang dibulatkan; komponen kinerja adalah bruto dikurangi komponen kehadiran, sehingga keduanya tepat menjumlah ke bruto termasuk untuk nominal kecil.

- Potongan absensi = komponen kehadiran × persentase absensi / 100, dibulatkan.
- Potongan SKP = komponen kinerja × persentase SKP / 100, dibulatkan, hanya pada mode gabungan.
- Dibayar = bruto − potongan absensi − potongan SKP (jika digunakan).
- Invariant: bruto = dibayar + seluruh potongan, tanpa selisih dan tanpa pembayaran negatif.
- Absensi Saja: predikat, komponen kinerja, persen SKP, dan nominal SKP semuanya NULL; sumber/status SKP TIDAK DIGUNAKAN.

Contoh bruto 3.915.950, absensi 1%: komponen 1.174.785, potongan 11.748, dibayar 3.904.202. Jika SKP 5%: potongan SKP 137.058, dibayar 3.767.144.

## IMPORT SKP LOGIC

Upload .xlsx → scoring sheet/header → auto mapping → mapping manual → preview → validasi → import. Kolom persen eksplisit diprioritaskan di atas kolom nominal `Potongan SKP`. Nilai `5,00%`, angka 5, dan Excel percentage 0.05 dengan format persen didukung; angka fraksi tanpa format dapat dipilih manual. Tahun/Bulan, termasuk nama bulan Indonesia, dinormalisasi ke YYYY-MM.

Persentase eksplisit menggunakan `IMPORTED`; tanpa persentase, lookup master aturan efektif pada awal periode memakai `RULE_MAPPING`. Predikat tanpa aturan tidak diubah menjadi nol. Aturan awal: Sangat Baik/Baik 0, Butuh Perbaikan 5, Kurang 10, Sangat Kurang 15. Aturan dengan rentang efektif bertumpang tindih tidak dipilih diam-diam.

Assessment yang belum APPROVED menghasilkan HOLD. Kondisi pembayaran Assessment yang sudah disetujui tetap diperhatikan. File hasil resmi memakai IMPORTED_FINAL, tanpa approval Assessment tambahan. SKP import tidak memperbarui identitas atau bruto Master SDM.

**Hasil pemeriksaan workbook asli di Downloads (database sementara):**

| Sumber | Hasil |
|---|---|
| `08092026_SKP 2026 3.0_ Final Tukin Backup.xlsx`, sheet `BNBA_AGUSTUS 2026 TEMP` | 32.609 baris, semua NIP valid, 0 duplikat, 0 persentase kosong; seluruhnya berhasil diimport. Ada nilai khusus 35%, 70%, 100%, serta predikat dengan pengecualian, yang tetap mengikuti persen eksplisit. |
| `Template_Penilaian_SKP.xlsx`, sheet DATA | 32.641 baris; 118 baris terlibat duplikasi dan 183 predikat `-` tanpa persentase; 293 baris bermasalah setelah memperhitungkan overlap. Import default ditolak sampai konflik diselesaikan. Pilihan eksplisit valid-only berhasil mengimport 32.348 baris dan mengecualikan 293 baris. Semua anggota grup duplikat dikecualikan; tidak dipilih pemenang. |

Daftar konflik menyertakan baris Excel dan NIP. Pilihan valid-only tidak aktif secara default dan jumlah pengecualian tersimpan dalam batch.

## EXPORT

Empat sheet: BNBA FINAL, REKAP, DATA BERMASALAH, METADATA PERHITUNGAN. Rekap mencakup total, provinsi, provinsi/kabupaten, predikat dan mode. Angka memakai snapshot tersimpan; NIP tetap teks. Header, freeze pane, filter, format integer dan perlindungan formula injection disertakan. Hold tidak masuk total pembayaran. Status OUTDATED tetap menampilkan angka historis.

## BACKWARD COMPATIBILITY

Mesin harian, verifikasi, dan Rekap SDM tidak diganti. Final lama tetap dapat dipakai; halaman baru juga dapat mengambil langsung Rekap SDM terverifikasi tanpa pembuatan Final lama dan tanpa SKP. Histori Final baru tidak bergantung pada session browser dan tidak ikut terhapus ketika workflow absensi aktif diganti.

## TESTS RUN / TEST RESULTS

- `python -m pytest backend/tests -q --disable-warnings`: **254 passed** pada pemeriksaan suite lengkap; termasuk 44 test baru saat itu.
- Setelah penambahan uji Assessment, valid-only, kompatibilitas Master terkini dan optimasi: `python -m pytest backend/tests/test_optional_final_tukin.py -q --disable-warnings`: **48 passed**.
- Pemeriksaan perubahan reset/schema bersama test Final: **65 passed** pada tahap pemeriksaan tersebut.
- `node --test backend/tests/*.cjs`: **8 suite passed**, termasuk 35.001 baris import → daily → 3.334 NIP/bulan, restore, verifikasi, final pairing/sync, penghapusan dan integritas export.
- Python compile, JavaScript syntax dan `git diff --check` pada file yang diubah: lulus.
- Test multipart HTTP preview/import, Final/hasil setelah membuka service kembali, dua mode/version berdampingan, stale source, arsip dan export workbook: lulus.
- Workbook asli keduanya diuji secara lokal terhadap DuckDB sementara; tidak diimport ke database produksi.
- UI kedua mode diuji sampai Final tersimpan dan BNBA; dua mode V1 terlihat berdampingan di riwayat. Preview database asli untuk Agustus menghasilkan 1.563 READY, 0 HOLD, tanpa SKP. Tidak ada Final produksi yang dibuat oleh pengujian.

## KNOWN LIMITATIONS

- File .xls lama belum didukung; simpan sebagai .xlsx.
- Preview layar menampilkan 100 baris contoh; daftar konflik lengkap tetap ditampilkan. Final BNBA dipaginasi 100 baris dan export berisi seluruh batch.
- Kecamatan tersedia sebagai kolom hasil, tetapi kosong jika belum disediakan Master SDM existing. File SKP tidak dipakai untuk menimpanya.
- Perubahan sumber dideteksi saat membuka/export hasil, bukan lewat watcher latar belakang.
- Pengaturan master aturan saat ini dilakukan pada tabel DuckDB; belum ada editor aturan khusus di UI baru.
- Pembulatan komponen komplementer adalah kebijakan deterministik untuk menjaga invariant Rp0; perbedaan Rp1 dari workbook yang membulatkan setiap tahap dengan kebijakan berbeda tetap mungkin, namun tidak ada selisih internal bruto/potongan/dibayar.
- Data contoh template yang bermasalah membutuhkan perbaikan atau pemilihan valid-only secara eksplisit; predikat `-` tidak diasumsikan Baik/0%.
