"""Ensure archive source snapshots expose the Tahun SP2D business field."""
from pathlib import Path
import os
import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        for table in (
            "pengembalian_archive_data_awal",
            "pengembalian_archive_data_penyesuaian",
        ):
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN tahun_sp2d INTEGER"
                )
            except Exception:
                # Existing installations already created by migration 023
                # already contain the column.
                pass
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
