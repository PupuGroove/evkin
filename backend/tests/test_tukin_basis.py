"""Reference-output integration: participant scope, adjustments and Excel parity."""
import io
import zipfile
import xml.etree.ElementTree as ET

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import tukin_combined as combined
from backend.tests.test_skp_assessment import services, NIP


@pytest.fixture
def basis(tmp_path):
    master, skp, annual = services(tmp_path)
    with skp.connect():
        pass
    annual.ensure_period('2026-08', '2026-09', 'LIVE')
    with annual.connect() as conn:
        conn.execute('CREATE TABLE final_absensi (nip VARCHAR, bulan VARCHAR, potPct DOUBLE)')
        conn.execute('INSERT INTO final_absensi VALUES (?,?,20)', [NIP,'2026-08'])
        conn.execute('''INSERT INTO skp_assessment_monthly
            (assessment_period,nip,final_predicate,report_status,review_status)
            VALUES ('2026-08',?,'Kurang','SUBMITTED','APPROVED')''', [NIP])
    app = FastAPI()
    app.include_router(combined.create_router(lambda: master.db_path))
    return master.db_path, TestClient(app)


def preview(client, scope='workflow'):
    response = client.get('/api/tukin/combined', params={'assessment_period':'2026-08','scope':scope})
    assert response.status_code == 200, response.text
    return response.json()


def payload(client, **changes):
    row = preview(client)['rows'][0]
    return {'assessment_period':'2026-08','nip':NIP,'amount':100000,
            'actor':'Petugas Uji','reason':'Koreksi sesuai dokumen uji 01',
            'expected':row['edit_token'], **changes}


def test_adjustment_persists_audit_and_preserves_source(basis):
    path, client = basis
    original = preview(client)['rows'][0]
    assert original['skp_deduction'] == 700000
    assert original['attendance_deduction'] == 600000
    assert original['final_tukin'] == 8700000
    request = payload(client)
    response = client.post('/api/tukin/combined/adjustment', json=request)
    assert response.status_code == 200, response.text
    saved = preview(client)['rows'][0]
    assert saved['final_tukin'] == 8800000
    assert saved['calculated_entitlement'] == 8700000
    assert saved['adjustment_actor'] == request['actor']
    assert client.post('/api/tukin/combined/adjustment', json=request).status_code == 400
    audit = client.get('/api/tukin/combined/adjustment/audit', params={'assessment_period':'2026-08','nip':NIP}).json()['rows']
    assert len(audit) == 1
    assert audit[0]['old_value'] is None
    assert audit[0]['new_value']['amount'] == 100000
    with duckdb.connect(path) as conn:
        assert conn.execute('SELECT potPct FROM final_absensi').fetchone()[0] == 20
        assert conn.execute('SELECT final_predicate FROM skp_assessment_monthly').fetchone()[0] == 'Kurang'
        assert conn.execute('SELECT count(*) FROM tukin_final_monthly').fetchone()[0] == 0


def test_changed_sources_hold_adjustment_until_review_and_zero_cancels(basis):
    path, client = basis
    assert client.post('/api/tukin/combined/adjustment', json=payload(client)).status_code == 200
    with duckdb.connect(path) as conn:
        conn.execute('UPDATE final_absensi SET potPct=10')
    changed = preview(client)['rows'][0]
    assert changed['adjustment_stale'] is True
    assert changed['final_tukin'] is None
    assert changed['payable_estimate'] == 9000000
    assert client.post('/api/tukin/combined/adjustment', json=payload(client,amount=0,reason='Batalkan koreksi lama')).status_code == 200
    with duckdb.connect(path) as conn:
        conn.execute('UPDATE final_absensi SET potPct=5')
    reset = preview(client)['rows'][0]
    assert reset['adjustment_stale'] is False
    assert reset['final_tukin'] == 9150000
    audit = client.get('/api/tukin/combined/adjustment/audit', params={'assessment_period':'2026-08','nip':NIP}).json()['rows']
    assert audit[0]['old_value']['amount'] == 100000
    assert audit[0]['new_value']['amount'] == 0


@pytest.mark.parametrize('changes', [
    {'amount':1300001}, {'amount':-8700001}, {'amount':'NaN'}, {'amount':'Infinity'},
    {'amount':'Rp 1.000'}, {'amount':'1.5'}, {'amount':None}, {'reason':'   '}, {'actor':''},
])
def test_invalid_adjustment_never_writes(basis, changes):
    path, client = basis
    response = client.post('/api/tukin/combined/adjustment', json=payload(client,**changes))
    assert response.status_code == 400
    with duckdb.connect(path) as conn:
        combined.ensure_adjustment_schema(conn)
        assert conn.execute('SELECT count(*) FROM tukin_combined_adjustment').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM tukin_combined_adjustment_audit').fetchone()[0] == 0


