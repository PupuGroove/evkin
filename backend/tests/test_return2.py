"""
Tests for RETURN-2: dasar perhitungan and penyesuaian.
These are smoke/integration tests that require DuckDB available and migrations applied.
"""
import os
import uuid
import importlib.util
from pathlib import Path
from backend import pengembalian


def test_dasar_and_penyesuaian_smoke(tmp_path, monkeypatch):
    db_path = tmp_path / "return2.duckdb"
    monkeypatch.setenv("EVKIN_DUCKDB_PATH", str(db_path))
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    for filename in (
        "007_create_pengembalian_history.py",
        "009_create_dasar_perhitungan.py",
        "010_create_penyesuaian.py",
    ):
        spec = importlib.util.spec_from_file_location(filename, str(migrations / filename))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()

    # create a case
    case_id = pengembalian.create_case(nip='999999', tahun=2026, bulan=8, komponen='TUKIN', created_by='test')
    assert case_id.startswith('RET-')

    # insert dasar perhitungan batch
    rows = [
        {
            'case_id': case_id,
            'nip': '999999',
            'periode': '2026-08',
            'komponen': 'TUKIN',
            'nilai_awal': 3000000,
            'nilai_dasar': 2800000,
            'nilai_penyesuaian': -200000,
            'tukin_seharusnya': 2600000,
            'nominal_pengembalian': 400000,
            'calculation_version': 'v1'
        }
    ]
    res = pengembalian.insert_dasar_perhitungan_batch(rows, batch_meta={'calculation_version': 'v1'}, created_by='test')
    assert res.get('status') == 'ok'
    batch_id = res.get('batch_id')
    assert batch_id

    # read dasar by case
    dasar_rows = pengembalian.get_dasar_by_case(case_id)
    assert isinstance(dasar_rows, list)
    assert len(dasar_rows) >= 1

    # insert penyesuaian
    p_rows = [
        {
            'case_id': case_id,
            'nip': '999999',
            'periode': '2026-08',
            'komponen': 'TUKIN',
            'nominal_sebelum': 3000000,
            'nominal_setelah': 2800000,
            'selisih': -200000,
            'jenis_penyesuaian': 'ABSENSI',
            'alasan_penyesuaian': 'Koreksi absensi',
            'reference_id': str(uuid.uuid4())
        }
    ]
    pres = pengembalian.insert_penyesuaian(p_rows, created_by='test')
    assert pres.get('status') == 'ok'

    pen_rows = pengembalian.get_penyesuaian_by_case(case_id)
    assert isinstance(pen_rows, list)
    assert len(pen_rows) >= 1
