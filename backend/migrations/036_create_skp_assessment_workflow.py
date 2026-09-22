"""Migration 036: auditable monthly SKP assessment workflow."""
from pathlib import Path
import os

import duckdb


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS skp_assessment_monthly (
        assessment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        sdm_id TEXT,
        nama TEXT,
        penilai TEXT,
        jabatan TEXT,
        source_predicate TEXT,
        recommended_predicate TEXT,
        final_predicate TEXT,
        report_status TEXT NOT NULL DEFAULT 'DATA_MISSING',
        hek_status TEXT DEFAULT 'BELUM_DINILAI',
        verkom_status TEXT DEFAULT 'BELUM_DINILAI',
        graduasi_status TEXT DEFAULT 'BELUM_DINILAI',
        p2k2_status TEXT DEFAULT 'BELUM_DINILAI',
        recommendation_reason TEXT,
        reviewer_notes TEXT,
        evidence_ref TEXT,
        validation_status TEXT NOT NULL DEFAULT 'VALID',
        review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
        reviewed_by TEXT,
        reviewed_at TIMESTAMP,
        approved_by TEXT,
        approved_at TIMESTAMP,
        rule_version TEXT DEFAULT 'PERMENSOS-6-2023-V1',
        source_file TEXT,
        source_row INTEGER,
        import_batch_id TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (assessment_period, nip)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skp_assessment_audit (
        id TEXT PRIMARY KEY,
        assessment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        action TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        evidence_ref TEXT,
        actor TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skp_import_batch (
        id TEXT PRIMARY KEY,
        assessment_period TEXT NOT NULL,
        source_file TEXT,
        row_count INTEGER DEFAULT 0,
        valid_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'COMPLETED',
        imported_by TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skp_rule_config (
        id TEXT PRIMARY KEY,
        third_month_action TEXT NOT NULL DEFAULT 'UNPAID',
        third_month_rate DECIMAL(9,4) NOT NULL DEFAULT 100,
        updated_by TEXT,
        updated_at TIMESTAMP DEFAULT now()
    )
    """,
)


def ensure_skp_assessment_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.execute(
        """INSERT INTO skp_rule_config (id,third_month_action,third_month_rate,updated_by)
           SELECT 'DEFAULT','UNPAID',100,'SYSTEM'
           WHERE NOT EXISTS (SELECT 1 FROM skp_rule_config WHERE id='DEFAULT')"""
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_skp_assessment_period ON skp_assessment_monthly(assessment_period,review_status)",
        "CREATE INDEX IF NOT EXISTS idx_skp_assessment_nip ON skp_assessment_monthly(nip,assessment_period)",
        "CREATE INDEX IF NOT EXISTS idx_skp_audit_nip ON skp_assessment_audit(nip,assessment_period)",
    ):
        conn.execute(statement)


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_skp_assessment_schema(conn)
    print(f"Migration 036 applied: SKP assessment workflow at {db_path}")


if __name__ == "__main__":
    main()
