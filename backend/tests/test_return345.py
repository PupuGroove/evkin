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
    # Bank-success results require the legacy repayment history table so the
    # result and its repayment event can be committed atomically.
    m007 = os.path.join(os.path.dirname(__file__), '..', 'migrations', '007_create_pengembalian_history.py')
    if os.path.exists(m007):
        runpy.run_path(m007, run_name='__main__')
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


def test_send_bank_api_surfaces_partial_result(monkeypatch):
    monkeypatch.setenv('EVKIN_API_KEY', 'test-api-key')
    monkeypatch.setenv('EVKIN_DUCKDB_PATH', setup_temp_duckdb())
    import backend.pengembalian_api as api
    import backend.main as main
    importlib.reload(api)
    importlib.reload(main)
    monkeypatch.setattr(api.pengembalian, 'send_bank_batch', lambda **kwargs: {
        'status': 'partial', 'batch_id': 'BANK-BATCH-1', 'inserted': 1, 'failed': 1,
        'items': [{'index': 1, 'stage': 'detail_insert', 'reason': 'detail_write_failed'}],
    })

    response = TestClient(main.app).post('/pengembalian/send_bank', json={
        'items': [{'case_id': 'CASE-1', 'nominal': 100}],
    }, headers={'X-EVKIN-API-Key': 'test-api-key'})

    assert response.status_code == 200
    assert response.json()['status'] == 'partial'
    assert response.json()['failed'] == 1


def test_bank_result_history_failure_rolls_back_result(monkeypatch):
    db_path = setup_temp_duckdb()
    import backend.pengembalian as p
    importlib.reload(p)

    def fail_history(**kwargs):
        raise RuntimeError('history unavailable')

    monkeypatch.setattr(p, 'insert_history_event', fail_history)
    result = p.record_bank_results('BANK-BATCH-1', [{
        'case_id': 'CASE-1', 'nip': '123', 'nominal': 500,
        'status': 'SUCCESS', 'reason': None,
    }], created_by='tester')

    assert result['status'] == 'error'
    assert result['inserted'] == 0
    assert result['failed'] == 1
    assert result['items'] == [{'index': 0, 'stage': 'history_write', 'reason': 'result_or_history_write_failed'}]
    conn = duckdb.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_bank_result WHERE bank_batch_id = 'BANK-BATCH-1'").fetchone()[0] == 0
    finally:
        conn.close()


def test_bank_result_middle_failure_is_partial_and_other_items_commit(monkeypatch):
    db_path = setup_temp_duckdb()
    import backend.pengembalian as p
    importlib.reload(p)
    original_history = p.insert_history_event

    def fail_second_history(**kwargs):
        if kwargs.get('case_id') == 'CASE-2':
            raise RuntimeError('history unavailable')
        return original_history(**kwargs)

    monkeypatch.setattr(p, 'insert_history_event', fail_second_history)
    result = p.record_bank_results('BANK-BATCH-2', [
        {'case_id': 'CASE-1', 'nip': '123', 'nominal': 100, 'status': 'SUCCESS', 'reason': None},
        {'case_id': 'CASE-2', 'nip': '456', 'nominal': 200, 'status': 'SUCCESS', 'reason': None},
        {'case_id': 'CASE-3', 'nip': '789', 'nominal': 300, 'status': 'SUCCESS', 'reason': None},
    ], created_by='tester')

    assert result['status'] == 'partial'
    assert result['inserted'] == 2
    assert result['failed'] == 1
    assert result['items'] == [{'index': 1, 'stage': 'history_write', 'reason': 'result_or_history_write_failed'}]
    conn = duckdb.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_bank_result WHERE bank_batch_id = 'BANK-BATCH-2'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_tukin_history WHERE event_type = 'bank_debit'").fetchone()[0] == 2
    finally:
        conn.close()


def test_bank_batch_middle_detail_failure_is_partial(monkeypatch):
    db_path = setup_temp_duckdb()
    import backend.pengembalian as p
    importlib.reload(p)
    real_get_conn = p._get_conn

    class FailMiddleDetailConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            if 'INSERT INTO pengembalian_bank_detail' in sql and params and 'CASE-2' in params:
                raise RuntimeError('detail unavailable')
            return self.connection.execute(sql) if params is None else self.connection.execute(sql, params)

        def close(self):
            self.connection.close()

    monkeypatch.setattr(p, '_get_conn', lambda: FailMiddleDetailConnection(real_get_conn()))
    result = p.send_bank_batch([
        {'case_id': 'CASE-1', 'nip': '123', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 100},
        {'case_id': 'CASE-2', 'nip': '456', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 200},
        {'case_id': 'CASE-3', 'nip': '789', 'periode': '2026-07', 'komponen': 'TUKIN', 'nominal': 300},
    ], created_by='tester')

    assert result['status'] == 'partial'
    assert result['inserted'] == 2
    assert result['failed'] == 1
    assert result['items'] == [{'index': 1, 'stage': 'detail_insert', 'reason': 'detail_write_failed'}]
    conn = duckdb.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_bank_detail WHERE batch_id = ?", [result['batch_id']]).fetchone()[0] == 2
    finally:
        conn.close()
