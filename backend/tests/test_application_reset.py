import json
import sqlite3
from pathlib import Path

import duckdb
import pytest

from backend.application_reset import ApplicationResetService, CONFIRMATION


def service(tmp_path):
    path = tmp_path / 'app.duckdb'
    with duckdb.connect(str(path)) as conn:
        for name in ('sdm_master', 'sdm_bank_history', 'sdm_death_record', 'master_data',
                     'skp_rule_config', 'raw_import', 'skp_assessment_monthly',
                     'tukin_final_monthly', 'pengembalian_monthly_master', 'workflow_config'):
            conn.execute(f'CREATE TABLE {name}(id INTEGER, value VARCHAR)')
            conn.execute(f"INSERT INTO {name} VALUES (1,'original')")
    return ApplicationResetService(path)


def confirmation(svc):
    return {'confirmation': CONFIRMATION, 'actor': 'Petugas', 'reason': 'Uji reset',
            'preview_token': svc.preview()['preview_token']}


def test_reset_preserves_master_and_verified_backup(tmp_path):
    svc = service(tmp_path)
    result = svc.confirm(confirmation(svc))
    assert result['deleted_rows'] == 5
    with duckdb.connect(str(svc.db_path)) as conn:
        for table in ('sdm_master','sdm_bank_history','sdm_death_record','master_data','skp_rule_config'):
            assert conn.execute(f'SELECT * FROM {table}').fetchall() == [(1, 'original')]
        for table in ('raw_import','skp_assessment_monthly','tukin_final_monthly','pengembalian_monthly_master','workflow_config'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,)
        assert conn.execute('SELECT actor,reason FROM application_reset_audit').fetchone() == ('Petugas','Uji reset')
    backup = Path(result['backup_path'])
    with duckdb.connect(str(backup / 'app.duckdb'), read_only=True) as conn:
        assert conn.execute('SELECT * FROM raw_import').fetchall() == [(1,'original')]
    assert json.loads((backup / 'manifest.json').read_text())['state'] == 'BACKUP_VERIFIED'


@pytest.mark.parametrize('field,value', [('actor',''), ('reason',''), ('confirmation','RESET'), ('preview_token','stale')])
def test_requires_confirmation(tmp_path, field, value):
    svc = service(tmp_path)
    payload = confirmation(svc)
    payload[field] = value
    with pytest.raises(ValueError):
        svc.confirm(payload)
    assert not (tmp_path / 'reset-backups').exists()


def test_same_count_changed_content_invalidates_preview(tmp_path):
    svc = service(tmp_path)
    payload = confirmation(svc)
    with duckdb.connect(str(svc.db_path)) as conn:
        conn.execute("UPDATE raw_import SET value='changed'")
    with pytest.raises(ValueError, match='Data berubah'):
        svc.confirm(payload)


@pytest.mark.parametrize('status', ['LOCKED','PAID','HISTORICAL_LOCKED','CLOSED','ARCHIVED'])
def test_locked_period_cannot_be_reset(tmp_path, status):
    svc = service(tmp_path)
    with duckdb.connect(str(svc.db_path)) as conn:
        conn.execute('CREATE TABLE tukin_period(status VARCHAR)')
        conn.execute('INSERT INTO tukin_period VALUES (?)',[status])
    assert svc.preview()['can_reset'] is False
    with pytest.raises(ValueError, match='terkunci/sudah dibayar'):
        svc.confirm(confirmation(svc))


def test_backup_failure_does_not_delete(tmp_path, monkeypatch):
    svc = service(tmp_path)
    def fail(*args):
        raise OSError('Disk penuh')
    monkeypatch.setattr(svc, '_backup', fail)
    with pytest.raises(OSError):
        svc.confirm(confirmation(svc))
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM raw_import').fetchone() == (1,)


def test_unknown_populated_table_blocks_reset(tmp_path):
    svc = service(tmp_path)
    with duckdb.connect(str(svc.db_path)) as conn:
        conn.execute('CREATE TABLE unknown_data AS SELECT 1 id')
    assert svc.preview()['can_reset'] is False


def test_running_jobs_block_reset(tmp_path):
    svc = service(tmp_path)
    svc.jobs_path = tmp_path / 'jobs.db'
    with sqlite3.connect(svc.jobs_path) as conn:
        conn.execute('CREATE TABLE jobs(status TEXT)')
        conn.execute("INSERT INTO jobs VALUES ('running')")
    assert svc.preview()['can_reset'] is False


def test_repeated_reset_keeps_audit(tmp_path):
    svc = service(tmp_path)
    svc.confirm(confirmation(svc))
    svc.confirm(confirmation(svc))
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM application_reset_audit').fetchone() == (2,)


def test_delete_failure_rolls_back_all_tables(tmp_path, monkeypatch):
    svc = service(tmp_path)
    original = svc._delete_table
    def fail_after_delete(conn, item):
        original(conn, item)
        if item['table'] == 'tukin_final_monthly':
            raise ValueError('Simulasi kegagalan setelah DELETE')
    monkeypatch.setattr(svc, '_delete_table', fail_after_delete)
    with pytest.raises(ValueError, match='Simulasi'):
        svc.confirm(confirmation(svc))
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM raw_import').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM skp_assessment_monthly').fetchone() == (1,)


def test_duplicate_rows_changed_invalidate_preview(tmp_path):
    svc = service(tmp_path)
    with duckdb.connect(str(svc.db_path)) as conn:
        conn.execute("INSERT INTO raw_import VALUES (1,'original')")
    payload = confirmation(svc)
    with duckdb.connect(str(svc.db_path)) as conn:
        conn.execute("UPDATE raw_import SET value='changed'")
    with pytest.raises(ValueError, match='Data berubah'):
        svc.confirm(payload)


def test_api_preview_and_confirmation(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.application_reset import create_router
    svc = service(tmp_path)
    app = FastAPI()
    app.include_router(create_router(lambda: str(svc.db_path), lambda: None))
    client = TestClient(app)
    assert client.get('/api/admin/reset-operational/preview').json()['can_reset'] is True
    assert client.post('/api/admin/reset-operational/confirm', json={}).status_code == 400
    assert client.post('/api/admin/reset-operational/confirm', json=confirmation(svc)).status_code == 200


def test_reset_gate_rejects_other_writes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import runtime_guard
    app = FastAPI()
    app.middleware('http')(runtime_guard.serialize_database_requests)
    @app.post('/api/jobs/export')
    def write():
        return {'unexpected': True}
    monkeypatch.setattr(runtime_guard, '_reset_in_progress', True)
    assert TestClient(app).post('/api/jobs/export').status_code == 409
