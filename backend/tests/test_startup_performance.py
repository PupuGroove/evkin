from __future__ import annotations

import duckdb
import sqlite3

from backend import evkin_export_api as api
from backend.final_tukin import migrate as migrate_final_tukin
from backend.lazy_imports import LazyModule


def test_pandas_dependency_is_lazy_but_transparent():
    assert isinstance(api.pd, LazyModule)
    frame = api.pd.DataFrame([{"nip": "1"}])
    assert frame.to_dict(orient="records") == [{"nip": "1"}]


def test_startup_schema_fast_path_detects_current_and_incomplete_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "startup.duckdb"
    monkeypatch.setattr(api, "DUCKDB_PATH", str(db_path))

    assert api.startup_schema_is_current() is False
    api.ensure_duckdb_master_schema()
    migrate_final_tukin(db_path)
    assert api.startup_schema_is_current() is True

    with duckdb.connect(str(db_path)) as conn:
        conn.execute("DROP INDEX idx_tukin_final_period")
    assert api.startup_schema_is_current() is False


def test_current_schema_startup_does_not_mutate_idle_data(tmp_path, monkeypatch):
    duckdb_path = tmp_path / "startup.duckdb"
    sqlite_path = tmp_path / "jobs.sqlite"
    monkeypatch.setattr(api, "DUCKDB_PATH", str(duckdb_path))
    monkeypatch.setattr(api, "DB_PATH", str(sqlite_path))
    api.ensure_duckdb_master_schema()
    migrate_final_tukin(duckdb_path)
    with duckdb.connect(str(duckdb_path)) as conn:
        conn.execute("INSERT INTO master_data VALUES ('keep')")
        before = conn.execute("SELECT * FROM master_data ORDER BY 1").fetchall()
    with sqlite3.connect(sqlite_path) as conn:
        api.ensure_jobs_table(conn)
        conn.execute(
            "INSERT INTO jobs(id,status,message) VALUES ('done','completed','unchanged')"
        )
        conn.commit()

    api.startup_bootstrap()

    with duckdb.connect(str(duckdb_path), read_only=True) as conn:
        assert conn.execute("SELECT * FROM master_data ORDER BY 1").fetchall() == before
    with sqlite3.connect(sqlite_path) as conn:
        assert conn.execute(
            "SELECT status,message FROM jobs WHERE id='done'"
        ).fetchone() == ('completed', 'unchanged')
