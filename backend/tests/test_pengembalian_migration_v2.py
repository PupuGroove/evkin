import importlib.util
from pathlib import Path

import duckdb


def _run(path, module_name, db_path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(str(db_path))


def test_dependency_safe_extension_preserves_rows_and_aliases(tmp_path):
    migrations = Path(__file__).parents[1] / "migrations"
    db_path = tmp_path / "dependency.duckdb"
    _run(migrations / "023_create_pengembalian_archive_compare.py", "m023", db_path)
    conn = duckdb.connect(str(db_path))
    conn.execute("INSERT INTO pengembalian_archive_import(import_id,source_type) VALUES ('i1','DATA_AWAL')")
    conn.execute("""INSERT INTO pengembalian_archive_data_awal
        (row_id,import_id,source_type,nip,raw_data) VALUES ('r1','i1','DATA_AWAL','42','{}')""")
    conn.close()

    _run(migrations / "026_extend_pengembalian_bnba_schema.py", "m026", db_path)
    _run(migrations / "026_extend_pengembalian_bnba_schema.py", "m026_again", db_path)

    conn = duckdb.connect(str(db_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_archive_data_awal").fetchone()[0] == 1
        assert conn.execute("SELECT nip FROM data_awal").fetchone()[0] == "42"
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info('pengembalian_archive_data_awal')"
        ).fetchall()}
        assert {"final_total_pengembalian_tukin", "bnba_normalized"} <= columns
    finally:
        conn.close()
