# Pemeriksaan workflow absensi — 9 September 2026

## Pembaruan kelengkapan record

Snapshot aktif berikutnya memperlihatkan 36.965 record impor/normalisasi, tetapi hanya 4.000 hasil Harian dan masih ada Final lama. Uji ulang tanpa menulis database menghasilkan 36.965 Harian dan 1.563 baris Rekap, dengan jumlah record sumber Rekap tepat 36.965.

- Penyimpanan workflow kini memakai satu snapshot JSON yang tidak berubah setelah masuk antrean, dan satu transaksi backend untuk seluruh tabel. Tidak lagi mengganti isi tabel per potongan 2.000 baris.
- Impor menunggu penyimpanan selesai; kesalahan penyimpanan ditampilkan dan menghalangi perhitungan lanjutan.
- Impor CSV menyimpan semua baris sumber di memori, bukan hanya 1.000 baris. Record Wali dengan NIP/tanggal valid tetapi kedua jam kosong tetap masuk sebagai record tidak lengkap. Baris identik tetap dicatat pada statistik sumber, sedangkan pasangan event shift dapat menjadi satu record kerja. Karena itu jumlah baris mentah dan record kerja Wali tidak selalu sama.
- Harian menghitung semua bulan impor. Filter bulan hanya mengubah tampilan. Data yang sengaja dihapus atau tidak mempunyai identitas/tanggal valid tidak dipaksakan menjadi hitungan.
- Verifikasi membandingkan identitas dan jumlah setiap record impor aktif dengan hasil Harian. Hasil parsial tidak dapat membuka Rekap/Final. Snapshot Semi Final berisi seluruh hasil terverifikasi.
- Rekap mengelompokkan seluruh data dengan kunci NIP dan bulan, menghitung kalender tiap bulan sekali, dan menyimpan jumlahRecord untuk memastikan tidak ada record yang tertinggal.
- Menu Rekap menampilkan rekonsiliasi jumlah record, filter seluruh/bulan tertentu, pencarian NIP/nama/jabatan, serta 25/50/100/250 baris per halaman. Pindah halaman tidak lagi menyimpan ulang seluruh workflow.
- Final dan ekspor tetap per periode; pemilih periode Final tersedia agar NIP pada dua bulan tidak dicampur. Seluruh periode tetap tersedia di Rekap.
- Pengujian mencakup 35.001 record lintas dua bulan → 35.001 Harian → 3.334 baris NIP/bulan, CSV 1.205 baris, snapshot antrean yang tidak berubah, kegagalan simpan, dan pemulihan penyimpanan lama yang terputus.

Alur: Import → Konfigurasi → Hitung Harian → Semi Final → Rekap SDM → Final → Ekspor.

## Temuan dan perbaikan

- Hari berstatus OFF/libur dengan jam kosong sebelumnya dikenai potongan tidak lengkap 3%. Pemeriksaan OFF kini dilakukan sebelum penalti tidak lengkap, konsisten dengan aturan kalender yang sudah digunakan mesin harian.
- Cuti/jenis bebas potongan tanpa jam sebelumnya tidak menambah hari yang dikecualikan pada Rekap, sehingga metode durasi dapat mengenakan Hari Kurang. Tanggal tersebut kini diperhitungkan sebagai hari yang dikecualikan.
- Baris dengan NIP/tanggal sama sebelumnya seluruhnya dijumlahkan walau jumlah hari dihitung unik. Verifikasi dan Rekap kini menolak duplikat untuk dikoreksi di Semi Final; aplikasi tidak memilih salah satu baris secara diam-diam.
- Nilai string numerik pada potongan pulang cepat/tidak lengkap kini dikonversi sebelum penjumlahan.
- Tarif konfigurasi 0% tidak lagi diganti otomatis menjadi default 3% saat normalisasi.
- Hitung ulang Semi Final kini menghapus hasil hilir dan menunggu verifikasi sebelum Rekap. Tombol hitung ulang Rekap menunggu hasil penyimpanan dan menampilkan kegagalan.
- Edit jam di Semi Final kini memperbarui kedua mode normalisasi waktu.
- Persentase total Final + SKP Kombinasi kini memakai bobot 30% absensi dan 70% SKP pada layar, snapshot backend, serta ekspor.

## Rumus yang diperiksa

Final Absensi: potongan rupiah = bruto × 30% × persentase Rekap / 100. Dengan bruto Rp2.000.000 dan potongan kehadiran 10%, nominal potongan Rp60.000 dan dibayar Rp1.940.000.

Final + SKP Kombinasi: potongan rupiah = bruto × (30% × persentase absensi + 70% × persentase SKP) / 100. Untuk absensi 10% dan SKP 20%, total setara 17% bruto: Rp340.000 dari bruto Rp2.000.000. Penjumlahan langsung menjadi 30% sebelumnya salah pada kolom persentase total; nominal memakai bobot komponen.

Aturan metode Rekap yang sudah ada tetap dipakai: Reguler menjumlah keterlambatan, pulang cepat, dan tidak lengkap; Durasi menjumlah keterlambatan, pulang cepat, durasi, dan Hari Kurang. README lama tidak menjelaskan pengecualian ini secara konsisten. Pengesahan aturan institusi/jadwal shift memerlukan dasar aturan pengguna; pemeriksaan ini memvalidasi implementasi aplikasi, bukan menetapkan peraturan baru. Kalender tetap mengikuti konfigurasi pengguna.

## Tombol hapus backend

Dashboard menyediakan **Hapus Data Backend Workflow Absensi**, dengan konfirmasi teks **HAPUS ABSENSI**. Berlaku untuk seluruh periode workflow aktif: raw_import, workflow_records, workflow_config, hitung_harian, rekap_sdm, anomali, dan empat tabel Final. Skema tabel dipertahankan. Master SDM, Penilaian SKP, arsip pengelolaan Tukin, dan Master Pengembalian tidak masuk daftar penghapusan.

Endpoint `POST /api/workflow/delete-absensi` menjalankan penghapusan dalam satu transaksi. Browser menunggu antrean penyimpanan sebelumnya, memuat state kosong dari backend, lalu membersihkan cache workflow IndexedDB. Tombol ini berbeda dari reset hasil turunan yang mempertahankan data impor dan konfigurasi.

Penghapusan hanya diuji pada database sementara. Data pengguna tidak dihapus dalam pengerjaan ini.

## Validasi dan batas

- Pengujian aturan harian/rekap, duplikat, normalisasi tarif nol, urutan verifikasi, Final pairing, persentase kombinasi, ekspor, dan pemulihan state.
- Pengujian hapus backend: konfirmasi wajib, hanya tabel milik workflow, aman dipanggil ulang, dan rollback seluruh transaksi jika ada kegagalan.
- Pengujian browser terhenti karena Computer Use tidak dapat memastikan URL halaman aktif; uji klik visual belum selesai.
- Snapshot backend yang diperiksa tidak berisi hasil Harian/Rekap/Final. Angka kasus pengguna belum dapat dicocokkan tanpa contoh NIP/periode/hasil.
- Perubahan rumus tidak menghitung ulang data pengguna otomatis. Muat ulang halaman dan jalankan Harian → verifikasi Semi Final → Rekap → Final untuk memperbarui hasil.
