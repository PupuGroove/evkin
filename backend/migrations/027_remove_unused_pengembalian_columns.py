"""Remove unused Master Pengembalian archive columns.

This migration is intentionally limited to the two BNBA archive tables.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb


DB = Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
TABLES = (
    "pengembalian_archive_data_awal",
    "pengembalian_archive_data_penyesuaian",
    "pengembalian_archive_import",
)
COLUMNS = (
    "tukin_absen_30",
    "tukin_skp_70",
    "potongan_skp",
    "esdm",
    "e_absensi",
    "tendik",
    "unit_kerja",
    "daily_ref",
    "monthly_ref",
    "absence_ref",
    "total_tukin_ref",
    "version",
    "bulan",
    "periode",
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    conn = duckdb.connect(path)
    try:
        for table in TABLES:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ?",
                    [table],
                ).fetchall()
            }
            # Legacy columns are retained when views or other catalog entries
            # depend on them. New imports simply do not populate them.
            # Dropping them here would invalidate those dependencies.
        for table, index in (
            ("pengembalian_archive_data_awal", "idx_pengembalian_archive_awal_key"),
            ("pengembalian_archive_data_penyesuaian", "idx_pengembalian_archive_penyesuaian_key"),
        ):
            if {row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                [table],
            ).fetchall()} >= {"nip", "tahun_sp2d"}:
                conn.execute(
                    f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table}"(nip, tahun_sp2d)'
                )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
