# Sumber data dan kepemilikan penyimpanan

## Master SDM

`sdm_master` dan tabel histori `sdm_*` dimiliki layanan Master SDM Bersama.
Perubahan master hanya melalui endpoint Master SDM. `master_data` adalah
proyeksi kompatibilitas yang dikelola layanan tersebut, bukan daftar peserta
workflow. `config.masterPegawai` di browser hanya cache pembacaan.

## Workflow aktif

`raw_import` berisi sumber yang diproses pengguna. `hitung_harian`, `rekap_sdm`,
`anomali`, serta tabel `final_*` adalah hasil workflow aktif. Jumlah peserta
mengikuti data impor/rekap, bukan seluruh Master SDM. Final mencocokkan NIP
peserta ke endpoint `/api/shared-master/lookup-tukin`.

`/api/workflow/sync` hanya memperbarui field yang dikirim, secara transaksional.
`/api/workflow/sync-table` menerima hanya tabel milik workflow. Kedua endpoint
menolak master dan arsip. Nilai `null`/daftar kosong yang dikirim secara eksplisit
mengosongkan tabel tujuan; field yang tidak dikirim tetap dipertahankan.
Konfigurasi tidak menyimpan `masterPegawai`. Pembacaan state tidak membawa
proyeksi master; frontend membaca master lewat endpoint tersendiri.

## Arsip Final

`tukin_final_monthly` dan histori Tukin dimiliki layanan Tukin Tahunan.
Penyimpanan workflow dan ekspor tidak mengarsipkan atau mengganti tabel ini.
Tindakan `Simpan Hasil Final` memanggil `/api/tukin/periods/capture-live`
secara eksplisit. Reset workflow hanya menghapus hasil turunan workflow.

## Batas tahap ini

Workflow aktif masih satu ruang kerja; isolasi banyak batch, master per periode,
dan penguatan penguncian/revisi arsip merupakan tahap pengembangan berikutnya.
Penulisan bertahap lewat sync-table belum atomik untuk seluruh rangkaian batch.
Klien lama yang masih mengirim master_data lewat workflow harus diperbarui.
