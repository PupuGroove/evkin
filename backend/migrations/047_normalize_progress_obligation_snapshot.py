"""Add backward-compatible initial/final snapshot fields for progress obligations."""
from pathlib import Path
import os
import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def _tables(conn):
    return {row[0] for row in conn.execute("SHOW TABLES").fetchall()}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}


def _add(conn, table, column, definition):
    if table in _tables(conn) and column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _has_columns(conn, table, required):
    return table in _tables(conn) and set(required) <= _columns(conn, table)


def _create_index_if_compatible(conn, table, columns, sql):
    if _has_columns(conn, table, columns):
        conn.execute(sql)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        for table in ("pengembalian_master_obligation", "pengembalian_obligation"):
            for name, definition in (
                ("awal_tukin", "DECIMAL(20,2) DEFAULT 0"),
                ("awal_uang_makan", "DECIMAL(20,2) DEFAULT 0"),
                ("awal_total", "DECIMAL(20,2) DEFAULT 0"),
                ("source_import_id", "TEXT"),
            ):
                _add(conn, table, name, definition)

        tables = _tables(conn)
        monthly_columns = {
            "periode_id", "nip", "tahun_sp2d_update", "tahun_sp2d_awal", "tahun",
            "pengembalian_awal_exact", "pengembalian_awal", "import_id",
        }
        master_columns = {
            "periode_id", "nip", "tahun_sp2d", "awal_tukin", "awal_uang_makan",
            "awal_total", "source_import_id", "updated_at", "opening_balance",
            "final_tukin", "final_total",
        }
        if (
            _has_columns(conn, "pengembalian_master_obligation", master_columns)
            and _has_columns(conn, "pengembalian_monthly_master", monthly_columns)
            and _has_columns(conn, "pengembalian_monthly_import", {"import_id", "status", "is_active"})
        ):
            conn.execute("""UPDATE pengembalian_master_obligation o SET
                awal_tukin=s.awal_tukin,
                awal_uang_makan=0,
                awal_total=s.awal_tukin,
                source_import_id=s.import_id,
                updated_at=now()
                FROM (
                    SELECT m.periode_id,m.nip,
                           coalesce(m.tahun_sp2d_update,m.tahun_sp2d_awal,m.tahun) tahun_sp2d,
                           sum(coalesce(m.pengembalian_awal_exact,cast(m.pengembalian_awal AS DOUBLE),0)) awal_tukin,
                           max(m.import_id) import_id
                    FROM pengembalian_monthly_master m
                    JOIN pengembalian_monthly_import i ON i.import_id=m.import_id
                    WHERE i.status='ACTIVE' AND i.is_active=TRUE
                    GROUP BY m.periode_id,m.nip,
                             coalesce(m.tahun_sp2d_update,m.tahun_sp2d_awal,m.tahun)
                ) s
                WHERE o.periode_id=s.periode_id AND o.nip=s.nip AND o.tahun_sp2d=s.tahun_sp2d""")

        if _has_columns(conn, "pengembalian_master_obligation", master_columns):
            conn.execute("""UPDATE pengembalian_master_obligation SET
                awal_tukin=CASE WHEN coalesce(awal_total,0)=0 AND coalesce(awal_tukin,0)=0
                    THEN coalesce(nullif(opening_balance,0),final_tukin,0) ELSE awal_tukin END,
                awal_total=CASE WHEN coalesce(awal_total,0)=0
                    THEN coalesce(nullif(opening_balance,0),awal_tukin,final_total,0) ELSE awal_total END,
                awal_uang_makan=coalesce(awal_uang_makan,0)""")

        legacy_columns = {
            "obligation_id", "awal_tukin", "awal_uang_makan", "awal_total",
            "source_import_id", "final_tukin", "final_total",
        }
        if (
            _has_columns(conn, "pengembalian_obligation", legacy_columns)
            and _has_columns(conn, "pengembalian_master_obligation", {"obligation_id", "awal_tukin", "awal_uang_makan", "awal_total", "source_import_id"})
        ):
            conn.execute("""UPDATE pengembalian_obligation legacy SET
                awal_tukin=master.awal_tukin,
                awal_uang_makan=master.awal_uang_makan,
                awal_total=master.awal_total,
                source_import_id=master.source_import_id
                FROM pengembalian_master_obligation master
                WHERE legacy.obligation_id=master.obligation_id""")
            conn.execute("""UPDATE pengembalian_obligation SET
                awal_tukin=CASE WHEN coalesce(awal_total,0)=0 AND coalesce(awal_tukin,0)=0
                    THEN coalesce(final_tukin,0) ELSE awal_tukin END,
                awal_total=CASE WHEN coalesce(awal_total,0)=0
                    THEN coalesce(awal_tukin,final_total,0) ELSE awal_total END,
                awal_uang_makan=coalesce(awal_uang_makan,0)""")

        _create_index_if_compatible(
            conn, "pengembalian_master_obligation", {"periode_id", "tahun_sp2d", "nip"},
            "CREATE INDEX IF NOT EXISTS idx_master_obligation_scope ON pengembalian_master_obligation(periode_id,tahun_sp2d,nip)",
        )
        _create_index_if_compatible(
            conn, "pengembalian_progress_transaction", {"periode_id", "tahun_sp2d", "tahap", "komponen_debit"},
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_scope_stage ON pengembalian_progress_transaction(periode_id,tahun_sp2d,tahap,komponen_debit)",
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
