import json
import pytest
from backend.tests.test_skp_assessment import services, NIP


def setup(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.ensure_period('2026-08','2026-09','LIVE')
    batch = skp.import_rows({'assessment_period':'2026-08','confirmed':True,
        'source_file':'first.xlsx','rows':[{'NIP':NIP,'Predikat':'Baik'}]})['batch_id']
    return skp, annual, batch


def request(skp, mode='selected', **extra):
    payload = {'assessment_period':'2026-08','mode':mode,'nips':[NIP],
               'actor':'Operator Uji','reason':'Koreksi impor', **extra}
    preview = skp.preview_removal(payload)
    return {**payload,'confirmed':True,'preview_token':preview['preview_token']}


def test_selected_removal_preserves_source_audit_and_holds_final(tmp_path):
    skp, annual, batch = setup(tmp_path)
    with annual.connect() as conn:
        conn.execute("INSERT INTO tukin_final_monthly (assessment_period,payment_period,nip,paid_amount,payment_status) VALUES ('2026-08','2026-09',?,100,'READY_TO_PAY')",[NIP])
    assert skp.remove_assessments(request(skp))['deleted']==1
    with skp.connect() as conn:
        assert conn.execute('SELECT count(*) FROM skp_import_source').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM skp_assessment_monthly').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM tukin_skp_monthly').fetchone()[0]==0
        assert conn.execute('SELECT payment_status,paid_amount FROM tukin_final_monthly').fetchone()==('HOLD',None)
    audit=skp.audit_detail('2026-08',NIP)
    assert audit['assessment'] is None
    removed=next(row for row in audit['audit'] if row['action']=='DELETE_SELECTED')
    assert json.loads(removed['old_value'])['nip']==NIP
    assert removed['actor']=='Operator Uji'


@pytest.mark.parametrize('locked',['LOCKED','HISTORICAL_LOCKED','PAID'])
@pytest.mark.parametrize('mode',['selected','period','batch'])
def test_lock_is_rechecked_after_preview(tmp_path,locked,mode):
    skp, annual, batch=setup(tmp_path)
    payload=request(skp,mode,batch_id=batch)
    with annual.connect() as conn:
        conn.execute('UPDATE tukin_period SET status=? WHERE assessment_period=?',[locked,'2026-08'])
    with pytest.raises(ValueError,match='dikunci/dibayar'):
        skp.remove_assessments(payload)
    with skp.connect() as conn:
        assert conn.execute('SELECT count(*) FROM skp_assessment_monthly').fetchone()[0]==1


def test_cancel_old_batch_does_not_remove_new_import(tmp_path):
    skp, _, batch=setup(tmp_path)
    skp.import_rows({'assessment_period':'2026-08','confirmed':True,
        'source_file':'second.xlsx','rows':[{'NIP':NIP,'Predikat':'Kurang'}]})
    assert skp.remove_assessments(request(skp,'batch',batch_id=batch))['deleted']==0
    with skp.connect() as conn:
        assert conn.execute('SELECT source_predicate FROM skp_assessment_monthly').fetchone()[0]=='Kurang'
        assert conn.execute('SELECT status FROM skp_import_batch WHERE id=?',[batch]).fetchone()[0]=='CANCELLED'


def test_confirmation_and_stale_preview_required(tmp_path):
    skp, _, _=setup(tmp_path)
    payload=request(skp)
    with pytest.raises(ValueError,match='Konfirmasi'):
        skp.remove_assessments({**payload,'confirmed':False})
    with skp.connect() as conn:
        conn.execute("UPDATE skp_assessment_monthly SET source_predicate='Kurang'")
    with pytest.raises(ValueError,match='Data berubah'):
        skp.remove_assessments(payload)


def test_period_reset_preserves_other_period_and_rollback_on_audit_failure(tmp_path,monkeypatch):
    skp, _, _=setup(tmp_path)
    skp.import_rows({'assessment_period':'2026-09','confirmed':True,'rows':[{'NIP':NIP,'Predikat':'Baik'}]})
    payload=request(skp,'period')
    original=skp._audit
    def fail(*args):
        if args[2]=='': raise RuntimeError('Simulasi gagal audit akhir')
        return original(*args)
    monkeypatch.setattr(skp,'_audit',fail)
    with pytest.raises(RuntimeError): skp.remove_assessments(payload)
    monkeypatch.setattr(skp,'_audit',original)
    assert skp.remove_assessments(payload)['deleted']==1
    with skp.connect() as conn:
        assert conn.execute('SELECT assessment_period FROM skp_assessment_monthly').fetchall()==[('2026-09',)]


def test_later_locked_payment_is_unchanged(tmp_path):
    skp, annual, _=setup(tmp_path)
    annual.ensure_period('2026-09','2026-10','LIVE')
    with annual.connect() as conn:
        conn.execute("UPDATE tukin_period SET status='PAID' WHERE assessment_period='2026-09'")
        conn.execute("INSERT INTO tukin_final_monthly (assessment_period,payment_period,nip,paid_amount,payment_status) VALUES ('2026-09','2026-10',?,123,'PAID')",[NIP])
    skp.remove_assessments(request(skp))
    with annual.connect() as conn:
        assert conn.execute("SELECT paid_amount,payment_status FROM tukin_final_monthly WHERE assessment_period='2026-09'").fetchone()==(123,'PAID')


def test_paid_row_blocks_even_when_period_is_open(tmp_path):
    skp, annual, _=setup(tmp_path)
    with annual.connect() as conn:
        conn.execute("INSERT INTO tukin_final_monthly (assessment_period,payment_period,nip,paid_amount,payment_status) VALUES ('2026-08','2026-09',?,123,'PAID')",[NIP])
    with pytest.raises(ValueError,match='sudah dibayar'): request(skp)
