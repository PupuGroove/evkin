"""Create append-only daily calculation snapshots for Master Pengembalian."""
from pathlib import Path
import os
import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)

DAILY_COLUMNS = """
    record_id TEXT PRIMARY KEY,
    nip TEXT NOT NULL,
    nama TEXT,
    tanggal DATE,
    hari TEXT,
    tahun INTEGER,
    bulan INTEGER,
    periode TEXT,
    provinsi TEXT,
    kabupaten_kota TEXT,
    kdanaksatker TEXT,
    jam_masuk TEXT,
    jam_pulang TEXT,
    jam_kerja DOUBLE,
    jadwal_masuk TEXT,
    jadwal_pulang TEXT,
    shift TEXT,
    terlambat DOUBLE,
    pulang_cepat DOUBLE,
    status_kehadiran TEXT,
    cuti BOOLEAN,
    sakit BOOLEAN,
    izin BOOLEAN,
    keterangan TEXT,
    persentase_potongan_terlambat DOUBLE,
    persentase_potongan_pulang_cepat DOUBLE,
    persentase_potongan_harian DOUBLE,
    nilai_tukin DOUBLE,
    tukin_absen_30 DOUBLE,
    nilai_potongan_harian DOUBLE,
    master_comparison_key TEXT,
    master_record_id TEXT,
    dataset_type TEXT NOT NULL,
    source_file TEXT,
    source_row INTEGER,
    import_id TEXT NOT NULL,
    source_version TEXT,
    archive_version TEXT,
    created_at TIMESTAMP DEFAULT now()
"""


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        for table, dataset in (
            ("pengembalian_dasar_harian_awal", "DATA_DASAR_AWAL"),
            ("pengembalian_dasar_harian_penyesuaian", "DATA_DASAR_PENYESUAIAN"),
        ):
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ({DAILY_COLUMNS})"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_business "
                f"ON {table}(nip, tahun, bulan, periode)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_master_key "
                f"ON {table}(master_comparison_key)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_import "
                f"ON {table}(import_id)"
            )
        # Views expose the dataset meaning without merging or overwriting snapshots.
        conn.execute(
            """CREATE VIEW IF NOT EXISTS pengembalian_dasar_harian AS
               SELECT *, 'DATA_DASAR_AWAL' AS snapshot_type
               FROM pengembalian_dasar_harian_awal
               UNION ALL
               SELECT *, 'DATA_DASAR_PENYESUAIAN' AS snapshot_type
               FROM pengembalian_dasar_harian_penyesuaian"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pengembalian_dasar_harian_compare (
                compare_id TEXT PRIMARY KEY,
                comparison_key TEXT NOT NULL,
                nip TEXT NOT NULL,
                tanggal DATE NOT NULL,
                data_awal TEXT,
                data_penyesuaian TEXT,
                changed_fields TEXT,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT now()
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dasar_harian_compare_key "
            "ON pengembalian_dasar_harian_compare(comparison_key)"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
