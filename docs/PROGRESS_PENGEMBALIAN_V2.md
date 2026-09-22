# Progress Pengembalian v2

Progress memakai kewajiban unik `Periode Master + NIP + Tahun SP2D + Komponen`. Nilai kewajiban berasal dari
Data Final Master Pengembalian dan tidak berubah ketika transaksi debit diimpor.

## Penyimpanan

- `pengembalian_obligation`: snapshot kewajiban Tukin, Uang Makan, dan total.
- `pengembalian_progress_import_batch`: audit setiap file import.
- `pengembalian_progress_transaction`: ledger transaksi immutable dengan `tahap INTEGER`, NTPN, bank, rekening, nominal diajukan/berhasil, lineage sumber, dan fingerprint unik.
- `pengembalian_obligation_component`: view kewajiban normalized per komponen.
- `pengembalian_transaction_ledger`: view ledger dengan nama field kontrak bisnis.
- `pengembalian_sp2d_lineage`: lineage perubahan Tahun SP2D.

Hanya transaksi `BERHASIL` mengurangi piutang. `GAGAL` disimpan dan direkap,
tetapi tidak mengurangi sisa. Nilai kosong tetap dibedakan dari nol saat validasi.

## Import

Unduh `GET /pengembalian/archive/progress/template`. Template hanya berisi `IMPORT_PROGRESS`
dan `PETUNJUK`. Lakukan preview progress melalui
`POST /pengembalian/archive/progress/preview`, lalu simpan baris valid melalui
`POST /pengembalian/archive/progress/import`. Fingerprint mencegah file/transaksi
yang sama dihitung dua kali.

Workbook baseline lama dipreview server-side melalui
`POST /pengembalian/archive/progress/baseline/preview`. Parser hanya menghitung
kolom `Pengembalian ... Tahap` pada sheet Mandiri, BRI, dan BSI. Sheet ALL SDM,
REKAPITULASI, hasil blokir, sisa, tagging, dummy, dan formula kontrol tidak dihitung.

Pembatalan batch memakai transaksi `REVERSAL`; transaksi asli tidak dihapus atau
dinonaktifkan. Semua perubahan tetap dapat ditelusuri dari batch asal dan batch revert.

## Query dan export

`GET /pengembalian/archive/progress` memakai pagination server-side serta menerima
filter tahap, Tahun SP2D, bank, provinsi, batch, komponen, status transaksi, dan status progress.
Ringkasan selalu dihitung dari seluruh scope filter, bukan hanya halaman aktif.

`GET /pengembalian/archive/progress/wide` membentuk tampilan dinamis per NIP.
Daftar tahap dan tahun berasal dari ledger, termasuk jumlah NTPN per sel tahap/tahun.
`GET /pengembalian/archive/progress/recaps` menyediakan matriks Tahap × Tahun SP2D.

Export `GET /pengembalian/archive/progress/download` menghasilkan SUMMARY,
PROGRESS_SDM, HISTORY_DEBIT, rekap Provinsi/Bank/SP2D/Periode, Debit Gagal,
Sisa Piutang, Data Lunas, Needs Review, dan Multi SP2D.
