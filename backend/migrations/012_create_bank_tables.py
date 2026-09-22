"""
Migration 012: create pengembalian_bank_batch and pengembalian_bank_detail (SEND BANK)
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
            CREATE TABLE IF NOT EXISTS pengembalian_bank_batch (
                batch_id TEXT PRIMARY KEY,
                batch_name TEXT,
                tanggal_send TIMESTAMP,
                bank TEXT,
                jenis_debet TEXT,
                jumlah_rekening INTEGER,
                total_nominal DOUBLE,
                status TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS pengembalian_bank_detail (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                case_id TEXT,
                nip TEXT,
                nama TEXT,
                nomor_rekening TEXT,
                periode TEXT,
                komponen TEXT,
                nominal_debet DOUBLE,
                cluster TEXT,
                angsuran_ke INTEGER,
                status_send TEXT,
                reference_bpk_batch TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        # indexes
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_batch_send ON pengembalian_bank_batch(tanggal_send)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_batch_bank ON pengembalian_bank_batch(bank)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_detail_batch ON pengembalian_bank_detail(batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_detail_case ON pengembalian_bank_detail(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bank_detail_nip ON pengembalian_bank_detail(nip)')
        except Exception:
            pass

        conn.close()
        print('Migration 012 applied: pengembalian_bank_batch + pengembalian_bank_detail ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
