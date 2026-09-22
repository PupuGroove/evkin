# Master Pengembalian — Database Arsip

## Sumber resmi bulanan

Sejak migration `042_create_pengembalian_monthly_master.py`, workbook
`MASTER SEND BPK DAN PENYESUAIAN.xlsx` adalah sumber resmi awal Master
Pengembalian. Grain data adalah `NIP + Tahun + Bulan`; kolom
`FINAL PENGEMBALIAN` menjadi kewajiban Tukin resmi yang disinkronkan ke
`pengembalian_master_obligation` untuk Progres Pengembalian.

Penyimpanan baru terdiri dari:

- `pengembalian_monthly_import`: versi import aktif/superseded dan statistik validasi.
- `pengembalian_monthly_source_row`: salinan lossless seluruh kolom sumber.
- `pengembalian_monthly_master`: proyeksi bulanan terstruktur dan terindeks.
- `vw_pengembalian_monthly_current`: hanya versi aktif per periode.

Import bersifat append-only. Import baru menonaktifkan versi sebelumnya tanpa
menghapusnya; versi lama dapat diaktifkan kembali dari History / Archive.
Baris dengan error referensi pada kolom perhitungan tendik disimpan sebagai
warning dan raw source, tetapi kewajiban tetap memakai `FINAL PENGEMBALIAN`.

API utama sumber bulanan:

- `/pengembalian/monthly/preview`, `/pengembalian/monthly/import`
- `/pengembalian/monthly/dashboard`, `/pengembalian/monthly/list`
- `/pengembalian/monthly/detail/{row_id}`, `/pengembalian/monthly/imports`
- `/pengembalian/monthly/reconciliation`, `/pengembalian/monthly/download`

Master Pengembalian menyimpan kewajiban Tukin/Uang Makan, hasil final,
dataset pendukung, dan realisasi debit secara multi-periode di DuckDB.

## Alur utama

```text
IMPORT MASTER
    ↓
DATABASE MASTER (DATA_AWAL + snapshot final immutable)
    ↓
FINAL ENGINE
    ↓
FLAG PERUBAHAN
    ↓
FINAL KEWAJIBAN
    ↓
HISTORI DEBIT
    ↓
SISA PIUTANG / STATUS LUNAS

IMPORT DATA DASAR
    ↓
ARCHIVE DATASET JSON
    ↓
NORMALISASI REKAP OKT/NOV/DES PER NIP
    ↓
DASAR ABSENSI = TOTAL TUKIN × 30% × % POTONGAN REKAP
    ↓
DETAIL SDM / LINEAGE (tanpa menimpa nilai Final resmi)
```

Satu workbook BNBA memuat kolom awal dan final. Backend menyimpan kedua
snapshot secara append-only dan membentuk Final dari data database, bukan dari
object browser. `periode_id` memisahkan arsip antartahun/periode.

## Tabel utama

- `pengembalian_period`: metadata periode lintas tahun.
- `pengembalian_archive_import`: history batch import Master.
- `pengembalian_archive_data_awal`: snapshot nilai awal.
- `pengembalian_archive_data_penyesuaian`: snapshot kolom final.
- `pengembalian_archive_dataset`: metadata Data Dasar bebas schema.
- `pengembalian_archive_dataset_row`: row Data Dasar dalam JSON lossless.
- `pengembalian_dasar_rekap_absensi`: NIP, bulan, persentase, nilai asli,
  status validasi, dan referensi baris sumber.
- `pengembalian_dasar_kalkulasi_absensi`: hasil formula per SDM/bulan,
  pembulatan Rupiah, nilai Final saat ini, serta selisih untuk audit.
- `pengembalian_payment_transaction`: histori debit berhasil/gagal.

Final adalah calculated/query layer dari dua snapshot immutable. Kunci bisnis
memuat NIP, periode ID/tahun SP2D, periode/bulan, batch, dan komponen yang
tersedia sehingga periode lama tidak tertimpa.

## Aturan nilai dan perubahan

Nilai kosong disimpan sebagai `NULL`; nol eksplisit tetap nol. Untuk UI dan
perbandingan, selisih adalah `final - awal`, sedangkan pengurangan adalah
`awal - final`. Klasifikasi bulanan: `TIDAK BERUBAH`, `NAIK`, `TURUN`,
`MENJADI 0`, atau `DARI 0 MENJADI ADA`.

## Progres

Hanya transaksi berstatus `BERHASIL` mengurangi kewajiban. Transaksi `GAGAL`
tetap menjadi histori. `sisa_piutang = max(kewajiban_final - debit_berhasil, 0)`.
Status: `BELUM ADA PENGEMBALIAN`, `SEBAGIAN`, `LUNAS`,
`TIDAK ADA KEWAJIBAN`, atau `LEBIH BAYAR / PERLU REVIEW`.

## Migration dan keselamatan data

Migration `029_create_pengembalian_archive_v2.py` hanya membuat tabel/index
baru. Migration 026 mendeteksi kolom yang benar-benar belum ada, melepas empat
alias view read-only sementara, menambah kolom secara idempotent, lalu membuat
ulang view. Tabel sumber dan row lama tidak dihapus.

Data Dasar tidak pernah menambah kolom ke tabel Master. Setiap bentuk Excel
disimpan sebagai dataset terpisah sehingga perubahan header tidak memicu
`ALTER pengembalian_archive_data_awal`.

Migration `040_create_pengembalian_dasar_rekap.py` bersifat aditif. Workbook
besar dibaca secara streaming dan hanya sheet `REKAP OKT`, `REKAP NOV`, serta
`REKAP DES` kolom A:B yang diimpor. Nilai error Excel seperti `#VALUE!`
dipertahankan sebagai error validasi dan tidak diperlakukan sebagai nol.

Pembulatan nominal dilakukan ke Rupiah dengan rekonsiliasi total per bulan.
Dasar hasil hitung disajikan pada DATA FINAL dan Detail SDM sebagai informasi
audit. Perubahan kewajiban resmi tetap melalui alur Master/penyesuaian yang
terkontrol.

## API utama

- `/pengembalian/archive/preview`, `/pengembalian/archive/import`
- `/pengembalian/archive/final`, `/pengembalian/archive/dashboard`
- `/pengembalian/archive/download`
- `/pengembalian/periods`
- `/pengembalian/datasets`, `/pengembalian/datasets/import`
- `/pengembalian/datasets/import-workbook`, `/pengembalian/datasets/materialize-rekap`
- `/pengembalian/archive/dasar-absensi/{nip}`
- `/pengembalian/payments/import`, `/pengembalian/archive/progress`

Export Final dan Data Dasar menggunakan XLSX. Nominal ditulis sebagai numeric
Excel dan filter export menggunakan filter database yang sama dengan Final.
