"""Migration 034: annual Tukin management, history, SKP, payments, and evidence."""
from pathlib import Path
import os

import duckdb


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS tukin_period (
        assessment_period TEXT PRIMARY KEY,
        payment_period TEXT NOT NULL,
        year INTEGER NOT NULL,
        semester INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'DRAFT',
        source_mode TEXT NOT NULL DEFAULT 'LIVE',
        notes TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        locked_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_import_batch (
        id TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        assessment_period TEXT NOT NULL,
        payment_period TEXT,
        source_file TEXT,
        file_size BIGINT,
        row_count INTEGER DEFAULT 0,
        imported_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        checksum TEXT,
        status TEXT NOT NULL DEFAULT 'COMPLETED',
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_skp_monthly (
        assessment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        nama TEXT,
        penilai TEXT,
        jabatan TEXT,
        tahap TEXT,
        predicate_raw TEXT,
        predicate_normalized TEXT,
        report_status TEXT NOT NULL DEFAULT 'DATA_MISSING',
        consecutive_missing INTEGER DEFAULT 0,
        skp_reduction_rate DECIMAL(9,4) DEFAULT 0,
        payment_eligible BOOLEAN DEFAULT TRUE,
        exception_code TEXT,
        source_file TEXT,
        source_row INTEGER,
        import_batch_id TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (assessment_period, nip)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_final_monthly (
        assessment_period TEXT NOT NULL,
        payment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        sdm_id TEXT,
        nama TEXT,
        penilai TEXT,
        kd_anak_satker TEXT,
        jabatan TEXT,
        unit TEXT,
        kelas_jabatan INTEGER,
        employment_status TEXT,
        tahap TEXT,
        wilayah_3t TEXT,
        status_sdm TEXT,
        jabatan_sdm TEXT,
        temporary_assignment_type TEXT,
        temporary_assignment_detail TEXT,
        temporary_assignment_effective_month TEXT,
        predicate_skp TEXT,
        report_status TEXT,
        consecutive_missing INTEGER DEFAULT 0,
        tahun INTEGER,
        bulan TEXT,
        tukin_gross DECIMAL(18,2) DEFAULT 0,
        skp_reduction_rate DECIMAL(9,4) DEFAULT 0,
        attendance_reduction_rate DECIMAL(9,4) DEFAULT 0,
        skp_deduction DECIMAL(18,2) DEFAULT 0,
        attendance_deduction DECIMAL(18,2) DEFAULT 0,
        manual_adjustment DECIMAL(18,2) DEFAULT 0,
        total_deduction DECIMAL(18,2) DEFAULT 0,
        calculated_entitlement DECIMAL(18,2) DEFAULT 0,
        paid_amount DECIMAL(18,2) DEFAULT 0,
        payment_status TEXT DEFAULT 'READY_TO_PAY',
        payment_reason TEXT,
        province TEXT,
        regency TEXT,
        account_number TEXT,
        bank_name TEXT,
        account_holder TEXT,
        special_conditions TEXT,
        evidence_status TEXT,
        master_version INTEGER,
        snapshot_at TIMESTAMP,
        calculation_version TEXT DEFAULT 'PERMENSOS-6-2023-V1',
        source_mode TEXT DEFAULT 'HISTORICAL',
        source_file TEXT,
        source_row INTEGER,
        import_batch_id TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (assessment_period, nip)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_attendance_daily (
        assessment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        work_date DATE NOT NULL,
        nama TEXT,
        day_name TEXT,
        check_in TEXT,
        check_out TEXT,
        attendance_type TEXT,
        attendance_status TEXT,
        reduction_rate DECIMAL(9,4) DEFAULT 0,
        deduction_amount DECIMAL(18,2) DEFAULT 0,
        reason TEXT,
        evidence_ref TEXT,
        source_file TEXT,
        source_row INTEGER,
        import_batch_id TEXT,
        created_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (assessment_period, nip, work_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_condition (
        id TEXT PRIMARY KEY,
        nip TEXT NOT NULL,
        assessment_period TEXT NOT NULL,
        condition_code TEXT NOT NULL,
        start_date DATE,
        end_date DATE,
        effect_type TEXT DEFAULT 'REVIEW',
        effect_value DECIMAL(18,4) DEFAULT 0,
        reason TEXT,
        evidence_ref TEXT,
        approved_by TEXT,
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tukin_payment_event (
        id TEXT PRIMARY KEY,
        assessment_period TEXT NOT NULL,
        nip TEXT NOT NULL,
        status TEXT NOT NULL,
        amount DECIMAL(18,2) DEFAULT 0,
        reason_code TEXT,
        reference_number TEXT,
        event_at TIMESTAMP DEFAULT now(),
        created_by TEXT
    )
    """,
)


def ensure_tukin_annual_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    for statement in (
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS sdm_id TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS unit TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS kelas_jabatan INTEGER",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS employment_status TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS account_holder TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS master_version INTEGER",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS snapshot_at TIMESTAMP",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_type TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_detail TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_effective_month TEXT",
        "CREATE INDEX IF NOT EXISTS idx_tukin_final_year ON tukin_final_monthly(tahun)",
        "CREATE INDEX IF NOT EXISTS idx_tukin_final_nip ON tukin_final_monthly(nip)",
        "CREATE INDEX IF NOT EXISTS idx_tukin_skp_nip ON tukin_skp_monthly(nip)",
        "CREATE INDEX IF NOT EXISTS idx_tukin_daily_nip ON tukin_attendance_daily(nip)",
    ):
        conn.execute(statement)


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parents[1] / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_tukin_annual_schema(conn)
    print(f"Migration 034 applied: annual Tukin management schema at {db_path}")


if __name__ == "__main__":
    main()