@pytest.mark.parametrize('state', ['LOCKED','HISTORICAL_LOCKED','PAID'])
def test_locked_period_rejects_edits(basis, state):
    path, client = basis
    with duckdb.connect(path) as conn:
        conn.execute('UPDATE tukin_period SET status=?', [state])
    assert preview(client)['rows'][0]['period_locked'] is True
    result = client.post('/api/tukin/combined/adjustment', json=payload(client))
    assert result.status_code == 400
    assert 'terkunci' in result.json()['detail']


def test_missing_skp_is_not_zero_or_adjustable(basis):
    path, client = basis
    with duckdb.connect(path) as conn:
        conn.execute("UPDATE skp_assessment_monthly SET review_status='PENDING_REVIEW'")
    row = preview(client)['rows'][0]
    assert row['attendance_participant'] is True
    assert row['skp_deduction'] is None
    assert row['final_tukin'] is None
    assert client.post('/api/tukin/combined/adjustment', json=payload(client)).status_code == 400


def test_cancellation_does_not_make_incomplete_data_payable(basis):
    path, client = basis
    assert client.post('/api/tukin/combined/adjustment', json=payload(client)).status_code == 200
    with duckdb.connect(path) as conn:
        conn.execute("UPDATE skp_assessment_monthly SET review_status='PENDING_REVIEW'")
    assert client.post('/api/tukin/combined/adjustment', json=payload(client,amount=0,reason='Batalkan saat review SKP')).status_code == 200
    row = preview(client)['rows'][0]
    assert row['final_tukin'] is None
    assert row['manual_adjustment'] == 0
    assert row['adjustment_stale'] is False


def test_paid_row_rejects_adjustment_even_when_period_open(basis):
    path, client = basis
    with duckdb.connect(path) as conn:
        conn.execute('''INSERT INTO tukin_final_monthly (assessment_period,payment_period,nip,payment_status)
            VALUES ('2026-08','2026-09',?,'PAID')''',[NIP])
    assert preview(client)['rows'][0]['period_locked'] is True
    assert client.post('/api/tukin/combined/adjustment',json=payload(client)).status_code == 400


def test_scope_keeps_unmatched_imports_and_separates_archived_participants(basis):
    path, client = basis
    with duckdb.connect(path) as conn:
        conn.execute("INSERT INTO final_absensi VALUES ('UNMATCHED','2026-08',0),('OTHER_MONTH','2026-07',0)")
        conn.execute('''INSERT INTO tukin_final_monthly (assessment_period,payment_period,nip,attendance_reduction_rate)
            VALUES ('2026-08','2026-09','ARCHIVE',10)''')
    live = preview(client)
    assert {r['nip'] for r in live['rows']} == {NIP,'UNMATCHED'}
    assert next(r for r in live['rows'] if r['nip']=='UNMATCHED')['final_tukin'] is None
    history = preview(client,'attendance')
    assert {r['nip'] for r in history['rows']} == {NIP,'UNMATCHED','ARCHIVE'}
    assert client.get('/api/tukin/combined',params={'assessment_period':'2026-08','scope':'invalid'}).status_code == 400


def test_explicit_unpaid_is_zero_and_hold_is_blank():
    from backend.tests.test_tukin_combined import inputs
    master, attendance, skp = inputs()
    for effect, expected in [('UNPAID',0),('HOLD',None)]:
        row = combined.combine(master,attendance,skp,[],'2026-08',[
            {'nip':'001','status':'APPROVED','payment_effect':effect,'reason':'Dokumen uji'}])[0]
        combined.apply_adjustment(row)
        assert row['final_tukin'] == expected
        assert row['payable_estimate'] is None


def test_export_matches_adjusted_preview_and_rejects_stale_snapshot(basis):
    _, client = basis
    before = preview(client)
    assert client.post('/api/tukin/combined/adjustment',json=payload(client,amount=-100000)).status_code == 200
    params = {'assessment_period':'2026-08','scope':'workflow','expected':before['fingerprint']}
    assert client.get('/api/tukin/combined/export',params=params).status_code == 409
    after = preview(client)
    params['expected'] = after['fingerprint']
    response = client.get('/api/tukin/combined/export',params=params)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        assert len(sheet.findall('x:sheetData/x:row',ns)) == 2
        assert sheet.find(".//x:c[@r='Y2']/x:v",ns).text == '8600000'
        assert sheet.find(".//x:c[@r='V2']/x:v",ns).text == '-100000'
        assert not sheet.findall('.//x:f',ns)
