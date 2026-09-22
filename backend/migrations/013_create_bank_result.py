"""
Migration 013: create pengembalian_bank_result (separate from send bank)
Non-destructive: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.
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
            CREATE TABLE IF NOT EXISTS pengembalian_bank_result (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                case_id TEXT,
                nip TEXT,
                nominal_request DOUBLE,
                nominal_berhasil DOUBLE,
                nominal_gagal DOUBLE,
                status_debet TEXT,
                kode_gagal TEXT,
                alasan_gagal TEXT,
                tanggal_proses TIMESTAMP,
                tanggal_result TIMESTAMP,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        # helpful indexes
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_result_batch ON pengembalian_bank_result(batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_result_case ON pengembalian_bank_result(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_result_nip ON pengembalian_bank_result(nip)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_result_status ON pengembalian_bank_result(status_debet)')
        except Exception:
            # tolerate environments without index support
            pass

        conn.close()
        print('Migration 013 applied: pengembalian_bank_result ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
