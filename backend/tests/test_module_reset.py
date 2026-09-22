import duckdb
import pytest

from backend.module_reset import ModuleResetService, MODULE_TABLES


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
    result = svc.reset_module_data('workflow')
    assert result['deleted_rows'] == 2
    with duckdb.connect(str(svc.db_path)) as conn:
        assert conn.execute('SELECT count(*) FROM raw_import').fetchone() == (0,)
        assert conn.execute('SELECT count(*) FROM hitung_harian').fetchone() == (0,)
        assert conn.execute('SELECT count(*) FROM master_sdm').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM pengembalian_period').fetchone() == (1,)


def test_protected_table_cannot_be_targeted(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setitem(MODULE_TABLES, 'unsafe', frozenset({'master_sdm'}))
    with pytest.raises(ValueError, match='protected'):
        svc.reset_module_data('unsafe')