"""Add persistent staging, file idempotency and reversible transaction state."""
from pathlib import Path
import os
import duckdb

DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb")


def _add(conn, table, column, definition):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        for name, definition in (
            ("source_file_hash", "TEXT"), ("warning_rows", "BIGINT DEFAULT 0"),
            ("tanggal_surat", "DATE"), ("nominal_berhasil", "DECIMAL(18,2) DEFAULT 0"),
            ("nominal_gagal", "DECIMAL(18,2) DEFAULT 0"),
            ("reconciliation_json", "TEXT DEFAULT '{}'"),
        ):
            _add(conn, "pengembalian_progress_import_batch", name, definition)
        for name, definition in (
            ("is_active", "BOOLEAN DEFAULT TRUE"), ("original_transaction_id", "TEXT"),
            ("correction_type", "TEXT"), ("rolled_back_at", "TIMESTAMP"),
        ):
            _add(conn, "pengembalian_progress_transaction", name, definition)
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_progress_staging (
            staging_id TEXT PRIMARY KEY, import_batch_id TEXT NOT NULL,
            source_file_name TEXT, source_file_hash TEXT, source_row_number BIGINT,
            raw_nip TEXT, normalized_nip TEXT, nama_sdm TEXT, tahun_sp2d INTEGER,
            provinsi TEXT, nama_bank_original TEXT, nama_bank_normalized TEXT,
            periode_debit TEXT, tanggal_debit DATE, tanggal_surat DATE, nomor_surat TEXT,
            debit_tukin DECIMAL(18,2), debit_uang_makan DECIMAL(18,2),
            debit_total DECIMAL(18,2), status_debit TEXT, alasan_gagal TEXT,
            komponen_debit TEXT, fingerprint TEXT, validation_status TEXT,
            matching_status TEXT, validation_messages TEXT, warning_messages TEXT,
            matched_obligation_id TEXT, existing_transaction_id TEXT,
            existing_paid DECIMAL(18,2), existing_remaining DECIMAL(18,2),
            projected_remaining DECIMAL(18,2), projected_overpayment DECIMAL(18,2),
            original_transaction_id TEXT, correction_type TEXT, raw_data TEXT,
            created_at TIMESTAMP DEFAULT now()
        )""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_progress_stage_batch ON pengembalian_progress_staging(import_batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_progress_stage_match ON pengembalian_progress_staging(normalized_nip,tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_progress_stage_fingerprint ON pengembalian_progress_staging(fingerprint)",
            "CREATE INDEX IF NOT EXISTS idx_progress_batch_hash ON pengembalian_progress_import_batch(source_file_hash)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_active ON pengembalian_progress_transaction(is_active,status_debit)",
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
