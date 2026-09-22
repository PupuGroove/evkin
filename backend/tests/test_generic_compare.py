"""
Minimal tests for generic compare (RETURN: non-destructive). These are skeleton tests — they assume the migrations ran and test DB is accessible.
"""
import os
import duckdb
import json
from backend.generic_compare import run_generic_compare


def test_generic_compare_smoke(tmp_path):
    # This test is a smoke test and will create two temp tables and run a compare
    db_path = os.environ.get('DUCKDB_PATH')
    if not db_path:
        # skip if no db configured in env for tests run in CI
        return
    conn = duckdb.connect(db_path)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS gc_test_a (nip TEXT, periode TEXT, komponen TEXT, nominal INTEGER)')
        conn.execute('CREATE TABLE IF NOT EXISTS gc_test_b (nip TEXT, periode TEXT, komponen TEXT, nominal INTEGER)')
        conn.execute("INSERT INTO gc_test_a VALUES ('100','2025-01','TUKIN', 1000), ('200','2025-01','TUKIN', 1500)")
        conn.execute("INSERT INTO gc_test_b VALUES ('100','2025-01','TUKIN', 1000), ('300','2025-01','TUKIN', 2000)")

        summary = run_generic_compare('smoke-test', 'gc_test_a', 'gc_test_b', ['nip','periode','komponen'], ['nominal'], created_by='test')
        assert 'run_id' in summary
        assert summary['total_a'] == 2
        assert summary['total_b'] == 2
    finally:
        conn.close()
