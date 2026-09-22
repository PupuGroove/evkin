"""
Migration 001: create EVKIN_MASTER.duckdb schema
This script is safe: it will backup an existing EVKIN_MASTER.duckdb to data/backup with a timestamp
and then create missing tables (IF NOT EXISTS).
"""
from pathlib import Path
import duckdb
import shutil
import datetime
import sys

def main():
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = repo_root / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / 'EVKIN_MASTER.duckdb'
    backup_dir = data_dir / 'backup'
    backup_dir.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        ts = datetime.datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
        backup_path = backup_dir / f'EVKIN_MASTER_{ts}.duckdb'
        print(f"Existing EVKIN_MASTER.duckdb found, attempting backup: {backup_path}")
        try:
            shutil.copy2(db_path, backup_path)
            print(f"Backup created successfully: {backup_path}")
        except PermissionError as exc:
            print(
                f"Warning: could not create backup because the database is in use by another process: {exc}\n"
                "The file will be kept as-is and the schema check will continue. Close the lock holder before a full backup.",
                file=sys.stderr,
            )

    print(f"Connecting to DuckDB at: {db_path}")
    try:
        con = duckdb.connect(database=str(db_path), read_only=False)
    except Exception as exc:
        print(f"Failed to open DuckDB at {db_path}: {exc}", file=sys.stderr)
        raise

    # Create tables
    statements = [
        # master SDM (pegawai)
        """
        CREATE TABLE IF NOT EXISTS master_sdm (
            id TEXT PRIMARY KEY,
            nip TEXT UNIQUE,
            nama TEXT,
            gelar TEXT,
            jabatan TEXT,
            unit_kerja TEXT,
            satker TEXT,
            golongan TEXT,
            status_pegawai TEXT,
            jenis_pegawai TEXT,
            nomor_sk TEXT,
            tanggal_mulai DATE,
            tanggal_berakhir DATE,
            zona_waktu TEXT,
            tahun INTEGER,
            aktif BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # master unit kerja
        """
        CREATE TABLE IF NOT EXISTS master_unit_kerja (
            id TEXT PRIMARY KEY,
            kode TEXT UNIQUE,
            nama TEXT,
            parent_id TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # master jabatan
        """
        CREATE TABLE IF NOT EXISTS master_jabatan (
            id TEXT PRIMARY KEY,
            nama TEXT UNIQUE,
            metode TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # tukin master
        """
        CREATE TABLE IF NOT EXISTS master_tukin (
            id TEXT PRIMARY KEY,
            nip TEXT,
            tahun INTEGER,
            bulan INTEGER,
            nominal_tukin DOUBLE,
            persen_potongan DOUBLE,
            nominal_potongan DOUBLE,
            nominal_diterima DOUBLE,
            status TEXT,
            source_file TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # raw attendance
        """
        CREATE TABLE IF NOT EXISTS absensi_raw (
            id TEXT PRIMARY KEY,
            import_batch_id TEXT,
            nip TEXT,
            tanggal DATE,
            jam_masuk TEXT,
            jam_pulang TEXT,
            jenis_absen TEXT,
            timezone_asal TEXT,
            jam_masuk_wib TEXT,
            jam_pulang_wib TEXT,
            source_file TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
        """,

        # attendance calculation result
        """
        CREATE TABLE IF NOT EXISTS absensi_hasil (
            id TEXT PRIMARY KEY,
            absensi_raw_id TEXT,
            nip TEXT,
            tanggal DATE,
            jam_masuk TEXT,
            jam_pulang TEXT,
            total_jam_kerja DOUBLE,
            keterlambatan_menit INTEGER,
            pulang_cepat_menit INTEGER,
            status_absen TEXT,
            persen_potongan DOUBLE,
            nominal_potongan DOUBLE,
            keterangan TEXT,
            rule_version TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # tukin refund
        """
        CREATE TABLE IF NOT EXISTS pengembalian_tukin (
            id TEXT PRIMARY KEY,
            nip TEXT,
            nama TEXT,
            tahun INTEGER,
            bulan INTEGER,
            nominal_tukin_awal DOUBLE,
            nominal_penyesuaian DOUBLE,
            nominal_pengembalian DOUBLE,
            nominal_sudah_dikembalikan DOUBLE DEFAULT 0,
            sisa_kewajiban DOUBLE,
            tanggal_pengembalian DATE,
            status_pengembalian TEXT,
            sumber_data TEXT,
            keterangan TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # meal allowance refund
        """
        CREATE TABLE IF NOT EXISTS pengembalian_uang_makan (
            id TEXT PRIMARY KEY,
            nip TEXT,
            tahun INTEGER,
            bulan INTEGER,
            nominal_awal DOUBLE,
            nominal_pengembalian DOUBLE,
            nominal_sudah_dikembalikan DOUBLE DEFAULT 0,
            sisa_kewajiban DOUBLE,
            status TEXT,
            keterangan TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # refund summary (could be a view later)
        """
        CREATE TABLE IF NOT EXISTS rekap_pengembalian (
            id TEXT PRIMARY KEY,
            tipe_kewajiban TEXT,
            nip TEXT,
            tahun INTEGER,
            bulan INTEGER,
            total_kewajiban DOUBLE,
            telah_dikembalikan DOUBLE,
            sisa_kewajiban DOUBLE
        )
        """,

        # rekonsiliasi
        """
        CREATE TABLE IF NOT EXISTS rekonsiliasi (
            id TEXT PRIMARY KEY,
            tahun INTEGER,
            bulan INTEGER,
            kategori TEXT,
            nominal_awal DOUBLE,
            nominal_perbaikan DOUBLE,
            selisih DOUBLE,
            jumlah_sdm INTEGER,
            keterangan TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
        """,

        # BNBA
        """
        CREATE TABLE IF NOT EXISTS bnba (
            id TEXT PRIMARY KEY,
            nomor_bnba TEXT,
            tanggal_bnba DATE,
            tahun INTEGER,
            bulan INTEGER,
            jenis TEXT,
            nip TEXT,
            nama TEXT,
            nominal DOUBLE,
            status TEXT,
            keterangan TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,

        # import batch
        """
        CREATE TABLE IF NOT EXISTS import_batch (
            id TEXT PRIMARY KEY,
            batch_id TEXT UNIQUE,
            nama_file TEXT,
            jenis_data TEXT,
            periode TEXT,
            tahun INTEGER,
            jumlah_baris INTEGER,
            jumlah_berhasil INTEGER,
            jumlah_gagal INTEGER,
            status TEXT,
            waktu_mulai TIMESTAMP,
            waktu_selesai TIMESTAMP,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
        """,

        # processing jobs
        """
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id TEXT PRIMARY KEY,
            type TEXT,
            status TEXT,
            payload TEXT,
            progress DOUBLE,
            message TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            result_table TEXT,
            row_count INTEGER
        )
        """,

        # audit log
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            table_name TEXT,
            record_id TEXT,
            action TEXT,
            old_value TEXT,
            new_value TEXT,
            user TEXT,
            timestamp TIMESTAMP DEFAULT now(),
            source TEXT
        )
        """,

        # workflow_config (migrate existing JSON config here too)
        """
        CREATE TABLE IF NOT EXISTS workflow_config (
            id TEXT PRIMARY KEY,
            config_json TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP
        )
        """,
    ]

    for sql in statements:
        con.execute(sql)

    # Useful indexes
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_master_sdm_nip ON master_sdm(nip);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_absensi_raw_nip ON absensi_raw(nip);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_absensi_hasil_nip ON absensi_hasil(nip);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_import_batch_batch_id ON import_batch(batch_id);")
    except Exception:
        pass

    con.close()
    print('EVKIN_MASTER schema ensured at', db_path)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Migration failed:', e, file=sys.stderr)
        raise
