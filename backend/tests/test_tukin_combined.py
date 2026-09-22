import pytest
from backend.tukin_combined import combine, build
from backend.tests.test_skp_assessment import services, NIP


def inputs():
    return ({'001':{'nama':'Canonical', 'tukin_gross':5000000, 'eligible':True},
             '002':{'nama':'Outside workflow', 'tukin_gross':2000000, 'eligible':True}},
            [{'nip':'001', 'potPct':20, 'nominal':1}],
            [{'nip':'001', 'final_predicate':'Kurang', 'report_status':'SUBMITTED', 'review_status':'APPROVED'}])


def test_all_master_visible_and_weighted_once():
    master, attendance, skp = inputs()
    rows = combine(master,attendance,skp,[], '2026-08')
    assert len(rows)==2
    assert rows[0]['skp_deduction']==350000
    assert rows[0]['attendance_deduction']==300000
    assert rows[0]['payable_estimate']==4350000
    assert rows[1]['attendance_deduction'] is None
    assert rows[1]['payable_estimate'] is None


def test_gross_falls_back_to_period_source_when_master_profile_is_missing():
    master, attendance, skp = inputs()
    master['001']['tukin_gross'] = None
    attendance[0]['tukin_gross'] = 5_000_000
    row = combine(master, attendance, skp, [], '2026-08')[0]
    assert row['tukin_gross'] == 5_000_000
    assert row['tukin_gross_source'] == 'FINAL/HISTORI'
    assert row['calculated_entitlement'] == 4_350_000


def test_missing_master_unapproved_and_duplicates_never_payable():
    master, attendance, skp = inputs()
    for test_master, test_absence, test_skp in [({},attendance,skp),
        (master,attendance+attendance,skp), (master,attendance,skp+skp),
        (master,attendance,[{**skp[0],'review_status':'PENDING_REVIEW'}])]:
        row = combine(test_master,test_absence,test_skp,[], '2026-08')[0]
        assert row['payable_estimate'] is None
        assert row['status']=='PERLU REVIEW'


def test_full_component_reduction_and_zero_preserved():
    master, attendance, skp = inputs()
    attendance[0]['potPct']=100
    skp[0]['report_status']='NOT_SUBMITTED_VERIFIED'
    history=[{'nip':'001','skp_reduction_rate':100,'payment_eligible':True}]
    row=combine(master,attendance,skp,history,'2026-08')[0]
    assert row['total_deduction']==5000000
    assert row['payable_estimate']==0


def test_approved_hold_and_unknown_eligibility_block_estimate():
    master, attendance, skp=inputs()
    conditions=[{'nip':'001','status':'APPROVED','payment_effect':'HOLD','reason':'Keputusan uji'}]
    row=combine(master,attendance,skp,[],'2026-08',conditions)[0]
    assert row['calculated_entitlement']==4350000
    assert row['payable_estimate'] is None
    assert 'Keputusan uji' in row['issues']
    master['001']['eligible']=None
    assert combine(master,attendance,skp,[],'2026-08')[0]['payable_estimate'] is None


def test_export_rejects_changed_snapshot(monkeypatch):
    from backend import tukin_combined as module
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setattr(module,'build',lambda *args:[])
    app=FastAPI(); app.include_router(module.create_router(lambda:'unused'))
    response=TestClient(app).get('/api/tukin/combined/export?assessment_period=2026-08&expected=outdated')
    assert response.status_code==409


def test_preview_rejects_both_conflicting_duplicate_rows(tmp_path):
    _, service, _ = services(tmp_path)
    preview=service.preview({'assessment_period':'2026-08','rows':[
        {'NIP':NIP,'Predikat':'Baik'}, {'NIP':NIP,'Predikat':'Kurang'}]})
    assert preview['valid_count']==0
    assert all(any(i['code']=='DUPLICATE_NIP' for i in row['issues']) for row in preview['rows'])


def test_import_keeps_original_rejected_rows_for_reconciliation(tmp_path):
    import json
    _, service, _=services(tmp_path)
    service.import_rows({'assessment_period':'2026-08','confirmed':True,'source_file':'source.xlsx',
        'rows':[{'NIP':NIP,'Predikat':'Baik','Rating Hasil Kinerja':'Sesuai Ekspektasi'},
                {'NIP':'999','Predikat':'-','Rating Hasil Kinerja':'-'}]})
    with service.connect() as conn:
        sources=conn.execute('SELECT raw_json FROM skp_import_source ORDER BY source_row').fetchall()
        assert len(sources)==2
        assert json.loads(sources[1][0])['Predikat']=='-'
        assert conn.execute('SELECT count(*) FROM skp_assessment_monthly').fetchone()[0]==1


def test_partial_capture_storage_preserves_other_participants_and_locked_period(tmp_path):
    _, _, annual=services(tmp_path)
    annual.ensure_period('2026-08','2026-09','LIVE')
    annual._replace_period('tukin_final_monthly','2026-08',[
        {'assessment_period':'2026-08','payment_period':'2026-09','nip':'001','nama':'First'},
        {'assessment_period':'2026-08','payment_period':'2026-09','nip':'002','nama':'Second'}])
    annual._replace_period('tukin_final_monthly','2026-08',[
        {'assessment_period':'2026-08','payment_period':'2026-09','nip':'001','nama':'Updated'}],merge=True)
    with annual.connect() as conn:
        assert conn.execute('SELECT nip,nama FROM tukin_final_monthly ORDER BY nip').fetchall()==[('001','Updated'),('002','Second')]
        conn.execute("UPDATE tukin_period SET status='LOCKED' WHERE assessment_period='2026-08'")
    with pytest.raises(ValueError,match='terkunci'):
        annual.capture_live('2026-08','2026-09')


def test_build_preserves_period_boundary_and_master_without_attendance(tmp_path):
    master, _, _ = services(tmp_path)
    import duckdb
    with duckdb.connect(master.db_path) as conn:
        conn.execute('CREATE TABLE final_absensi (nip VARCHAR, bulan VARCHAR, potPct DOUBLE)')
        conn.execute('INSERT INTO final_absensi VALUES (?, ?, ?)',[NIP,'2026-07',100])
    rows=build(master.db_path,'2026-08')
    row=next(row for row in rows if row['nip']==NIP)
    assert row['attendance_rate'] is None
    assert row['tukin_gross']==10000000


def test_excel_exports_all_rows_and_preserves_missing_values(monkeypatch):
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend import tukin_combined as module
    rows=[{'nip':f'001234567890{i:06d}', 'nama':f'Test {i}', 'tukin_gross':5000000,
           'payable_estimate':None, 'status':'PERLU REVIEW'} for i in range(2005)]
    monkeypatch.setattr(module,'build',lambda *args:rows)
    app=FastAPI(); app.include_router(module.create_router(lambda:'unused'))
    response=TestClient(app).get('/api/tukin/combined/export?assessment_period=2026-08')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        output_rows=sheet.findall('x:sheetData/x:row',ns)
        assert len(output_rows)==2006
        strings=[''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        for i,row in enumerate(output_rows[1:]):
            nip=row.find(f"x:c[@r='B{i+2}']/x:v",ns)
            assert strings[int(nip.text)]==rows[i]['nip']
            assert row.find(f"x:c[@r='Q{i+2}']/x:v",ns) is None
