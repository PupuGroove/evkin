import duckdb
import pytest

from backend.module_reset import ModuleResetService
from backend.reset_service import RESET_PROFILES, ResetSpec


def service(tmp_path):
    path = tmp_path / 'modules.duckdb'
    with duckdb.connect(str(path)) as conn:
        for table in ('master_sdm', 'pengembalian_period', 'raw_import', 'hitung_harian',
                      'skp_assessment_monthly', 'final_tukin_results', 'tukin_period'):
            conn.execute(f'CREATE TABLE {table}(id INTEGER)')
            conn.execute(f'INSERT INTO {table} VALUES (1)')
    return ModuleResetService(path)


def test_module_reset_preserves_protected_tables(tmp_path):
    svc = service(tmp_path)
    preview = svc.preview_module('workflow')
    result = svc.reset_module_data('workflow', {
        'preview_token': preview['preview_token'], 'confirmation': preview['confirmation'],
    })
    assert result['deleted_rows'] == 2
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM raw_import').fetchone() == (0,)
        assert conn.execute('SELECT count(*) FROM hitung_harian').fetchone() == (0,)
        assert conn.execute('SELECT count(*) FROM master_sdm').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM pengembalian_period').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM application_reset_audit').fetchone() == (1,)


def test_protected_table_cannot_be_targeted(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setitem(RESET_PROFILES, 'unsafe', ResetSpec(
        'unsafe', ('master_sdm',), 'RESET UNSAFE', 'none'
    ))
    with pytest.raises(ValueError, match='protected'):
        svc.preview_module('unsafe')


def test_preview_and_execute_use_identical_targets(tmp_path):
    svc = service(tmp_path)
    preview = svc.preview_module('workflow')
    result = svc.reset_module_data('workflow', {
        'preview_token': preview['preview_token'], 'confirmation': preview['confirmation'],
    })
    assert result['target_tables'] == preview['target_tables']
    assert set(result['deleted']) == set(preview['target_tables'])
    assert result['deleted_rows'] == preview['deleted_rows']


def test_invalid_module_and_confirmation_are_rejected(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(ValueError, match='tidak dikenal'):
        svc.preview_module('unknown')
    preview = svc.preview_module('workflow')
    with pytest.raises(ValueError, match='Konfirmasi'):
        svc.reset_module_data('workflow', {
            'preview_token': preview['preview_token'], 'confirmation': 'SALAH',
        })


def test_module_reset_rolls_back_and_does_not_audit_failure(tmp_path, monkeypatch):
    svc = service(tmp_path)
    preview = svc.preview_module('workflow')
    original = svc._delete_table
    calls = 0
    def fail_second(conn, item):
        nonlocal calls
        calls += 1
        original(conn, item)
        if calls == 2:
            raise ValueError('Simulasi kegagalan reset')
    monkeypatch.setattr(svc, '_delete_table', fail_second)
    with pytest.raises(ValueError, match='Simulasi'):
        svc.reset_module_data('workflow', {
            'preview_token': preview['preview_token'], 'confirmation': preview['confirmation'],
        })
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM raw_import').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM hitung_harian').fetchone() == (1,)
        assert 'application_reset_audit' not in {
            row[0] for row in conn.execute('SHOW TABLES').fetchall()
        }
