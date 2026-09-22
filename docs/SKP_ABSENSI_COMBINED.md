# Pengelolaan gabungan SKP dan absensi

## Penggunaan

1. Buka Penilaian SKP, pilih periode penilaian, lalu file. Sheet dengan NIP dan predikat dipilih otomatis. Untuk file TN Agustus gunakan `bnba` dan periode `2026-08`, bukan tanggal unduhnya.
2. Preview sebelum konfirmasi. Semua kemunculan NIP duplikat ditolak; tidak ada pemilihan predikat pertama/terakhir secara otomatis. Predikat kosong dan NIP tidak cocok perlu ditindaklanjuti. Impor menyimpan sumber asli termasuk baris yang tidak masuk penilaian, pada batch yang dikonfirmasi.
3. Jalankan review/persetujuan SKP yang sudah ada. Penggabungan tidak menyetujui SKP secara otomatis.
4. Proses workflow absensi untuk peserta yang diperlukan. Data siap hitung disimpan terpisah dari data mentah. Hasil Harian/Rekap/Semi Final menunggu penyimpanan sebelum mengumumkan keberhasilan.
5. Buka Pengelolaan Tukin, bagian teratas **Dasar Tukin — SKP 70% dan Absensi 30%**. Pilih periode lalu **Hitung Gabungan**. Cakupan awal adalah peserta Final Absensi workflow aktif. Pilihan lain: Final termasuk histori bulan itu, atau seluruh Master SDM dan sumber.
6. **Excel Dasar Tukin** mengekspor seluruh peserta pada cakupan terpilih, tidak hanya halaman/pencarian. Jika sumber berubah setelah tabel dimuat, hitung gabungan kembali.

## Perhitungan dan sumber

- Identitas, bruto, dan kelayakan berasal dari snapshot Master SDM pada periode penilaian.
- Potongan SKP = bruto × 70% × persentase potongan SKP disetujui.
- Potongan absensi = bruto × 30% × persentase Final Absensi. Nominal yang sudah berbobot tidak dikalikan lagi.
- Pasangan berdasarkan NIP dan periode. Hasil absensi batch aktif diutamakan; peserta lain memakai hasil bulanan tersimpan bila tersedia. Seluruh Master SDM serta NIP sumber yang tidak cocok tetap terlihat.
- Cakupan workflow hanya berisi NIP Final Absensi aktif periode tersebut, termasuk NIP yang belum cocok. Master tanpa Final terlihat pada cakupan seluruh SDM. Cakupan histori merupakan gabungan Final aktif dan histori absensi bulanan; tidak menambahkan pegawai hanya karena memiliki penilaian SKP.
- Nilai hilang berbeda dari nol. Nominal tidak lengkap tidak dihitung menjadi pembayaran. Keputusan HOLD/UNPAID dan kelayakan Master tetap diperiksa.
- Penggabungan adalah proyeksi review; tidak mengubah arsip pembayaran terkunci atau menyetujui pembayaran. Persetujuan dan kondisi khusus tetap melalui modul yang berwenang.
- Sinkronisasi Final ke histori melakukan penggabungan peserta, bukan menghapus peserta batch sebelumnya. Periode terkunci ditolak.

## Keluaran dasar Tukin dan penyesuaian

Acuan struktur adalah workbook `08092026_SKP 2026 3.0_ Final Tukin Backup.xlsx`, sheet `BNBA_AGUSTUS 2026 TEMP`. File sumber tidak diimpor otomatis. Aturan `MAX` antarsumber absensi dan koreksi final tanpa alasan dari Excel tidak diterapkan otomatis. Sumber kehadiran adalah hasil Final Absensi yang dipilih melalui workflow, dengan bruto dari Master SDM pada periode yang sama.

Tabel dan Excel memperlihatkan bruto, komponen 70/30, predikat dan persentase potongan, nominal potongan, hasil perhitungan, penyesuaian, alasan, petugas, Final Dasar Tukin, status, sumber absensi, wilayah 3T, status Tendik, dan status periode. Nominal Excel berupa angka rupiah bulat, bukan teks `Rp`. NIP tetap teks. Nilai tidak tersedia tetap kosong.

