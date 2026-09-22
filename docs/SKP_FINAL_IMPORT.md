# Impor hasil final SKP

Pada Impor Nilai SKP Bulanan, pilih jalur Hasil Final SKP untuk file NIP, Nama, Predikat. Pilih periode dan sheet, preview, lalu konfirmasi nama petugas. Baris valid langsung APPROVED dan dihitung oleh mesin SKP yang sama dengan persetujuan manual. Baris invalid tidak diproses; sumber seluruh baris tetap diarsipkan. Audit IMPORT_FINAL mencatat petugas dan konfirmasi final. Impor ulang mengganti penilaian NIP/periode yang sama.

Jalur REVIEW tetap menjadi default. Jalur FINAL tidak membaca konfigurasi indikator. Master kosong, NIP tidak dikenal, duplikasi, predikat kosong/tidak dikenal tidak boleh masuk jalur final. Periode terkunci atau dibayar tetap dilindungi.

Tanda `-`, tidak bisa dinilai, tidak dapat dinilai, dan tidak membuat SKP dipetakan ke NOT_SUBMITTED_VERIFIED. Sel kosong tetap DATA_MISSING dan ditolak. Mesin yang sudah ada menghitung urutan bulan; bulan terputus memulai urutan baru. Bobot tetap 70% SKP dan 30% absensi, bukan potongan tetap 70% untuk semua predikat.

Setelah impor final berhasil, aplikasi membuka Kelola Tukin pada periode tersebut. Klik Hitung Gabungan untuk memuat data gabungan terbaru sebelum ekspor. Final SKP tidak otomatis berarti pembayaran sudah disahkan: kelengkapan absensi, identitas, dan kontrol pembayaran tetap berlaku.

Sinkronisasi hasil hitung dilakukan setelah transaksi penilaian, mengikuti alur persetujuan manual. Jika sinkronisasi gagal, penilaian dapat sudah tersimpan; periksa audit dan ulangi review/penghitungan sebelum pembayaran. Tidak ada migrasi otomatis atas histori impor lama.
