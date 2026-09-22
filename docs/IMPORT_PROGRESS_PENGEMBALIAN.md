# Import Progress Pengembalian

## Alur aman

`Excel → Import Batch → Staging → Normalisasi → Validasi → Matching → Preview → Commit → Rekonsiliasi`

Preview menyimpan data hanya di `pengembalian_progress_staging`; kewajiban dan
history transaksi final belum berubah. Commit menggunakan `import_batch_id` dan
berjalan dalam satu transaksi database. Baris `INVALID`, `DUPLICATE`, dan
`NEEDS_REVIEW` tidak masuk history final.

Baris `VALID` dan `WARNING` yang tetap memiliki matching obligation valid dapat
dikomit. Setelah commit, Progress SDM dibaca langsung dari transaksi aktif sehingga
realisasi dan sisa piutang berubah tanpa proses refresh/backfill manual. Batch
`READY` yang belum dikomit ditampilkan kembali di UI dengan tombol
`Commit ke Progress SDM`.

## Idempotency dan koreksi

- SHA-256 file mendeteksi `FILE_ALREADY_IMPORTED`.
- Fingerprint baris mendeteksi transaksi yang sama meskipun berasal dari file lain.
- `REVERSAL` mengurangi realisasi netto tanpa menghapus transaksi berhasil asal.
- Correction dapat menyimpan `original_transaction_id` dan `correction_type`.
- Rollback batch mengubah transaksi menjadi nonaktif dan status batch menjadi
  `ROLLED_BACK`; seluruh history tetap tersedia untuk audit.

## Nilai kosong dan nol

Kolom Debit Tukin/UM yang kosong berarti komponen tidak diberikan. Nol berarti
komponen diberikan dengan nilai nol. Jika hanya `Nominal Debit Total` tersedia,
baris diberi `COMPONENT_ALLOCATION_REQUIRED` dan `NEEDS_REVIEW`; sistem tidak
membagi nominal secara otomatis.

## Template

Template memiliki sheet `IMPORT_PROGRESS`, `PETUNJUK`, `REFERENSI_STATUS`, dan
`CONTOH_DATA`. Status yang didukung: `BERHASIL`, `GAGAL`, `PENDING`,
`DIBATALKAN`, `REVERSAL`, dan `NEEDS_REVIEW`.

## Column mapping dan file besar

Header umum dipetakan otomatis. Jika field wajib atau kolom nominal tidak dikenali,
UI menampilkan pemetaan kolom sumber untuk NIP, SP2D, bank, periode, status,
komponen, tanggal, surat, dan keterangan. Mapping yang dipilih ikut disimpan dalam
metadata batch. Parsing workbook dijalankan melalui Web Worker agar halaman tetap
responsif, dengan fallback kompatibel untuk browser yang tidak mendukung worker.
