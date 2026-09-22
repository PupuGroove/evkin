"""Additive schema for cumulative return-payment progress per NIP + SP2D year."""
from pathlib import Path
import os
import duckdb

DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb")


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_obligation (
            obligation_id TEXT PRIMARY KEY, nip TEXT NOT NULL, tahun_sp2d INTEGER NOT NULL,
            nama_sdm TEXT, provinsi TEXT, periode_id TEXT,
            final_tukin DECIMAL(18,2) DEFAULT 0, final_uang_makan DECIMAL(18,2) DEFAULT 0,
            final_total DECIMAL(18,2) DEFAULT 0, status_sp2d TEXT DEFAULT 'NORMAL_SP2D',
            tahun_sp2d_awal INTEGER, tahun_sp2d_update INTEGER,
            sumber_sp2d TEXT, flags_json TEXT DEFAULT '[]', source_record_ids TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT now(), updated_at TIMESTAMP DEFAULT now(),
            UNIQUE(nip, tahun_sp2d)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_progress_import_batch (
            import_batch_id TEXT PRIMARY KEY, source_filename TEXT, periode_debit TEXT,
            nama_bank_original TEXT, nama_bank_normalized TEXT, status TEXT,
            total_rows BIGINT DEFAULT 0, valid_rows BIGINT DEFAULT 0,
            invalid_rows BIGINT DEFAULT 0, duplicate_rows BIGINT DEFAULT 0,
            berhasil_rows BIGINT DEFAULT 0, gagal_rows BIGINT DEFAULT 0,
            total_tukin DECIMAL(18,2) DEFAULT 0, total_uang_makan DECIMAL(18,2) DEFAULT 0,
            total_debit DECIMAL(18,2) DEFAULT 0, metadata_json TEXT DEFAULT '{}',
            imported_by TEXT, imported_at TIMESTAMP DEFAULT now()
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_progress_transaction (
            transaction_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            import_batch_id TEXT NOT NULL, obligation_id TEXT,
            nip TEXT NOT NULL, nama_sdm TEXT, tahun_sp2d INTEGER NOT NULL, provinsi TEXT,
            nama_bank_original TEXT, nama_bank_normalized TEXT,
            periode_debit TEXT, bulan_debit INTEGER, tahun_debit INTEGER,
            tanggal_debit DATE, tanggal_surat DATE, nomor_surat TEXT,
            komponen_debit TEXT NOT NULL, nominal_debit_tukin DECIMAL(18,2) DEFAULT 0,
            nominal_debit_uang_makan DECIMAL(18,2) DEFAULT 0,
            nominal_debit_total DECIMAL(18,2) DEFAULT 0, status_debit TEXT NOT NULL,
            keterangan_gagal TEXT, kategori_gagal TEXT, source_filename TEXT,
            source_row_number BIGINT, validation_flags TEXT DEFAULT '[]', raw_data TEXT,
            created_by TEXT, created_at TIMESTAMP DEFAULT now(), updated_at TIMESTAMP DEFAULT now()
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_sp2d_lineage (
            lineage_id TEXT PRIMARY KEY, nip TEXT NOT NULL, tahun_sp2d_awal INTEGER,
            tahun_sp2d_update INTEGER, tahun_sp2d_efektif INTEGER, status_sp2d TEXT,
            sumber_sp2d TEXT, source_reference TEXT, created_at TIMESTAMP DEFAULT now()
        )""")
        # Materialized numeric dashboard columns avoid JSON extraction on every request.
        existing = {r[1] for r in conn.execute("PRAGMA table_info('pengembalian_final')").fetchall()}
        for name in ("total_tukin_awal", "final_tukin", "final_uang_makan", "final_total"):
            if name not in existing:
                conn.execute(f"ALTER TABLE pengembalian_final ADD COLUMN {name} DECIMAL(18,2)")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_progress_obligation_nip_year ON pengembalian_obligation(nip,tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_progress_obligation_nip_id ON pengembalian_obligation(nip,obligation_id)",
            "CREATE INDEX IF NOT EXISTS idx_progress_obligation_year ON pengembalian_obligation(tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_progress_nip_tenor ON pengembalian_progress_bulanan(nip,tenor_bulan)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_nip_year ON pengembalian_progress_transaction(nip,tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_obligation_status ON pengembalian_progress_transaction(obligation_id,status_debit)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_bank ON pengembalian_progress_transaction(nama_bank_normalized)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_period ON pengembalian_progress_transaction(periode_debit)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_status ON pengembalian_progress_transaction(status_debit)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_date ON pengembalian_progress_transaction(tanggal_debit)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_batch ON pengembalian_progress_transaction(import_batch_id)",
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
