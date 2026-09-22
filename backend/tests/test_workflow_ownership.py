import json
import sqlite3

import duckdb
import pytest
from fastapi import HTTPException
from backend import evkin_export_api as api


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = str(tmp_path / 'ownership.duckdb')
    monkeypatch.setattr(api, 'DUCKDB_PATH', path)
    monkeypatch.setattr(api, 'get_connection', lambda: sqlite3.connect(':memory:'))
    api.ensure_duckdb_master_schema()
    with duckdb.connect(path) as conn:
        conn.execute("CREATE OR REPLACE TABLE master_data AS SELECT 'MASTER' nip, 2000000 tukin")
        conn.execute("CREATE TABLE sdm_master AS SELECT 'MASTER' nip")
        conn.execute("CREATE TABLE tukin_final_monthly AS SELECT 'ARCHIVE' nip")
        conn.execute("CREATE OR REPLACE TABLE raw_import AS SELECT 'PARTICIPANT' nip")
    return path


def test_partial_final_sync_preserves_master_sources_and_archive(isolated):
    api.sync_workflow({'final_absensi': [{'nip': 'PARTICIPANT', 'tukin': 2000000}]})
    with duckdb.connect(isolated) as conn:
        for table, nip in [('master_data', 'MASTER'), ('sdm_master', 'MASTER'),
                           ('raw_import', 'PARTICIPANT'), ('tukin_final_monthly', 'ARCHIVE')]:
            assert conn.execute(f'SELECT nip FROM {table}').fetchall() == [(nip,)]
        assert conn.execute('SELECT nip FROM final_absensi').fetchall() == [('PARTICIPANT',)]


def test_configuration_nested_values_and_workflow_records_roundtrip(isolated):
    record = {'nip':'001234567890123456', 'tanggal':{'monthKey':'2026-08'}, 'deleted':True}
    api.sync_workflow({'config':{'leavePeriods':[{'nip':'001'}], 'jamDasar':{'senKam':{'masuk':'08:00'}},
                                '_workflow':{'month':'2026-08'}},
                       'processed_data':[{'record':json.dumps(record)}],
                       'daily_data':[{'nip':'001','flags':['Tidak lengkap']}]})
    result = api.get_workflow_state()['data']
    assert result['config']['jamDasar']['senKam']['masuk']=='08:00'
    assert result['config']['leavePeriods'][0]['nip']=='001'
    assert result['daily_data'][0]['flags']==['Tidak lengkap']
    assert json.loads(result['processed_data'][0]['record'])==record


@pytest.mark.parametrize('source', ['master_data', 'sdm_master', 'tukin_final_monthly'])
def test_workflow_rejects_writes_to_other_owners(isolated, source):
    with pytest.raises(HTTPException):
        api.sync_workflow({source: []})
    with pytest.raises(HTTPException):
        api.sync_workflow_table({'source': source, 'rows': [], 'replace': True})


def test_config_is_identical_for_bulk_and_chunked_routes_without_master_cache(isolated):
    config = {'masterPegawai': [{'nip': 'STALE'}], 'minDurasiJam': 7.5}
    api.sync_workflow({'config': json.dumps(config)})
    assert api.get_workflow_state()['data']['config'] == {'minDurasiJam': 7.5}
    api.sync_workflow_table({'source': 'config', 'rows': [json.dumps(config)], 'replace': True})
    state = api.get_workflow_state()['data']
    assert state['config'] == {'minDurasiJam': 7.5}
    assert 'master_data' not in state


def test_bulk_failure_rolls_back_previous_tables(isolated, monkeypatch):
    original = api.prepare_database_frame
    def fail_second(frame):
        if 'fail' in frame.columns:
            raise ValueError('Simulated failure')
        return original(frame)
    monkeypatch.setattr(api, 'prepare_database_frame', fail_second)
    with pytest.raises(ValueError):
        api.sync_workflow({'raw_import': [{'nip': 'NEW'}], 'final_absensi': [{'fail': True}]})
    with duckdb.connect(isolated) as conn:
        assert conn.execute('SELECT nip FROM raw_import').fetchall() == [('PARTICIPANT',)]


def test_chunk_failure_preserves_original_table(isolated, monkeypatch):
    def fail(frame):
        raise ValueError('Simulated failure')
    monkeypatch.setattr(api, 'prepare_database_frame', fail)
    with pytest.raises(ValueError):
        api.sync_workflow_table({'source': 'raw_import', 'rows': [{'nip': 'NEW'}], 'replace': True})
    with duckdb.connect(isolated) as conn:
        assert conn.execute('SELECT nip FROM raw_import').fetchall() == [('PARTICIPANT',)]


def test_delete_absensi_requires_confirmation_and_preserves_other_owners(isolated):
    with pytest.raises(HTTPException):
        api.delete_absensi_workflow({})
    with duckdb.connect(isolated) as conn:
        assert conn.execute('SELECT COUNT(*) FROM raw_import').fetchone()[0] == 1
        for table in api.WORKFLOW_WRITABLE.values():
            conn.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT \'WORKFLOW\' nip')
        for table in ['skp_assessments', 'pengembalian_archive']:
            conn.execute(f'CREATE TABLE "{table}" AS SELECT \'PRESERVE\' nip')
    result = api.delete_absensi_workflow({'confirmation': 'HAPUS ABSENSI'})
    assert result['deleted_rows'] == len(set(api.WORKFLOW_WRITABLE.values()))
    with duckdb.connect(isolated) as conn:
        for table in api.WORKFLOW_WRITABLE.values():
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
        for table in ['master_data', 'sdm_master', 'tukin_final_monthly', 'skp_assessments', 'pengembalian_archive']:
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1
    assert api.delete_absensi_workflow({'confirmation': 'HAPUS ABSENSI'})['deleted_rows'] == 0


def test_delete_absensi_rolls_back_all_tables_on_failure(isolated, monkeypatch):
    # A view cannot be deleted from; use it to force a failure after raw_import was cleared.
    with duckdb.connect(isolated) as conn:
        conn.execute('CREATE VIEW failing_delete AS SELECT 1 AS value')
    monkeypatch.setattr(api, 'WORKFLOW_WRITABLE', {'raw_import': 'raw_import', 'fail': 'failing_delete'})
    with pytest.raises(duckdb.Error):
        api.delete_absensi_workflow({'confirmation': 'HAPUS ABSENSI'})
    with duckdb.connect(isolated) as conn:
        assert conn.execute('SELECT COUNT(*) FROM raw_import').fetchone()[0] == 1
