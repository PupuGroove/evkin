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
