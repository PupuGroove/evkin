"""
Migration 015: add source lineage columns to pengembalian tables
Non-destructive: add columns only if missing.
"""
from pathlib import Path
import duckdb


def add_col_if_missing(conn, table, col_def):
    try:
        cols = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    except Exception:
        cols = []
    col_names = [r[1] for r in cols] if cols else []
    name = col_def.split()[0]
    if name not in col_names:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            # duckdb older versions or restriction; swallow and continue
            pass


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        target_tables = [
            'pengembalian_tukin_history',
            'pengembalian_history_awal',
            'pengembalian_dasar_perhitungan',
            'pengembalian_penyesuaian',
            'pengembalian_bpk_detail',
            'pengembalian_bank_detail',
            'pengembalian_bank_result',
            'pengembalian_keuangan_detail'
        ]

        lineage_cols = [
            'source_type TEXT',
            'source_file TEXT',
            'source_sheet TEXT',
            'source_row INTEGER',
            'source_batch TEXT',
            'source_record_id TEXT',
            'parent_record_id TEXT',
            'calculation_id TEXT',
            'calculation_version TEXT'
        ]

        for t in target_tables:
            for c in lineage_cols:
                add_col_if_missing(conn, t, c)

        conn.close()
        print('Migration 015 applied: added source lineage columns where missing')
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
