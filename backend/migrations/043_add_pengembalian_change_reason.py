"""Add a normalized change reason to the canonical monthly master."""
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
        conn.execute("ALTER TABLE pengembalian_monthly_master ADD COLUMN IF NOT EXISTS alasan_perubahan TEXT")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_monthly_master_reason
            ON pengembalian_monthly_master(alasan_perubahan,status_perubahan)""")
        conn.execute("""UPDATE pengembalian_monthly_master
            SET alasan_perubahan = CASE
                WHEN cek_selisih IS NULL OR trim(cek_selisih) IN ('', '0', '0.0') THEN
                    CASE WHEN status_perubahan='TIDAK BERUBAH' THEN 'TIDAK ADA PERUBAHAN'
                         ELSE 'PERUBAHAN TANPA KETERANGAN' END
                ELSE upper(trim(cek_selisih))
            END
            WHERE alasan_perubahan IS NULL OR trim(alasan_perubahan)=''""")
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
