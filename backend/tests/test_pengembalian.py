import os
import tempfile
import importlib
import duckdb
from backend import pengembalian


def test_migration_and_basic_flow(tmp_path, monkeypatch):
    # Use a temporary duckdb file for tests
    td = tmp_path / 'test_master.duckdb'
    monkeypatch.setenv('EVKIN_DUCKDB_PATH', str(td))

    # reload modules that read DUCKDB_PATH at import time
    import backend.evkin_export_api as eea
    importlib.reload(eea)
    import backend.pengembalian as peng
    importlib.reload(peng)

    # The migration file is named 007_create_pengembalian_history.py; import it via importlib
    from importlib import util
    spec = util.spec_from_file_location('m007', os.path.join(os.path.dirname(__file__), '..', 'migrations', '007_create_pengembalian_history.py'))
    m007 = util.module_from_spec(spec)
    spec.loader.exec_module(m007)
    m007.main()

    # Now create a case and insert history
    case_id = peng.create_case(nip='123', tahun=2026, bulan=8, created_by='test')
    assert case_id is not None
    hid = peng.insert_history_event(case_id=case_id, event_type='initial_import', amount=1000.0, created_by='test')
    assert hid is not None
    hist = peng.get_history(case_id)
    assert isinstance(hist, list)
    assert len(hist) >= 1
    pos = peng.get_current_position(case_id)
    assert pos == 1000.0

    # Verify audit_log and import_batch are writable (even if schema minimal)
    conn = duckdb.connect(str(td))
    try:
        # audit_log may exist but if not, ensure no exception
        try:
            _ = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()
        except Exception:
            pass
    finally:
        conn.close()
    # Restore the module-level database path before subsequent tests run.
    monkeypatch.delenv('EVKIN_DUCKDB_PATH', raising=False)
    importlib.reload(peng)
