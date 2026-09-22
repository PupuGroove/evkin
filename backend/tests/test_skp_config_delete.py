import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.skp_assessment import create_router
from backend.tests.test_skp_assessment import services, NIP


def config(service, status='APPROVED', target=20):
    return service.save_indicator_config({'indicator_code':'HEK','target_mode':'FIXED',
        'target_value':target,'reaches_min_percent':100,'effective_from':'2026-08',
        'scope_type':'ALL','status':status,'created_by':'Petugas Uji'})


def test_delete_used_version_preserves_assessment_and_audit(tmp_path):
    _, service, _ = services(tmp_path)
    first = config(service)
    second = config(service,target=22)
    service.import_rows({'assessment_period':'2026-08','confirmed':True,'source_file':'test.xlsx',
        'rows':[{'NIP':NIP,'Predikat Kinerja Periodik':'Baik','Realisasi HEK':18}]})
    with service.connect() as conn:
        original = conn.execute('SELECT indicator_config_snapshot,hek_target,hek_status FROM skp_assessment_monthly').fetchall()
    service.delete_indicator_config(second['id'],{'actor':'Pemeriksa','reason':'Versi salah'})
    assert [r['id'] for r in service.list_indicator_configs('2026-08')['rows']] == [first['id']]
    assert [r['id'] for r in service._active_indicator_configs('2026-08')['HEK']] == [first['id']]
    with service.connect() as conn:
        assert conn.execute('SELECT indicator_config_snapshot,hek_target,hek_status FROM skp_assessment_monthly').fetchall() == original
        old,new,actor = conn.execute("SELECT old_value,new_value,actor FROM skp_indicator_config_audit WHERE action='DELETE'").fetchone()
        assert json.loads(old)['id'] == second['id']
        assert json.loads(new)['reason'] == 'Versi salah'
        assert actor == 'Pemeriksa'
    assert config(service)['version'] == 3


def test_delete_route_validates_reason_and_repeated_delete(tmp_path):
    master, service, _ = services(tmp_path)
    created=config(service,'DRAFT')
    app=FastAPI(); app.include_router(create_router(lambda:master.db_path))
    client=TestClient(app)
    path='/api/skp-assessment/indicator-config/'+created['id']
    for body in [{'actor':'Petugas'}, {'reason':'Salah'}, {'actor':' ','reason':'Salah'}]:
        assert client.request('DELETE',path,json=body).status_code == 400
    body={'actor':'Petugas','reason':'Draft ganda'}
    assert client.request('DELETE',path,json=body).status_code == 200
    assert service.list_indicator_configs()['rows'] == []
    assert client.request('DELETE',path,json=body).status_code == 400
    assert client.request('DELETE','/api/skp-assessment/indicator-config/missing',json=body).status_code == 400


def test_audit_failure_rolls_back_deletion(tmp_path, monkeypatch):
    _, service, _ = services(tmp_path)
    created=config(service)
    def fail(*args):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(service,'_audit_config',fail)
    with pytest.raises(RuntimeError):
        service.delete_indicator_config(created['id'],{'actor':'Petugas','reason':'Uji transaksi'})
    assert service.list_indicator_configs()['rows'][0]['status'] == 'APPROVED'
