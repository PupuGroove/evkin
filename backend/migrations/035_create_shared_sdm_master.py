"""Migration 035: canonical shared SDM master with effective-dated Tukin data."""
from pathlib import Path
import os

import duckdb


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sdm_master (
        sdm_id TEXT PRIMARY KEY,
        nip TEXT NOT NULL UNIQUE,
        nama TEXT,
        jenis_sdm TEXT,
        employment_status TEXT DEFAULT 'AKTIF',
        jabatan TEXT,
        unit TEXT,
        kd_anak_satker TEXT,
        provinsi TEXT,
        kabupaten_kota TEXT,
        penilai TEXT,
        active BOOLEAN DEFAULT TRUE,
        master_version INTEGER DEFAULT 1,
        valid_from DATE,
        valid_to DATE,
        source_file TEXT,
        source_row INTEGER,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_assignment_history (
        id TEXT PRIMARY KEY,
        sdm_id TEXT NOT NULL,
        nip TEXT NOT NULL,
        jabatan TEXT,
        unit TEXT,
        kd_anak_satker TEXT,
        provinsi TEXT,
        kabupaten_kota TEXT,
        penilai TEXT,
        valid_from DATE NOT NULL,
        valid_to DATE,
        source_file TEXT,
        change_reason TEXT,
        approved_by TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_tukin_profile_history (
        id TEXT PRIMARY KEY,
        sdm_id TEXT NOT NULL,
        nip TEXT NOT NULL,
        kelas_jabatan INTEGER,
        tukin_gross DECIMAL(18,2) DEFAULT 0,
        eligible BOOLEAN DEFAULT TRUE,
        eligibility_reason TEXT,
        wilayah_3t BOOLEAN DEFAULT FALSE,
        status_tendik TEXT,
        jabatan_osdm TEXT,
        valid_from DATE NOT NULL,
        valid_to DATE,
        source_file TEXT,
        change_reason TEXT,
        approved_by TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_bank_history (
        id TEXT PRIMARY KEY,
        sdm_id TEXT NOT NULL,
        nip TEXT NOT NULL,
        bank_name TEXT,
        account_number TEXT,
        account_holder TEXT,
        valid_from DATE NOT NULL,
        valid_to DATE,
        source_file TEXT,
        change_reason TEXT,
        approved_by TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_temporary_assignment_history (
        id TEXT PRIMARY KEY,
        sdm_id TEXT NOT NULL,
        nip TEXT NOT NULL,
        effective_month TEXT NOT NULL,
        assignment_type TEXT NOT NULL,
        assignment_detail TEXT,
        raw_value TEXT,
        source_file TEXT,
        source_row INTEGER,
        change_reason TEXT,
        approved_by TEXT,
        import_batch_id TEXT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now(),
        UNIQUE (nip, effective_month)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_change_request (
        id TEXT PRIMARY KEY,
        batch_id TEXT,
        nip TEXT NOT NULL,
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        effective_date DATE,
        status TEXT DEFAULT 'APPROVED',
        source_file TEXT,
        reason TEXT,
        reviewed_by TEXT,
        reviewed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_active_history (
        id TEXT PRIMARY KEY,
        sdm_id TEXT NOT NULL,
        nip TEXT NOT NULL,
        active BOOLEAN NOT NULL,
        valid_from DATE NOT NULL,
        valid_to DATE,
        reason TEXT,
        approved_by TEXT NOT NULL,
        source_file TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_validation_issue (
        id TEXT PRIMARY KEY,
        nip TEXT,
        issue_type TEXT NOT NULL,
        severity TEXT DEFAULT 'WARNING',
        source_table TEXT,
        source_value TEXT,
        master_value TEXT,
        details TEXT,
        status TEXT DEFAULT 'OPEN',
        resolved_by TEXT,
        resolved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sdm_master_import_batch (
        id TEXT PRIMARY KEY,
        source_file TEXT,
        effective_date DATE,
        row_count INTEGER DEFAULT 0,
        new_count INTEGER DEFAULT 0,
        changed_count INTEGER DEFAULT 0,
        unchanged_count INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'COMPLETED',
        approved_by TEXT,
        created_at TIMESTAMP DEFAULT now()
    )
    """,
)


def ensure_shared_master_schema(conn: duckdb.DuckDBPyConnection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_sdm_master_nip ON sdm_master(nip)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_assignment_nip ON sdm_assignment_history(nip,valid_from)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_profile_nip ON sdm_tukin_profile_history(nip,valid_from)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_bank_nip ON sdm_bank_history(nip,valid_from)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_temp_assignment_nip ON sdm_temporary_assignment_history(nip,effective_month)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_active_history_nip ON sdm_active_history(nip,valid_from)",
        "CREATE INDEX IF NOT EXISTS idx_sdm_issue_status ON sdm_validation_issue(status,issue_type)",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS sdm_id TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS master_version INTEGER",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS snapshot_at TIMESTAMP",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS kelas_jabatan INTEGER",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS unit TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS account_holder TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS employment_status TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_type TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_detail TEXT",
        "ALTER TABLE tukin_final_monthly ADD COLUMN IF NOT EXISTS temporary_assignment_effective_month TEXT",
    ):
        try:
            conn.execute(statement)
        except duckdb.CatalogException:
            # The annual module may not have been initialized yet. Its own
            # schema bootstrap will add snapshot columns on the next request.
            if not statement.startswith("ALTER TABLE tukin_final_monthly"):
                raise
    conn.execute(
        """INSERT INTO sdm_active_history
           (id,sdm_id,nip,active,valid_from,reason,approved_by,source_file)
           SELECT uuid()::VARCHAR,m.sdm_id,m.nip,coalesce(m.active,true),coalesce(m.valid_from,CURRENT_DATE),
                  'Migrasi status awal','SYSTEM','SCHEMA_MIGRATION'
           FROM sdm_master m
           WHERE NOT EXISTS (SELECT 1 FROM sdm_active_history h WHERE h.nip=m.nip)"""
    )


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parents[1] / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_shared_master_schema(conn)
    print(f"Migration 035 applied: shared SDM master schema at {db_path}")


if __name__ == "__main__":
    main()
