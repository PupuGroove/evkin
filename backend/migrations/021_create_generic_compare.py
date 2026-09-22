"""
Migration 021: create generic data compare tables
Non-destructive: CREATE TABLE IF NOT EXISTS.
"""
from pathlib import Path
import duckdb


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS generic_compare_run (
                run_id TEXT PRIMARY KEY,
                run_name TEXT,
                table_a TEXT,
                table_b TEXT,
                keys TEXT,
                compare_columns TEXT,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                status TEXT,
                total_a INTEGER,
                total_b INTEGER,
                matched_count INTEGER,
                changed_count INTEGER,
                only_a_count INTEGER,
                only_b_count INTEGER,
                duplicate_count INTEGER,
                nominal_diff_count INTEGER,
                created_by TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS generic_compare_detail (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                key_values TEXT,
                record_a TEXT,
                record_b TEXT,
                result_type TEXT,
                diffs TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_compare_run_started ON generic_compare_run(started_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_compare_detail_run ON generic_compare_detail(run_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_compare_detail_key ON generic_compare_detail(key_values)')
        except Exception:
            pass

        conn.close()
        print('Migration 021 applied: generic_compare_run and generic_compare_detail ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
