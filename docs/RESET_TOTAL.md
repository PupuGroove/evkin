# Reset total tanpa Master SDM

Menu profil EV kanan atas → **Reset Total (Tanpa Master SDM)**. Tutup tab EVKIN lain dan tunggu proses selesai. Dialog memuat preview jumlah baris per tabel, nama petugas, alasan, dan frasa `RESET TOTAL TANPA MASTER SDM`. Membuka dialog tidak menghapus data.

Reset mengosongkan tabel operasional DuckDB: sumber/hasil absensi, konfigurasi workflow, SKP beserta hasil/rekomendasi/impor, Tukin, pengembalian dan rekonsiliasi. Skema tabel tidak dihapus.

Yang tetap disimpan:

- Seluruh tabel `sdm_*`, Master SDM legacy/proyeksinya, master jabatan/unit dan profil Tukin legacy.
- Aturan potongan `skp_rule_config`, audit sistem umum dan audit reset.
- Riwayat job teknis SQLite, file hasil ekspor, file Excel asli dan backup sebelumnya. Layanan pembulatan terpisah tidak direset oleh fitur ini.

Backend menolak reset jika ada data terkunci/ditutup/diarsipkan/sudah dibayar, job aktif, atau tabel berisi data yang belum dipetakan. Preview diverifikasi ulang berdasarkan isi tabel, bukan hanya jumlah baris. API tidak menerima nama tabel atau lokasi penghapusan dari pengguna.

Backup logis DuckDB dibuat di `backend/data/reset-backups/<id-reset>/` (mengikuti direktori database aktif jika dikustomisasi), dibuka ulang dan dibandingkan seluruh tabelnya sebelum penghapusan pertama. Backup SQLite job ikut dibuat. Kegagalan backup membatalkan reset. Semua penghapusan DuckDB dan audit reset berada dalam satu transaksi; kegagalan penghapusan membatalkan seluruh transaksi. Master dan aturan diperiksa ulang sebelum commit.

Audit reset ada pada tabel `application_reset_audit`, memuat petugas, alasan, waktu, lokasi backup dan manifest. Manifest di folder backup menandai BACKUP_VERIFIED; keberadaan backup saja tidak berarti reset berhasil. Jika koneksi UI terputus saat reset, periksa audit dan data sebelum mencoba lagi.

Sesudah berhasil, klik Muat Ulang Aplikasi. Cache workflow browser dibersihkan tanpa menghapus cache Master SDM. Jangan melanjutkan pekerjaan dari tab lama. Pemulihan backup belum memiliki tombol otomatis: lakukan secara administratif saat backend berhenti dan perhatikan perubahan Master SDM yang mungkin terjadi setelah backup.
