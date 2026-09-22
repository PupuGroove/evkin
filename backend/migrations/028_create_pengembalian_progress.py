from __future__ import annotations

import os
from pathlib import Path
import duckdb

DB = Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    conn = duckdb.connect(path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pengembalian_progress_bulanan (
                progress_id TEXT PRIMARY KEY,
                nip TEXT NOT NULL,
                nama TEXT,
                tenor_bulan INTEGER NOT NULL,
                nominal_tagihan DOUBLE DEFAULT 0,
                nominal_dikirim DOUBLE DEFAULT 0,
                nominal_berhasil DOUBLE DEFAULT 0,
                nominal_gagal DOUBLE DEFAULT 0,
                status TEXT,
                keterangan TEXT,
                source_file TEXT,
                imported_at TIMESTAMP DEFAULT now(),
                imported_by TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pengembalian_progress_nip ON pengembalian_progress_bulanan(nip)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pengembalian_progress_tenor ON pengembalian_progress_bulanan(tenor_bulan)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
