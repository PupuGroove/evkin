"""Migration 038: deceased SDM lifecycle and optional heir payment destination."""
from pathlib import Path
import os

import duckdb


def ensure_deceased_sdm_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sdm_death_record (
            id TEXT PRIMARY KEY,
            nip TEXT NOT NULL UNIQUE,
            death_date DATE NOT NULL,
            assessment_period TEXT NOT NULL,
            stop_effective_period TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            reason TEXT NOT NULL,
            verified_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'VERIFIED',
            payment_decision TEXT NOT NULL DEFAULT 'HOLD_REVIEW',
            pay_to_heir BOOLEAN NOT NULL DEFAULT FALSE,
            heir_name TEXT,
            heir_relationship TEXT,
            heir_bank_name TEXT,
            heir_account_number TEXT,
            heir_account_holder TEXT,
            heir_document_ref TEXT,
            payment_notes TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sdm_death_audit (
            id TEXT PRIMARY KEY,
            death_record_id TEXT NOT NULL,
            nip TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            actor TEXT,
            created_at TIMESTAMP DEFAULT now()
        )"""
    )
    final_exists = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='tukin_final_monthly'"
    ).fetchone()[0]
    if final_exists:
        for column, data_type in (
            ("death_record_id", "TEXT"),
            ("recipient_type", "TEXT"),
            ("recipient_name", "TEXT"),
            ("recipient_relationship", "TEXT"),
            ("recipient_bank_name", "TEXT"),
            ("recipient_account_number", "TEXT"),
            ("recipient_account_holder", "TEXT"),
            ("beneficiary_document_ref", "TEXT"),
        ):
            conn.execute(f"ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS {column} {data_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sdm_death_period ON sdm_death_record(assessment_period,stop_effective_period)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sdm_death_audit_nip ON sdm_death_audit(nip,created_at)")


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_deceased_sdm_schema(conn)
    print(f"Migration 038 applied: deceased SDM lifecycle at {db_path}")


if __name__ == "__main__":
    main()
