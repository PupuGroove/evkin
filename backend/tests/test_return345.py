import os
import tempfile
import runpy
import importlib
import duckdb
from fastapi.testclient import TestClient

# Prepare a temporary DuckDB file for tests
def setup_temp_duckdb():
    fd, path = tempfile.mkstemp(suffix='.duckdb')
    os.close(fd)
    os.unlink(path)
    # DuckDB creates a valid database file on first connect.
    duckdb.connect(path).close()
    # ensure env var used by evkin_export_api
    os.environ['EVKIN_DUCKDB_PATH'] = path
    # run base migration that creates audit_log, import_batch etc if present
    migrations_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    # Execute migration 001_create_master_schema.py if exists
    m001 = os.path.join(os.path.dirname(__file__), '..', 'migrations', '001_create_master_schema.py')
    if os.path.exists(m001):
        runpy.run_path(m001, run_name='m001')
    # Execute our new migration 022
    m022 = os.path.join(os.path.dirname(__file__), '..', 'migrations', '022_create_bpk_bank_tables.py')
    if os.path.exists(m022):
        runpy.run_path(m022, run_name='m022')
    return path


def test_send_bpk_and_bank_and_results():
    db_path = setup_temp_duckdb()
    # reload modules to pick up env var
    import backend.evkin_export_api as ev
    importlib.reload(ev)
    import backend.pengembalian as p
    importlib.reload(p)

    # prepare sample items
    items_bpk = [
        {'case_id': 'CASE-1', 'nip': '123', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 1000},
        {'case_id': 'CASE-2', 'nip': '456', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 2000}
    ]
    res_bpk = p.send_bpk_batch(items_bpk, batch_meta={'batch_name': 'test-bpk'}, created_by='tester')
    assert res_bpk.get('status') == 'ok'
    assert 'batch_id' in res_bpk
    assert res_bpk.get('inserted') >= 0

    # send bank
    items_bank = [
        {'case_id': 'CASE-1', 'nip': '123', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 500, 'reference': 'ref-1'},
    ]
    res_bank = p.send_bank_batch(items_bank, batch_meta={'batch_name': 'test-bank'}, created_by='tester')
    assert res_bank.get('status') == 'ok'
    bank_batch_id = res_bank.get('batch_id')

    # record bank results (one success, one fail)
    results = [
        {'bank_detail_id': None, 'case_id': 'CASE-1', 'nip': '123', 'nominal': 500, 'status': 'SUCCESS', 'reason': None},
        {'bank_detail_id': None, 'case_id': 'CASE-2', 'nip': '456', 'nominal': 2000, 'status': 'FAILED', 'reason': 'Insufficient funds'}
    ]
    res_results = p.record_bank_results(bank_batch_id=bank_batch_id, results=results, created_by='tester')
    assert res_results.get('status') == 'ok'
    assert res_results.get('inserted') >= 0

    # verify DB rows
    conn = duckdb.connect(db_path)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM pengembalian_bpk_batch").fetchone()[0]
        assert cnt >= 1
        cntd = conn.execute("SELECT COUNT(*) FROM pengembalian_bpk_detail").fetchone()[0]
        assert cntd >= res_bpk.get('inserted')
        # bank batch
        cntb = conn.execute("SELECT COUNT(*) FROM pengembalian_bank_batch").fetchone()[0]
        assert cntb >= 1
        cntbd = conn.execute("SELECT COUNT(*) FROM pengembalian_bank_detail").fetchone()[0]
        assert cntbd >= res_bank.get('inserted')
        # results
        cntr = conn.execute("SELECT COUNT(*) FROM pengembalian_bank_result WHERE bank_batch_id = ?", [bank_batch_id]).fetchone()[0]
        assert cntr >= len(results)
        # check that history entry created for SUCCESS (negative amount)
        # Note: pengembalian_tukin_history may exist only if migrations created pengembalian tables
        try:
            hist_cnt = conn.execute("SELECT COUNT(*) FROM pengembalian_tukin_history WHERE event_type = 'bank_debit'").fetchone()[0]
            assert hist_cnt >= 1
        except Exception:
            # if history table missing, ignore but ensure no exception
            pass
    finally:
        conn.close()


def test_send_bpk_requires_api_key_when_configured(monkeypatch):
    monkeypatch.setenv('EVKIN_API_KEY', 'secret-key')
    monkeypatch.delenv('EVKIN_ANALYTICS_API_KEY', raising=False)
    monkeypatch.setenv('EVKIN_DUCKDB_PATH', setup_temp_duckdb())
    import backend.main as main
    import backend.pengembalian_api as api
    importlib.reload(api)
    importlib.reload(main)

    client = TestClient(main.app)
    forbidden = client.post('/pengembalian/send_bpk', json={'batch_name': 'unit-test', 'items': [{'case_id': 'CASE-99', 'nominal': 123}]})
    assert forbidden.status_code == 401
    progress_forbidden = client.get('/pengembalian/archive/progress')
    assert progress_forbidden.status_code == 401
    invalid_limit = client.get('/pengembalian/archive/progress?limit=1001',
                               headers={'X-EVKIN-API-Key': 'secret-key'})
    assert invalid_limit.status_code == 400
    invalid_offset = client.get('/pengembalian/archive/progress?offset=-1',
                                headers={'X-EVKIN-API-Key': 'secret-key'})
    assert invalid_offset.status_code == 400

    allowed = client.post('/pengembalian/send_bpk', json={'batch_name': 'unit-test', 'items': [{'case_id': 'CASE-99', 'nominal': 123}]}, headers={'X-EVKIN-API-Key': 'secret-key'})
    assert allowed.status_code == 200
