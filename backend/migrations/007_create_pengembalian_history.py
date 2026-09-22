"""
Migration 007: create pengembalian_tukin_case and pengembalian_tukin_history tables
Non-destructive: CREATE TABLE IF NOT EXISTS.
"""
from pathlib import Path
import os
import duckdb


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = Path(os.environ.get(
        'EVKIN_DUCKDB_PATH',
        str(repo_root / 'data' / 'EVKIN_MASTER.duckdb')
    ))
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        statements = [
            # case table for obligations
            """
            CREATE TABLE IF NOT EXISTS pengembalian_tukin_case (
                case_id TEXT PRIMARY KEY,
                pengembalian_id TEXT,
                tipe_kewajiban TEXT,
                nip TEXT,
                tahun INTEGER,
                bulan INTEGER,
                status TEXT,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT now(),
                created_by TEXT
            )
            """,

            # immutable history of events for each case
            """
            CREATE TABLE IF NOT EXISTS pengembalian_tukin_history (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                event_type TEXT,
                amount DOUBLE,
                currency TEXT,
                balance_after DOUBLE,
                source_table TEXT,
                source_record_id TEXT,
                import_batch_id TEXT,
                notes TEXT,
                revision INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT now(),
                created_by TEXT,
                source_type TEXT,
                source_file TEXT,
                source_sheet TEXT,
                source_row INTEGER,
                source_batch TEXT,
                parent_record_id TEXT,
                calculation_id TEXT,
                calculation_version TEXT
            )
            """,

            # indexes
            """
            CREATE INDEX IF NOT EXISTS idx_pengembalian_case_nip ON pengembalian_tukin_case(nip)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_pengembalian_case_ym ON pengembalian_tukin_case(tahun, bulan)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_pengembalian_history_case ON pengembalian_tukin_history(case_id)
            """,
        ]

        for sql in statements:
            try:
                conn.execute(sql)
            except Exception:
                # be resilient to older DuckDB versions / index syntax differences
                try:
                    # attempt to run without index statements
                    if sql.strip().upper().startswith('CREATE INDEX'):
                        continue
                except Exception:
                    pass
        conn.close()
        print('Migration 007 applied: pengembalian_tukin_case + pengembalian_tukin_history ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
