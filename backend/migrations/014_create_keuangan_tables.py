"""
Migration 014: create pengembalian_keuangan_batch and pengembalian_keuangan_detail (SEND KEUANGAN)
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
            CREATE TABLE IF NOT EXISTS pengembalian_keuangan_batch (
                batch_id TEXT PRIMARY KEY,
                batch_name TEXT,
                tanggal_send TIMESTAMP,
                jenis_data TEXT,
                jumlah_sdm INTEGER,
                total_nominal DOUBLE,
                revision INTEGER DEFAULT 1,
                status TEXT,
                keterangan TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS pengembalian_keuangan_detail (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                case_id TEXT,
                nip TEXT,
                periode TEXT,
                komponen TEXT,
                nominal DOUBLE,
                status_pengembalian TEXT,
                reference_bank_batch TEXT,
                reference_bpk_batch TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        # indexes
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_keu_batch_send ON pengembalian_keuangan_batch(tanggal_send)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_keu_batch_status ON pengembalian_keuangan_batch(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_keu_detail_batch ON pengembalian_keuangan_detail(batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_keu_detail_case ON pengembalian_keuangan_detail(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_keu_detail_nip ON pengembalian_keuangan_detail(nip)')
        except Exception:
            pass

        conn.close()
        print('Migration 014 applied: pengembalian_keuangan_batch + pengembalian_keuangan_detail ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
