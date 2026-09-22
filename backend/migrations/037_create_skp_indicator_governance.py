"""Migration 037: versioned SKP indicator rules and meeting governance."""
from pathlib import Path
import os

import duckdb


INDICATOR_COLUMNS = (
    "hek", "verkom", "graduasi", "p2k2",
)


def ensure_skp_indicator_governance_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_indicator_config (
            id TEXT PRIMARY KEY,
            config_code TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            indicator_code TEXT NOT NULL,
            display_name TEXT NOT NULL,
            unit TEXT,
            target_mode TEXT NOT NULL DEFAULT 'FIXED',
            target_value DECIMAL(18,4),
            reaches_min_percent DECIMAL(9,4) NOT NULL DEFAULT 100,
            zero_status TEXT NOT NULL DEFAULT 'TIDAK_ADA',
            blank_status TEXT NOT NULL DEFAULT 'BELUM_DINILAI',
            scope_type TEXT NOT NULL DEFAULT 'ALL',
            scope_value TEXT,
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            legal_basis TEXT,
            meeting_document TEXT,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            created_by TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            UNIQUE(config_code, version)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_indicator_config_audit (
            id TEXT PRIMARY KEY,
            config_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            actor TEXT,
            created_at TIMESTAMP DEFAULT now()
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_meeting_batch (
            id TEXT PRIMARY KEY,
            batch_code TEXT UNIQUE NOT NULL,
            assessment_period TEXT NOT NULL,
            meeting_date DATE,
            document_number TEXT,
            recommended_predicate TEXT,
            reason TEXT NOT NULL,
            evidence_ref TEXT,
            criteria_json TEXT,
            affected_count INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'RECORDED',
            created_by TEXT,
            approved_by TEXT,
            created_at TIMESTAMP DEFAULT now(),
            approved_at TIMESTAMP
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_meeting_member (
            batch_id TEXT NOT NULL,
            assessment_period TEXT NOT NULL,
            nip TEXT NOT NULL,
            predicate_before TEXT,
            predicate_after TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT now(),
            PRIMARY KEY(batch_id, nip)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS skp_assessment_exception (
            id TEXT PRIMARY KEY,
            assessment_period TEXT NOT NULL,
            nip TEXT NOT NULL,
            exception_code TEXT NOT NULL,
            effect_type TEXT NOT NULL DEFAULT 'EXEMPT_SKP',
            start_date DATE,
            end_date DATE,
            reason TEXT NOT NULL,
            evidence_ref TEXT,
            status TEXT NOT NULL DEFAULT 'APPROVED',
            approved_by TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now(),
            UNIQUE(assessment_period, nip, exception_code)
        )"""
    )

    additions = [
        ("indicator_config_snapshot", "TEXT"),
        ("meeting_batch_id", "TEXT"),
        ("pokja_notes", "TEXT"),
        ("other_indicators_json", "TEXT"),
    ]
    for prefix in INDICATOR_COLUMNS:
        additions.extend([
            (f"{prefix}_target", "DECIMAL(18,4)"),
            (f"{prefix}_actual", "DECIMAL(18,4)"),
            (f"{prefix}_achievement_pct", "DECIMAL(18,4)"),
            (f"{prefix}_pokja_recommendation", "TEXT"),
        ])
    for column, data_type in additions:
        conn.execute(f"ALTER TABLE skp_assessment_monthly ADD COLUMN IF NOT EXISTS {column} {data_type}")

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_skp_indicator_effective ON skp_indicator_config(indicator_code,effective_from,effective_to,status)",
        "CREATE INDEX IF NOT EXISTS idx_skp_meeting_period ON skp_meeting_batch(assessment_period,created_at)",
        "CREATE INDEX IF NOT EXISTS idx_skp_exception_period ON skp_assessment_exception(assessment_period,nip,status)",
    ):
        conn.execute(statement)


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_skp_indicator_governance_schema(conn)
    print(f"Migration 037 applied: SKP indicator governance at {db_path}")


if __name__ == "__main__":
    main()
