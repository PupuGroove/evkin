"""Create normalized attendance-recap basis and derived calculation tables.

The migration is additive. Source BNBA snapshots and arbitrary dataset JSON rows
remain immutable; the new tables can be rebuilt from those sources.
"""
from pathlib import Path
import os

import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}


def _add(conn, table, column, definition):
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        _add(conn, "pengembalian_archive_dataset", "bulan", "INTEGER")
        _add(conn, "pengembalian_archive_dataset", "metadata_json", "TEXT DEFAULT '{}'")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_dasar_rekap_absensi (
            record_id TEXT PRIMARY KEY,
            periode_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            nip TEXT NOT NULL,
            tahun INTEGER,
            bulan INTEGER NOT NULL,
            persentase_potongan DECIMAL(18,9),
            raw_value TEXT,
            validation_status TEXT NOT NULL,
            validation_message TEXT,
            source_filename TEXT,
            source_sheet TEXT,
            source_row BIGINT,
            created_at TIMESTAMP DEFAULT now(),
            UNIQUE(dataset_id,source_row)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_dasar_kalkulasi_absensi (
            calculation_id TEXT PRIMARY KEY,
            periode_id TEXT NOT NULL,
            final_record_id TEXT NOT NULL,
            nip TEXT NOT NULL,
            total_tukin DECIMAL(18,2),
            tukin_absen_30 DECIMAL(18,2),
            persen_oktober DECIMAL(18,9),
            persen_november DECIMAL(18,9),
            persen_desember DECIMAL(18,9),
            raw_oktober DECIMAL(24,9),
            raw_november DECIMAL(24,9),
            raw_desember DECIMAL(24,9),
            nominal_oktober BIGINT,
            nominal_november BIGINT,
            nominal_desember BIGINT,
            nominal_total BIGINT,
            current_oktober BIGINT,
            current_november BIGINT,
            current_desember BIGINT,
            current_total BIGINT,
            selisih_oktober BIGINT,
            selisih_november BIGINT,
            selisih_desember BIGINT,
            selisih_total BIGINT,
            validation_status TEXT NOT NULL,
            issues_json TEXT DEFAULT '[]',
            source_dataset_ids TEXT DEFAULT '{}',
            formula_version TEXT NOT NULL,
            calculated_at TIMESTAMP DEFAULT now(),
            UNIQUE(periode_id,final_record_id)
        )""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_dasar_rekap_period_nip ON pengembalian_dasar_rekap_absensi(periode_id,nip,bulan)",
            "CREATE INDEX IF NOT EXISTS idx_dasar_rekap_dataset ON pengembalian_dasar_rekap_absensi(dataset_id,source_row)",
            "CREATE INDEX IF NOT EXISTS idx_dasar_calc_period_nip ON pengembalian_dasar_kalkulasi_absensi(periode_id,nip)",
            "CREATE INDEX IF NOT EXISTS idx_dasar_calc_final ON pengembalian_dasar_kalkulasi_absensi(final_record_id)",
        ):
            conn.execute(sql)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
