"""
Migration 010: create pengembalian_penyesuaian
Non-destructive: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.

Jenis penyesuaian (informational only):
- ABSENSI, WITA, WIT, TENDIK, SP2D, CUTI, IZIN, SKP, MANUAL, LAINNYA
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
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pengembalian_penyesuaian (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                nip TEXT,
                periode TEXT,
                komponen TEXT,
                nominal_sebelum DOUBLE,
                nominal_setelah DOUBLE,
                selisih DOUBLE,
                jenis_penyesuaian TEXT,
                alasan_penyesuaian TEXT,
                reference_id TEXT,
                revision INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_penyesuaian_case ON pengembalian_penyesuaian(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_penyesuaian_nip ON pengembalian_penyesuaian(nip)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_penyesuaian_periode ON pengembalian_penyesuaian(periode)')
        except Exception:
            # be tolerant for environments that may not support index creation
            pass

        conn.close()
        print('Migration 010 applied: pengembalian_penyesuaian ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
