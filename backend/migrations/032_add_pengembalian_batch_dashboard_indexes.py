"""Add source Batch BPK to materialized Final and dashboard indexes.

Non-destructive and idempotent: source archives and history are untouched.
"""
from pathlib import Path
import os

import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    conn = duckdb.connect(path)
    try:
        columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='pengembalian_final'"
            ).fetchall()
        }
        if "batch" not in columns:
            conn.execute("ALTER TABLE pengembalian_final ADD COLUMN batch TEXT")
        conn.execute("""UPDATE pengembalian_final
            SET batch = NULLIF(TRIM(json_extract_string(row_json, '$.batch')), '')
            WHERE (batch IS NULL OR TRIM(batch) = '')
              AND NULLIF(TRIM(json_extract_string(row_json, '$.batch')), '') IS NOT NULL""")
        # Existing row_json already contains the correctly calculated business
        # flag and source batch. Backfill the formerly generic status without
        # re-reading or overwriting immutable source archives.
        conn.execute("DROP INDEX IF EXISTS idx_peng_final_status_nip")
        conn.execute("""UPDATE pengembalian_final
            SET status_compare = flag_ada_perubahan
            WHERE flag_ada_perubahan IN ('BERUBAH','TIDAK BERUBAH')
              AND status_compare IS DISTINCT FROM flag_ada_perubahan""")
        conn.execute("""UPDATE pengembalian_final
            SET row_json = CAST(json_merge_patch(CAST(row_json AS JSON), json_object(
                'batch', batch,
                'batch_bpk', batch,
                'status_compare', status_compare,
                'status_perubahan', flag_ada_perubahan
            )) AS TEXT)
            WHERE json_extract_string(row_json,'$.batch') IS DISTINCT FROM batch
               OR json_extract_string(row_json,'$.batch_bpk') IS DISTINCT FROM batch
               OR json_extract_string(row_json,'$.status_compare') IS DISTINCT FROM status_compare
               OR json_extract_string(row_json,'$.status_perubahan') IS DISTINCT FROM flag_ada_perubahan""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_peng_final_status_nip ON pengembalian_final(status_compare,nip)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_batch ON pengembalian_final(batch)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_year_batch ON pengembalian_final(tahun_sp2d,batch)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_direction ON pengembalian_final(arah_perubahan)",
            "CREATE INDEX IF NOT EXISTS idx_peng_final_change_direction ON pengembalian_final(flag_ada_perubahan,arah_perubahan)",
        ):
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
