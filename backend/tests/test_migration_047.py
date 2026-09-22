import importlib.util
from pathlib import Path

import duckdb


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "047_normalize_progress_obligation_snapshot.py"


def _run(db_path):
    spec = importlib.util.spec_from_file_location("migration_047_regression", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(db_path)


def _indexes(conn, table):
    return {
        row[0]
        for row in conn.execute("SELECT index_name FROM duckdb_indexes() WHERE table_name=?", [table]).fetchall()
    }


def test_migration_047_is_safe_for_legacy_schema_without_tahap(tmp_path):
    db = tmp_path / "legacy.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("""CREATE TABLE pengembalian_progress_transaction (
        transaction_id TEXT, periode_id TEXT, tahun_sp2d INTEGER, komponen_debit TEXT
    )""")
    conn.execute("INSERT INTO pengembalian_progress_transaction VALUES ('TX-1','P-1',2025,'TUKIN')")
    conn.close()

    _run(db)

    conn = duckdb.connect(str(db))
    assert conn.execute("SELECT count(*) FROM pengembalian_progress_transaction").fetchone()[0] == 1
    assert "idx_progress_tx_scope_stage" not in _indexes(conn, "pengembalian_progress_transaction")
    conn.close()


def test_migration_047_is_safe_for_partial_schema(tmp_path):
    db = tmp_path / "partial.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE pengembalian_master_obligation (obligation_id TEXT PRIMARY KEY, nip TEXT)")
    conn.execute("INSERT INTO pengembalian_master_obligation VALUES ('O-1','100')")
    conn.close()

    _run(db)

    conn = duckdb.connect(str(db))
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pengembalian_master_obligation')").fetchall()}
    assert {"awal_tukin", "awal_uang_makan", "awal_total", "source_import_id"} <= columns
    assert conn.execute("SELECT obligation_id,nip FROM pengembalian_master_obligation").fetchone() == ("O-1", "100")
    conn.close()


def test_migration_047_creates_indexes_for_current_schema_and_can_rerun(tmp_path):
    db = tmp_path / "current.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("""CREATE TABLE pengembalian_master_obligation (
        obligation_id TEXT, periode_id TEXT, nip TEXT, tahun_sp2d INTEGER,
        opening_balance DECIMAL(20,2), final_tukin DECIMAL(20,2), final_total DECIMAL(20,2),
        updated_at TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE pengembalian_progress_transaction (
        transaction_id TEXT, periode_id TEXT, tahun_sp2d INTEGER, tahap INTEGER,
        komponen_debit TEXT
    )""")
    conn.execute("INSERT INTO pengembalian_master_obligation VALUES ('O-1','P-1','100',2025,100,100,100,now())")
    conn.close()

    _run(db)
    _run(db)

    conn = duckdb.connect(str(db))
    assert "idx_master_obligation_scope" in _indexes(conn, "pengembalian_master_obligation")
    assert "idx_progress_tx_scope_stage" in _indexes(conn, "pengembalian_progress_transaction")
    assert conn.execute("SELECT obligation_id FROM pengembalian_master_obligation").fetchone()[0] == "O-1"
    conn.close()