1. Klik **Penyesuaian** pada peserta lengkap dan layak dibayar. Isi nominal bertanda (positif menambah, negatif mengurangi), nama petugas, serta alasan/rujukan.
2. Final = hasil hitungan + penyesuaian. Backend menolak nilai negatif, melebihi bruto, pecahan rupiah, dan nilai nonangka. Pembetulan bruto dilakukan melalui Master SDM, bukan penyesuaian.
3. Setiap simpan mencatat nilai sebelum/sesudah, alasan, petugas, waktu, dan sidik sumber dalam `tukin_combined_adjustment_audit`; nilai aktif berada pada `tukin_combined_adjustment`. Tabel dibuat otomatis saat penyimpanan pertama.
4. Klik **Audit** untuk melihat riwayat. Isi penyesuaian 0 disertai alasan untuk membatalkan koreksi lama. Pembatalan tetap boleh dilakukan ketika SKP belum lengkap/ditahan, selama periode terbuka dan peserta masih tersedia.
5. Perubahan sumber memblokir penggunaan penyesuaian nonnol sampai diperiksa ulang. Formulir lama ditolak bila data atau penyesuaian berubah setelah dimuat. Periode LOCKED/HISTORICAL_LOCKED/PAID dan hasil bulanan PAID tidak bisa diedit.
6. Keputusan UNPAID eksplisit pada data lengkap menghasilkan final 0; HOLD atau kelengkapan yang belum terpenuhi menghasilkan final kosong. Penyesuaian tidak dapat melewati penahanan atau ketidaklayakan.

**Batas keluaran:** Final Dasar Tukin adalah hasil untuk review dan ekspor, bukan bukti pembayaran. Penyesuaian ini tidak mengubah penilaian SKP, Final Absensi, arsip `tukin_final_monthly`, matriks pembayaran tahunan, atau mengesahkan pembayaran. Gunakan **Excel Dasar Tukin** untuk hasil gabungan yang telah disesuaikan; **Download Final Bulan** tetap mengekspor arsip bulanan yang dikelola terpisah.

API: `GET /api/tukin/combined` dan `/export` menerima `scope=workflow|attendance|all` (default API `all` untuk kompatibilitas). `POST /api/tukin/combined/adjustment` memerlukan periode, NIP, amount, actor, reason, dan token `expected` dari `edit_token` baris preview. Audit tersedia di `GET /api/tukin/combined/adjustment/audit` dengan periode dan NIP.

## Verifikasi

Tes mencakup bobot 70/30, potongan penuh, nol, duplikasi, pasangan hilang, periode berbeda, HOLD, pemulihan data impor, perubahan snapshot, dan kelengkapan ekspor 2.005 baris.

File TN sumber tidak diimpor atau disetujui otomatis oleh pengembangan ini. Duplikat dan predikat `-` tetap memerlukan keputusan pengguna.

## Penghapusan penilaian SKP

### Hapus versi konfigurasi indikator

Di **Penilaian SKP → Konfigurasi Indikator → Versi Konfigurasi**, isi petugas dan alasan penghapusan, kemudian klik **Hapus** pada versi yang dimaksud dan konfirmasi. Draft maupun versi aktif dapat dihapus dari daftar penggunaan. Backend menandai versi sebagai `DELETED` dan mencatat nilai lama, alasan, petugas, serta waktu di audit dalam satu transaksi.

Versi yang dihapus tidak dipilih untuk impor berikutnya. Versi lain yang masih APPROVED dan sesuai lingkup/periode dapat menjadi pengganti. Snapshot penilaian yang telah diimpor tidak dihitung ulang atau dihapus; nomor versi juga tidak digunakan ulang. Ekspor histori konfigurasi tetap menyertakan versi berstatus DELETED untuk penelusuran.

Di tab Klasifikasi/Rekomendasi atau Review/Persetujuan, buka **Kelola / hapus data SKP**.
Isi nama petugas dan alasan. Pilih salah satu tindakan:

- **Hapus SKP Terpilih**: hanya NIP yang dicentang pada periode aktif.
- **Reset SKP Per Periode**: seluruh penilaian pada periode aktif, bukan hanya hasil filter.
- **Batalkan Batch Impor**: muat daftar batch, pilih batch, lalu konfirmasi. Hanya penilaian yang masih dimiliki batch itu dihapus. Penilaian dari impor lebih baru tidak disentuh. Ini bukan pemulihan versi sebelum impor.

Preview menunjukkan jumlah penilaian dan jumlah yang sudah disetujui. Backend memeriksa ulang cakupan dan kunci periode dalam transaksi; perubahan setelah preview mengharuskan konfirmasi ulang. LOCKED, HISTORICAL_LOCKED, PAID dan penilaian terkait pembayaran PAID ditolak.

Data sumber impor, Master SDM, absensi, pengecualian, dan audit tetap disimpan. Nilai lama penilaian disalin ke audit sebelum dihapus. Gunakan **Lihat Audit NIP** untuk menelusuri penilaian yang sudah dihapus. Belum ada tombol pemulihan otomatis.

Hasil Tukin terkait pada periode terbuka, termasuk periode berikutnya yang mungkin bergantung pada urutan tidak membuat SKP, ditahan untuk review/hitung ulang. Arsip terkunci/sudah dibayar tidak diubah. Seluruh perubahan dan audit dilakukan dalam satu transaksi.
