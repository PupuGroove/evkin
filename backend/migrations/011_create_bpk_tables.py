"""
Migration 011: create pengembalian_bpk_batch and pengembalian_bpk_detail (SEND BPK snapshots)
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
            CREATE TABLE IF NOT EXISTS pengembalian_bpk_batch (
                batch_id TEXT PRIMARY KEY,
                batch_name TEXT,
                tanggal_send TIMESTAMP,
                revision INTEGER DEFAULT 1,
                status TEXT,
                jumlah_sdm INTEGER,
                total_nominal DOUBLE,
                source_snapshot_id TEXT,
                keterangan TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS pengembalian_bpk_detail (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                case_id TEXT,
                nip TEXT,
                nama TEXT,
                periode TEXT,
                komponen TEXT,
                nominal_awal DOUBLE,
                nominal_penyesuaian DOUBLE,
                nominal_pengembalian DOUBLE,
                status TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        # indexes
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bpk_batch_name ON pengembalian_bpk_batch(batch_name)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bpk_batch_send ON pengembalian_bpk_batch(tanggal_send)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bpk_detail_batch ON pengembalian_bpk_detail(batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bpk_detail_case ON pengembalian_bpk_detail(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_bpk_detail_nip ON pengembalian_bpk_detail(nip)')
        except Exception:
            # tolerant if index creation fails in environment
            pass

        conn.close()
        print('Migration 011 applied: pengembalian_bpk_batch + pengembalian_bpk_detail ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
