import sqlite3

import duckdb
import pytest

from backend import evkin_export_api as api


@pytest.fixture
def performance_db(tmp_path, monkeypatch):
    path = str(tmp_path / "performance.duckdb")
    monkeypatch.setattr(api, "DUCKDB_PATH", path)
    monkeypatch.setattr(api, "get_connection", lambda: sqlite3.connect(":memory:"))
    api.ensure_duckdb_master_schema()
    with duckdb.connect(path) as conn:
        conn.execute("""
            CREATE OR REPLACE TABLE hitung_harian AS
            SELECT i row_number, printf('N%06d', i % 1000) nip,
                   printf('Pegawai %06d', i % 1000) nama,
                   CASE WHEN i % 2=0 THEN 'Staf' ELSE 'Guru' END jabatan,
                   CASE WHEN i % 3=0 THEN '2026-08' ELSE '2026-09' END bulan,
                   DATE '2026-08-01' + CAST(i % 28 AS INTEGER) tanggal,
                   '07:30' jamMasuk,'16:00' jamPulang,'8h 30m' durasi,
                   'reguler' metode,'' jenis,
                   CASE WHEN i % 10=0 THEN 'Tidak Lengkap' ELSE 'Lengkap' END statusLengkap,
                   CAST(i % 4 AS DOUBLE) totalHarian,
                   repeat('large-detail-', 100) flags
            FROM range(10000) t(i)
        """)
    return path


def test_page_search_filter_sort_and_detail_are_server_side(performance_db):
    result = api.get_workflow_data(
        'daily_data', 1, 100, '2026-08', 'default', 50,
        'N000010', None, 'nip', 'desc', False,
    )
    assert result['page'] == 1 and result['page_size'] == 50
    assert result['total'] > 0
    assert len(result['rows']) <= 50
    assert all(row['bulan'] == '2026-08' for row in result['rows'])
    assert all('N000010' in row['nip'] for row in result['rows'])
    assert 'row_number' not in result['rows'][0]  # detail-only column
    row_id = result['rows'][0]['_row_id']
    detail = api.get_workflow_detail('daily_data', row_id)['row']
    assert detail['row_number'] >= 0
    assert detail['flags'].startswith('large-detail-')

    filtered = api.get_workflow_data(
        'daily_data', 1, 100, None, 'default', 25,
        None, 'statusLengkap:Tidak Lengkap', 'nip', 'asc', False,
    )
    assert len(filtered['rows']) == 25
    assert all(row['statusLengkap'] == 'Tidak Lengkap' for row in filtered['rows'])
    assert [row['nip'] for row in filtered['rows']] == sorted(row['nip'] for row in filtered['rows'])


def test_summary_matches_full_dataset_aggregation(performance_db):
    result = api.get_workflow_summary('daily_data', None, 'default')['summary']
    with duckdb.connect(performance_db) as conn:
        expected = conn.execute("""
            SELECT count(*),count(distinct nip),
                   count(*) FILTER (WHERE statusLengkap='Lengkap'),
                   count(*) FILTER (WHERE statusLengkap='Tidak Lengkap'),
                   sum(totalHarian) FROM hitung_harian
        """).fetchone()
    assert result['total'] == expected[0]
    assert result['distinct_sdm'] == expected[1]
    assert result['valid'] == expected[2]
    assert result['invalid'] == expected[3]
    assert result['total_potongan'] == expected[4]


def test_first_page_never_materializes_full_dataset(performance_db):
    result = api.get_workflow_data('daily_data', 1, 100, None, 'default')
    assert result['total'] == 10000
    assert len(result['rows']) == 100
    assert result['total_pages'] == 100
