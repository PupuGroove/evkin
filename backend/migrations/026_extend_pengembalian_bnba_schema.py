"""Extend the append-only BNBA archive without rewriting existing snapshots.

The source workbook has evolved over time and its headers are not reliable.
``raw_data`` remains the lossless record; these columns provide a stable,
queryable projection for all supported BNBA fields and derived indicators.
"""
from pathlib import Path
import os
import duckdb

DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)

# Stable BNBA projection (33 business columns).  Values are also retained in
# raw_data and bnba_normalized, so adding a future source column is safe.
BNBA_COLUMNS = (
    "nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun", "bulan", "periode",
    "batch", "komponen", "total_tukin", "tukin_absen_30", "tukin_skp_70",
    "potongan_skp", "esdm", "e_absensi", "tendik", "total_potongan_absen",
    "total_potongan_tukin", "daily_ref", "monthly_ref", "absence_ref",
    "total_tukin_ref", "source_record_id", "source_file", "source_sheet",
    "provinsi", "kabupaten_kota", "kdanaksatker", "unit_kerja", "jabatan",
    "golongan", "status", "npwp", "nomor_rekening", "kode_bank", "keterangan",
)
BNBA_EXTENDED_COLUMNS = (
    "nama_sdm", "kode_anak_satker", "tahun_sp2d_sebelumnya",
    "tahun_sp2d_update", "status_sp2d", "tukin_pengembalian_oktober",
    "tukin_pengembalian_november", "tukin_pengembalian_desember",
    "total_awal_tukin", "final_pengembalian_tukin_oktober",
    "final_pengembalian_tukin_november", "final_pengembalian_tukin_desember",
    "final_total_pengembalian_tukin", "pengembalian_uang_makan_oktober",
    "pengembalian_uang_makan_november", "pengembalian_uang_makan_desember",
    "final_total_pengembalian_uang_makan",
    "final_total_pengembalian_tukin_uang_makan", "batas_usia_pensiun",
    "status_pengembalian_tukin_uang_makan", "cluster_tukin",
    "cluster_uang_makan", "cluster_total", "batch_oktober_raw",
    "batch_november_raw", "batch_desember_raw", "final_batch_raw",
    "nama_bank", "nama_direk", "selisih_oktober", "flag_perubahan_oktober",
    "selisih_november", "flag_perubahan_november", "selisih_desember",
    "flag_perubahan_desember", "selisih_total_tukin", "flag_perubahan_total",
    "flag_ada_perubahan", "arah_perubahan", "batch_oktober_normalized",
    "batch_november_normalized", "batch_desember_normalized",
    "final_batch_normalized",
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        aliases = (
            ("data_awal", "pengembalian_archive_data_awal"),
            ("data_penyesuaian", "pengembalian_archive_data_penyesuaian"),
            ("pengembalian_data_awal", "pengembalian_archive_data_awal"),
            ("pengembalian_data_penyesuaian", "pengembalian_archive_data_penyesuaian"),
        )
        changed = False
        missing_by_table = {}
        for table in (
            "pengembalian_archive_data_awal",
            "pengembalian_archive_data_penyesuaian",
        ):
            # Migration is deliberately idempotent for deployed databases.
            numeric_columns = {
                "tahun_sp2d_sebelumnya", "tahun_sp2d_update", "batas_usia_pensiun",
                "tukin_pengembalian_oktober", "tukin_pengembalian_november",
                "tukin_pengembalian_desember", "total_awal_tukin",
                "final_pengembalian_tukin_oktober", "final_pengembalian_tukin_november",
                "final_pengembalian_tukin_desember", "final_total_pengembalian_tukin",
                "pengembalian_uang_makan_oktober", "pengembalian_uang_makan_november",
                "pengembalian_uang_makan_desember", "final_total_pengembalian_uang_makan",
                "final_total_pengembalian_tukin_uang_makan", "selisih_oktober",
                "selisih_november", "selisih_desember", "selisih_total_tukin",
            }
            existing = {
                row[0] for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
                ).fetchall()
            }
            base_numeric_columns = {
                "tahun_sp2d", "tahun", "bulan", "total_tukin", "tukin_absen_30",
                "tukin_skp_70", "potongan_skp", "esdm", "e_absensi", "tendik",
                "total_potongan_absen", "total_potongan_tukin",
            }
            wanted = []
            for column in BNBA_COLUMNS + BNBA_EXTENDED_COLUMNS:
                if column in existing:
                    continue
                if column in {
                    "nip", "nama", "tahun_sp2d", "nomor_sp2d", "tahun", "bulan",
                    "periode", "batch", "komponen", "total_tukin",
                    "tukin_absen_30", "tukin_skp_70", "potongan_skp", "esdm",
                    "e_absensi", "tendik", "total_potongan_absen",
                    "total_potongan_tukin", "daily_ref", "monthly_ref",
                    "absence_ref", "total_tukin_ref", "source_record_id",
                    "source_file", "source_sheet",
                }:
                    if column in {"tahun_sp2d", "tahun", "bulan"}:
                        definition = "INTEGER"
                    else:
                        definition = "DOUBLE" if column in base_numeric_columns else "TEXT"
                else:
                    definition = "DOUBLE" if column in numeric_columns else "TEXT"
                wanted.append((column, definition))
            for column, definition in (
                ("normalized_batch", "TEXT"),
                ("is_monthly", "BOOLEAN DEFAULT FALSE"),
                ("is_total", "BOOLEAN DEFAULT FALSE"),
                ("bnba_normalized", "TEXT"),
            ):
                if column not in existing:
                    wanted.append((column, definition))
            missing_by_table[table] = wanted
            changed = changed or bool(wanted)

        # DuckDB blocks ALTER TABLE while SELECT * aliases depend on it.  Drop
        # only these four read-only aliases, extend in one transaction, and
        # recreate the aliases. DuckDB cannot commit multiple ALTER operations
        # on one table in a single transaction, so each idempotent ADD COLUMN
        # is autocommitted. Source tables and rows are never dropped.
        if changed:
            for alias, _ in aliases:
                conn.execute(f'DROP VIEW IF EXISTS "{alias}"')
            try:
                for table, definitions in missing_by_table.items():
                    for column, definition in definitions:
                        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
            finally:
                for alias, physical in aliases:
                    conn.execute(f'CREATE OR REPLACE VIEW "{alias}" AS SELECT * FROM "{physical}"')

        for table in missing_by_table:
            for statement in (
                f"CREATE INDEX IF NOT EXISTS idx_{table}_period ON {table}(periode)",
                f"CREATE INDEX IF NOT EXISTS idx_{table}_batch ON {table}(normalized_batch)",
            ):
                conn.execute(statement)
        conn.commit()
    except Exception:
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
