"""Add lifecycle and period isolation for multiple Master Pengembalian workspaces."""
from pathlib import Path
import json
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
        for name, definition in (
            ("tahun_proses", "INTEGER"), ("bulan_proses", "INTEGER"),
            ("tahun_penghasilan", "INTEGER"), ("bulan_penghasilan", "INTEGER"),
            ("is_active", "BOOLEAN DEFAULT FALSE"), ("locked_at", "TIMESTAMP"),
            ("archived_at", "TIMESTAMP"), ("created_by", "TEXT"), ("notes", "TEXT"),
        ):
            _add(conn, "pengembalian_period", name, definition)
        conn.execute("""UPDATE pengembalian_period SET
            tahun_proses=COALESCE(tahun_proses,tahun),
            bulan_proses=COALESCE(bulan_proses,bulan_awal),
            tahun_penghasilan=COALESCE(tahun_penghasilan,tahun),
            bulan_penghasilan=COALESCE(bulan_penghasilan,bulan_awal),
            is_active=COALESCE(is_active,FALSE)""")

        _add(conn, "pengembalian_archive_import", "periode_id", "TEXT")
        conn.execute("""UPDATE pengembalian_archive_import SET periode_id=
            COALESCE(periode_id,json_extract_string(metadata,'$.periode_id'))
            WHERE periode_id IS NULL""")
        for table in ("pengembalian_progress_import_batch", "pengembalian_progress_staging",
                      "pengembalian_progress_transaction"):
            _add(conn, table, "periode_id", "TEXT")

        # V2 obligation grain includes periode_id. The legacy table remains intact
        # as a recovery source and is not dropped by this additive migration.
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_master_obligation (
            obligation_id TEXT PRIMARY KEY, periode_id TEXT NOT NULL,
            nip TEXT NOT NULL, tahun_sp2d INTEGER NOT NULL,
            nama_sdm TEXT, provinsi TEXT,
            final_tukin DECIMAL(18,2) DEFAULT 0,
            final_uang_makan DECIMAL(18,2) DEFAULT 0,
            final_total DECIMAL(18,2) DEFAULT 0,
            status_sp2d TEXT DEFAULT 'NORMAL_SP2D',
            tahun_sp2d_awal INTEGER, tahun_sp2d_update INTEGER,
            sumber_sp2d TEXT, flags_json TEXT DEFAULT '[]',
            source_record_ids TEXT DEFAULT '[]', opening_balance DECIMAL(18,2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT now(), updated_at TIMESTAMP DEFAULT now(),
            UNIQUE(periode_id,nip,tahun_sp2d)
        )""")
        conn.execute("""INSERT INTO pengembalian_master_obligation
            (obligation_id,periode_id,nip,tahun_sp2d,nama_sdm,provinsi,final_tukin,
             final_uang_makan,final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,
             sumber_sp2d,flags_json,source_record_ids,created_at,updated_at)
            SELECT obligation_id,COALESCE(periode_id,'LEGACY'),nip,tahun_sp2d,nama_sdm,
                   provinsi,final_tukin,final_uang_makan,final_total,status_sp2d,
                   tahun_sp2d_awal,tahun_sp2d_update,sumber_sp2d,flags_json,
                   source_record_ids,created_at,updated_at
            FROM pengembalian_obligation
            ON CONFLICT (periode_id,nip,tahun_sp2d) DO NOTHING""")
        conn.execute("""UPDATE pengembalian_progress_transaction t SET periode_id=o.periode_id
            FROM pengembalian_master_obligation o
            WHERE t.periode_id IS NULL AND t.obligation_id=o.obligation_id""")

        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_period_audit (
            audit_id TEXT PRIMARY KEY, periode_id TEXT, action TEXT NOT NULL,
            previous_status TEXT, new_status TEXT, details_json TEXT DEFAULT '{}',
            created_by TEXT, created_at TIMESTAMP DEFAULT now()
        )""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_peng_period_active ON pengembalian_period(is_active,status)",
            "CREATE INDEX IF NOT EXISTS idx_peng_import_period ON pengembalian_archive_import(periode_id)",
            "CREATE INDEX IF NOT EXISTS idx_master_obligation_period_nip ON pengembalian_master_obligation(periode_id,nip,tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_progress_batch_master ON pengembalian_progress_import_batch(periode_id,imported_at)",
            "CREATE INDEX IF NOT EXISTS idx_progress_stage_master ON pengembalian_progress_staging(periode_id,import_batch_id)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_master ON pengembalian_progress_transaction(periode_id,nip,tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_period_audit_period ON pengembalian_period_audit(periode_id,created_at)",
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
