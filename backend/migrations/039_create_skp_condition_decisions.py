"""Migration 039: governed SKP conditions with downstream Tukin effects."""
from pathlib import Path
import os

import duckdb


def ensure_skp_condition_decision_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_condition_decision (
            id TEXT PRIMARY KEY,
            assessment_period TEXT NOT NULL,
            nip TEXT NOT NULL,
            condition_code TEXT NOT NULL,
            start_date DATE,
            end_date DATE,
            skp_effect TEXT NOT NULL DEFAULT 'NONE',
            recommended_predicate TEXT,
            payment_effect TEXT NOT NULL DEFAULT 'NONE',
            reason TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            document_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'APPROVED',
            approved_by TEXT NOT NULL,
            approved_at TIMESTAMP DEFAULT now(),
            synced_to_tukin BOOLEAN NOT NULL DEFAULT FALSE,
            synced_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            UNIQUE(assessment_period,nip,condition_code)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_condition_decision_audit (
            id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            assessment_period TEXT NOT NULL,
            nip TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            actor TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_skp_condition_period ON skp_condition_decision(assessment_period,nip,status)"
    )


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_skp_condition_decision_schema(conn)
    print(f"Migration 039 applied: SKP condition decisions at {db_path}")


if __name__ == "__main__":
    main()
