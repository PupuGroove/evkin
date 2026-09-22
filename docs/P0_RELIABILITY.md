# P0 — keandalan Final dan backend

Implementasi 8 September 2026 melengkapi aturan sumber kanonis dalam DATA_OWNERSHIP.md:

- Empat tabel Final dikirim dalam satu permintaan/transaksi. Kegagalan tidak meninggalkan sebagian snapshot Final yang baru.
- Ekspor job Final Absensi membandingkan jumlah baris, NIP (termasuk duplikat), total bruto/potongan/dibayar, dan SHA-256 antara snapshot browser, database, dan isi XLSX sebelum publikasi. Nilai kosong dan ketidaksesuaian menggagalkan ekspor. CSV job juga memeriksa serialisasi ulang.
- Tombol ekspor dikunci selama proses; kegagalan backend ditampilkan, bukan dialihkan diam-diam ke ekspor lokal.
- Job perhitungan/ekspor workflow memakai satu worker thread dalam proses server. Gate bersama mengantrekan permintaan database dan job SKP agar snapshot tidak berubah saat ekspor.
- Berkas `.server.lock` memakai penguncian OS: server kedua ditolak dan pengunci dilepas saat proses berakhir. Berkas pengunci boleh tetap ada; keberadaan berkas saja bukan tanda terkunci.
- Launcher memakai server aktif pada port yang sama; tidak mematikan proses lain, menghapus lock/WAL, atau otomatis memilih port lain. Job workflow yang terputus oleh restart ditandai gagal dengan instruksi menjalankan ulang.

Pengujian regresi: test_final_export_complete.py, test_final_integrity.py, test_export_integrity.cjs, test_workflow_ownership.py, dan pengujian pairing/harian.

Batas: transaksi seluruh impor bertahap (bukan hanya Final), pemisahan beberapa batch workflow aktif, dan validasi tiga-arah pada endpoint unduhan lama/offline belum dicakup. Validasi tiga-arah berlaku pada tombol ekspor job Final Absensi yang mengirim expected_final. Pengujian otomatis tidak menggantikan uji klik di browser pengguna.
