"""Stable multi-period archive schema for Master Pengembalian.

No existing table is dropped or rewritten. Flexible Data Dasar rows use JSON,
so importing a new spreadsheet shape never requires ALTER TABLE.
"""
from pathlib import Path
import os
import duckdb

DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_period (
                periode_id TEXT PRIMARY KEY, nama_periode TEXT NOT NULL,
                tahun INTEGER, bulan_awal INTEGER, bulan_akhir INTEGER,
                status TEXT DEFAULT 'ACTIVE', created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            )
        """)
        # Periods are user-managed Master data. Do not seed a default row here:
        # migrations run again after restart and would otherwise resurrect a
        # period that the user intentionally removed or cleared.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_archive_dataset (
                dataset_id TEXT PRIMARY KEY, periode_id TEXT, nama_dataset TEXT NOT NULL,
                jenis_dataset TEXT, source_filename TEXT, sheet_name TEXT,
                jumlah_baris BIGINT DEFAULT 0, jumlah_kolom INTEGER DEFAULT 0,
                schema_json TEXT NOT NULL, checksum TEXT, status TEXT DEFAULT 'SUCCESS',
                imported_by TEXT, tanggal_import TIMESTAMP DEFAULT now(),
                created_at TIMESTAMP DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_archive_dataset_row (
                dataset_id TEXT NOT NULL, row_number BIGINT NOT NULL,
                row_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_payment_transaction (
                transaction_id TEXT PRIMARY KEY, obligation_key TEXT NOT NULL,
                periode_id TEXT, nip TEXT NOT NULL, tanggal_debit DATE,
                bulan_debit TEXT, nominal DECIMAL(18,2) NOT NULL,
                komponen TEXT, status_debit TEXT NOT NULL, alasan_gagal TEXT,
                kategori_gagal TEXT, batch_debit TEXT, source_import TEXT,
                raw_data TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_final (
                record_id TEXT PRIMARY KEY, comparison_key TEXT NOT NULL,
                periode_id TEXT, nip TEXT, nama TEXT, tahun_sp2d INTEGER,
                periode TEXT, batch TEXT, provinsi TEXT, kabupaten_kota TEXT, unit_kerja TEXT,
                status_compare TEXT, arah_perubahan TEXT, ada_perubahan TEXT,
                flag_ada_perubahan TEXT, status_lunas TEXT,
                nilai_awal DECIMAL(18,2), nilai_final DECIMAL(18,2),
                selisih_total DECIMAL(18,2), total_debit_berhasil DECIMAL(18,2),
                total_debit_gagal DECIMAL(18,2), sisa_piutang DECIMAL(18,2),
                row_json TEXT NOT NULL, updated_at TIMESTAMP DEFAULT now()
            )
        """)
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_peng_period_year ON pengembalian_period(tahun)",
            "CREATE INDEX IF NOT EXISTS idx_peng_dataset_period ON pengembalian_archive_dataset(periode_id)",
            "CREATE INDEX IF NOT EXISTS idx_peng_dataset_row ON pengembalian_archive_dataset_row(dataset_id, row_number)",
            "CREATE INDEX IF NOT EXISTS idx_peng_payment_key ON pengembalian_payment_transaction(obligation_key)",
            "CREATE INDEX IF NOT EXISTS idx_peng_payment_key_status ON pengembalian_payment_transaction(obligation_key,status_debit)",
            "CREATE INDEX IF NOT EXISTS idx_peng_payment_nip ON pengembalian_payment_transaction(nip)",
            "CREATE INDEX IF NOT EXISTS idx_peng_payment_period ON pengembalian_payment_transaction(periode_id)",
            "CREATE INDEX IF NOT EXISTS idx_peng_payment_status ON pengembalian_payment_transaction(status_debit)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_period ON pengembalian_final(periode_id)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_nip ON pengembalian_final(nip)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_change ON pengembalian_final(flag_ada_perubahan)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_status_nip ON pengembalian_final(status_compare,nip)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_period_record ON pengembalian_final(periode_id,record_id)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_payment ON pengembalian_final(status_lunas)",
        ):
            conn.execute(sql)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
