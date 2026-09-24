import sqlite3
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import pytest
from fastapi import HTTPException
from backend import evkin_export_api as api


def setup_export(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'EXPORT_DIR', str(tmp_path))
    monkeypatch.setattr(api, 'get_connection', lambda: sqlite3.connect(':memory:'))
    monkeypatch.setattr(api, '_update_job', lambda *args, **kwargs: None)


def test_final_export_preserves_every_cell_beyond_ui_and_batch_limits(monkeypatch, tmp_path):
    setup_export(monkeypatch, tmp_path)
    rows = [{'nip': f'001234567890{i:06d}', 'nama': f'Pegawai {i}',
             'jabatan': 'Pendamping', 'bulan': '2026-09', 'tukin': 2000000 + i,
             'komponen': 600000, 'potPct': 10, 'nominal': 60000,
             'finalDibayar': 1940000 + i} for i in range(2005)]
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(api, 'read_workflow_table_duckdb', lambda *args: frame)
    path = api.run_export_job('complete', '2026-09', None, ['FINAL ABSENSI'])
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        strings = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        shared = [''.join(item.itertext()) for item in strings]
        xml = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        actual = []
        for row in xml.findall('x:sheetData/x:row', ns)[1:]:
            cells = row.findall('x:c', ns)
            assert len(cells) == len(frame.columns)
            values = []
            for cell in cells:
                value = cell.find('x:v', ns).text
                values.append(shared[int(value)] if cell.get('t') == 's' else float(value))
            actual.append(values)
    assert actual == frame.values.tolist()


def test_export_database_error_does_not_create_successful_empty_sheet(monkeypatch, tmp_path):
    setup_export(monkeypatch, tmp_path)
    def unavailable(*args):
        raise HTTPException(503, 'Database terkunci')
    monkeypatch.setattr(api, 'read_workflow_table_duckdb', unavailable)
    with pytest.raises(HTTPException):
        api.run_export_job('failed', '2026-09', None, ['FINAL ABSENSI'])
    assert not (tmp_path / 'failed.xlsx').exists()


def test_export_query_is_explicit_and_rejects_invalid_sources():
    query, params = api.build_export_query(
        'final_absensi', '2026-08', {'nip', 'bulan', 'unit'}, 'SDM', None
    )
    assert query == 'SELECT * FROM "final_absensi" WHERE "bulan" = ? AND "unit" = ?'
    assert params == ['2026-08', 'SDM']
    with pytest.raises(api.ExportValidationError, match='Unsupported export source'):
        api.build_export_query('final_tukin', '2026-08', {'nip'})
    with pytest.raises(api.ExportValidationError, match='Periode export tidak valid'):
        api.build_export_query('final_absensi', '', {'nip'})


def test_export_missing_source_returns_business_error_not_unbound_local(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'DUCKDB_PATH', str(tmp_path / 'missing.duckdb'))
    with pytest.raises(HTTPException) as error:
        api.read_workflow_table_duckdb('final_absensi', '2026-08')
    assert error.value.status_code == 404
    detail = error.value.detail
    assert isinstance(detail, dict)
    assert detail['code'] == 'EXPORT_SOURCE_NOT_FOUND'
    assert 'UnboundLocalError' not in str(detail)
