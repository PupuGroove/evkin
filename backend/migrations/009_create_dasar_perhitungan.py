"""
Migration 009: create pengembalian_dasar_perhitungan
Non-destructive: CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.
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
            CREATE TABLE IF NOT EXISTS pengembalian_dasar_perhitungan (
                id TEXT PRIMARY KEY,
                case_id TEXT,
                calculation_batch_id TEXT,
                nip TEXT,
                periode TEXT,
                komponen TEXT,

                nilai_awal DOUBLE,
                nilai_dasar DOUBLE,
                nilai_penyesuaian DOUBLE,

                tukin_bruto DOUBLE,
                potongan_absensi DOUBLE,
                potongan_skp DOUBLE,
                potongan_esdm DOUBLE,
                potongan_eabsensi DOUBLE,
                potongan_manual DOUBLE,

                tukin_seharusnya DOUBLE,

                uang_makan_dibayar DOUBLE,
                uang_makan_seharusnya DOUBLE,

                nominal_seharusnya DOUBLE,
                nominal_kelebihan DOUBLE,
                nominal_pengembalian DOUBLE,

                calculation_version TEXT,
                rule_version TEXT,
                calculated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now()
            )
        ''')

        # indexes for efficient lookups
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dasar_case ON pengembalian_dasar_perhitungan(case_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dasar_nip ON pengembalian_dasar_perhitungan(nip)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dasar_batch ON pengembalian_dasar_perhitungan(calculation_batch_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_dasar_periode ON pengembalian_dasar_perhitungan(periode)')
        except Exception:
            # be resilient if index creation is not supported in runtime
            pass

        conn.close()
        print('Migration 009 applied: pengembalian_dasar_perhitungan ensured at', duck_path)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
