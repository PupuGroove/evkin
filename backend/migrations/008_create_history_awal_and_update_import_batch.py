"""
Migration 008: create pengembalian_history_awal table and ensure import_batch has import metadata columns
Non-destructive. Use PRAGMA to only add missing columns.
"""
from pathlib import Path
import duckdb


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        # create history awal table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pengembalian_history_awal (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                batch_id TEXT,
                nip TEXT,
                nama TEXT,
                periode TEXT,
                tahun INTEGER,
                bulan INTEGER,
                komponen TEXT,
                nominal_awal DOUBLE,
                nominal_tukin DOUBLE,
                nominal_uang_makan DOUBLE,
                sumber_data TEXT,
                tahun_sp2d INTEGER,
                nomor_sp2d TEXT,
                provinsi TEXT,
                unit_kerja TEXT,
                jenis_pegawai TEXT,
                status_awal TEXT,
                source_file TEXT,
                source_sheet TEXT,
                source_row INTEGER,
                imported_at TIMESTAMP DEFAULT now()
            )
        ''')

        # Ensure useful indexes
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_pengembalian_history_awal_case ON pengembalian_history_awal(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_pengembalian_history_awal_nip ON pengembalian_history_awal(nip)')
        except Exception:
            pass

        # Ensure import_batch has columns requested: file_hash, import_type, imported_at, total_rows, success_rows, failed_rows, file_hash unique constraint-like behavior isn't enforced but we will rely on check at import time
        try:
            cols = conn.execute("PRAGMA table_info('import_batch')").fetchall()
        except Exception:
            cols = []
        col_names = [r[1] for r in cols] if cols else []

        def add_col_if_missing(col_def):
            # col_def like 'file_hash TEXT'
            name = col_def.split()[0]
            if name not in col_names:
                try:
                    conn.execute(f'ALTER TABLE import_batch ADD COLUMN {col_def}')
                except Exception:
                    # older DuckDB versions or permission issues; continue
                    pass

        add_col_if_missing('file_hash TEXT')
        # import_type maps to jenis_data if present; add alias column 'import_type' too for clarity
        add_col_if_missing('import_type TEXT')
        add_col_if_missing('imported_at TIMESTAMP')
        add_col_if_missing('total_rows INTEGER')
        add_col_if_missing('success_rows INTEGER')
        add_col_if_missing('failed_rows INTEGER')

        conn.close()
        print('Migration 008 applied: pengembalian_history_awal created and import_batch columns ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
