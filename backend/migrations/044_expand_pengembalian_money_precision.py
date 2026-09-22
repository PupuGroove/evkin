"""Preserve source precision so dashboard totals reconcile with the workbook."""
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
        conn.execute("ALTER TABLE pengembalian_monthly_master ADD COLUMN IF NOT EXISTS pengembalian_awal_exact DOUBLE")
        conn.execute("ALTER TABLE pengembalian_monthly_master ADD COLUMN IF NOT EXISTS final_pengembalian_exact DOUBLE")
        conn.execute("ALTER TABLE pengembalian_monthly_master ADD COLUMN IF NOT EXISTS selisih_pengembalian_exact DOUBLE")
        conn.execute("""UPDATE pengembalian_monthly_master SET
            pengembalian_awal_exact=coalesce(pengembalian_awal_exact,cast(pengembalian_awal AS DOUBLE)),
            final_pengembalian_exact=coalesce(final_pengembalian_exact,cast(final_pengembalian AS DOUBLE)),
            selisih_pengembalian_exact=coalesce(selisih_pengembalian_exact,cast(selisih_pengembalian AS DOUBLE))""")
        conn.execute("""CREATE OR REPLACE VIEW vw_pengembalian_monthly_current AS
            SELECT m.* FROM pengembalian_monthly_master m
            JOIN pengembalian_monthly_import i ON i.import_id=m.import_id
            WHERE i.status='ACTIVE' AND i.is_active=TRUE
        """)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
