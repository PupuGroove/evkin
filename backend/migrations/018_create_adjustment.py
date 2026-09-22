"""
Migration 018: create pengembalian_adjustment (official adjustments after BPK/Bank)
Non-destructive: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.

Rules: adjustments are append-only; do not change history rows.
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
            CREATE TABLE IF NOT EXISTS pengembalian_adjustment (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                adjustment_type TEXT,
                nominal_before DOUBLE,
                adjustment_value DOUBLE,
                nominal_after DOUBLE,
                reason TEXT,
                reference_document TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_adjustment_case ON pengembalian_adjustment(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_adjustment_type ON pengembalian_adjustment(adjustment_type)')
        except Exception:
            pass

        conn.close()
        print('Migration 018 applied: pengembalian_adjustment ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
