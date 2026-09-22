from pathlib import Path

import duckdb

from backend.shared_master import SharedMasterService
from backend.tukin_annual import TukinAnnualService
from backend import evkin_export_api


def master_service(tmp_path: Path) -> SharedMasterService:
    return SharedMasterService(str(tmp_path / "shared.duckdb"))


def base_row(**overrides):
    row = {
        "NIP": "198701012026011001",
        "Nama": "ANI UJI",
        "Jabatan": "PENDAMPING SOSIAL",
        "Unit Kerja": "UNIT A",
        "Provinsi": "ACEH",
        "Kabupaten/Kota": "PIDIE",
        "Kelas Jabatan": "7",
        "Tukin": "Rp2.000.000",
        "Berhak Tukin": "YA",
        "Wilayah 3T": "3T",
        "Bank": "BRI",
        "No Rekening": "001234567890",
        "Nama Pemilik Rekening": "ANI UJI",
    }
    row.update(overrides)
    return row


def test_import_preview_histories_and_legacy_projection(tmp_path):
    svc = master_service(tmp_path)
    preview = svc.preview([base_row()])
    assert preview["new_count"] == 1
    result = svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    assert result["committed"] == 1

    listed = svc.list()
    assert listed["total"] == 1
    assert listed["rows"][0]["account_number"] == "001234567890"
    with svc.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sdm_assignment_history").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sdm_tukin_profile_history").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sdm_bank_history").fetchone()[0] == 1
        legacy = conn.execute('SELECT nip,tukin,"noRekening" FROM master_data').fetchone()
    assert legacy == ("198701012026011001", 2_000_000, "001234567890")


def test_effective_history_and_period_snapshot(tmp_path):
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row()], "2026-01-01", "jan.xlsx", "Pemeriksa", True)
    svc.ingest_rows([base_row(Tukin="Rp2.500.000", Bank="MANDIRI", **{"No Rekening": "0099"})],
                    "2026-08-01", "aug.xlsx", "Pemeriksa", True)

    january = svc.snapshot_map("2026-01")["198701012026011001"]
    august = svc.snapshot_map("2026-08")["198701012026011001"]
    assert january["tukin_gross"] == 2_000_000
    assert january["account_number"] == "001234567890"
    assert january["master_version"] == 1
    assert august["tukin_gross"] == 2_500_000
    assert august["account_number"] == "0099"
    assert august["master_version"] == 2


def test_annual_final_freezes_master_values_and_soft_delete_preserves_history(tmp_path):
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    annual = TukinAnnualService(svc.db_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "payment_period": "2026-09",
        "source_file": "final.xlsx", "rows": [{
            "NIP": "198701012026011001", "Predikat": "Baik", "Potongan Absensi": "5%"
        }],
    })
    detail = svc.detail("198701012026011001")
    snapshot = detail["snapshots"][0]
    assert snapshot["tukin_gross"] == 2_000_000
    assert snapshot["bank_name"] == "BRI"
    assert snapshot["master_version"] == 1
    monthly_export = annual.export_final("2026-08").getvalue()
    annual_export = annual.export_annual(2026).getvalue()
    assert monthly_export[:2] == b"PK" and len(monthly_export) > 5_000
    assert annual_export[:2] == b"PK" and len(annual_export) > 10_000

    svc.set_active("198701012026011001", False, "Berhenti", "Pemeriksa")
    assert svc.list(active=False)["total"] == 1
    assert svc.detail("198701012026011001")["snapshots"][0]["paid_amount"] == 1_970_000
    with svc.connect() as conn:
        assert conn.execute("SELECT count(*) FROM master_data").fetchone()[0] == 0


def test_workflow_reconciliation_reports_unknown_and_name_mismatch(tmp_path):
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    with svc.connect() as conn:
        conn.execute("CREATE TABLE raw_import(nip TEXT,nama TEXT)")
        conn.executemany("INSERT INTO raw_import VALUES (?,?)", [
            ("198701012026011001", "NAMA BERBEDA"), ("999", "SDM TIDAK DIKENAL")
        ])
    result = svc.reconcile_workflow()
    assert result["issues_created"] == 2
    issues = svc.validation_issues()["rows"]
    assert {row["issue_type"] for row in issues} == {"UNKNOWN_NIP", "NAME_MISMATCH"}


def test_legacy_master_is_backfilled_once_without_recursion(tmp_path):
    path = str(tmp_path / "legacy.duckdb")
    with duckdb.connect(path) as conn:
        conn.execute("CREATE TABLE master_data(nip TEXT,nama TEXT,tukin DOUBLE)")
        conn.execute("INSERT INTO master_data VALUES ('123','SDM LEGACY',1500000)")
    svc = SharedMasterService(path)
    assert svc.list()["total"] == 1
    assert svc.list()["rows"][0]["nama"] == "SDM LEGACY"


def test_legacy_master_endpoint_reads_canonical_source_when_projection_is_empty(tmp_path, monkeypatch):
    path = str(tmp_path / "canonical.duckdb")
    svc = SharedMasterService(path)
    svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    with svc.connect() as conn:
        conn.execute('DROP TABLE IF EXISTS "master_data"')
        conn.execute('CREATE TABLE "master_data" (_empty TEXT)')

    monkeypatch.setattr(evkin_export_api, "DUCKDB_PATH", path)
    result = evkin_export_api.get_master_sdm(
        q=None, page=1, per_page=50, jabatan=None, unit=None, sort=None
    )

    assert result["source"] == "shared-master"
    assert result["count"] == 1
    assert result["rows"][0]["nip"] == "198701012026011001"
    assert result["rows"][0]["tukin"] == 2_000_000
    monkeypatch.setattr(evkin_export_api, 'shared_master', None)
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as unavailable:
        evkin_export_api.get_master_sdm(q=None, page=1, per_page=50, jabatan=None, unit=None, sort=None)
    assert unavailable.value.status_code == 503
    from backend import shared_master as shared_module
    monkeypatch.setattr(evkin_export_api, 'shared_master', shared_module)

    filtered = evkin_export_api.get_master_sdm(
        q=None, page=1, per_page=50, jabatan="PENDAMPING SOSIAL", unit="UNIT A", sort="tukin"
    )
    assert filtered["count"] == 1
    assert filtered["source"] == "shared-master"


def test_workflow_tukin_lookup_only_returns_requested_nips(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.shared_master import create_router
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row(), base_row(NIP="0002", Tukin="0"),
                     base_row(NIP="0003", Tukin="3000000")],
                    "2026-01-01", "master.xlsx", "Pemeriksa", True)
    with svc.connect() as conn:
        conn.execute('DELETE FROM master_data')
    app = FastAPI()
    app.include_router(create_router(lambda: svc.db_path))
    client = TestClient(app)
    result = client.post('/api/shared-master/lookup-tukin',
                         json={"nips": ["0002", "0003", "0003", "UNKNOWN"]})
    assert result.status_code == 200
    body = result.json()
    assert {row['nip']: row['tukin'] for row in body['rows']} == {"0002": 0, "0003": 3000000}
    assert body['missing_nips'] == ['UNKNOWN']
    assert client.post('/api/shared-master/lookup-tukin', json={"nips": []}).json()['rows'] == []
    assert client.post('/api/shared-master/lookup-tukin', json={"nips": [123]}).status_code == 400


def test_one_sheet_flag_tendik_import_builds_effective_month_history(tmp_path):
    svc = master_service(tmp_path)
    row = base_row(**{
        "FLAG TENDIK JUNI 2026": "Walih Asuh",
        "FLAG TENDIK JULI 2026": "",
        "FLAG TENDIK AGUSTUS 2026": "-",
    })
    preview = svc.preview([row], "2026-01-01")
    assert preview["assignment_column_count"] == 3
    assert preview["assignment_new_count"] == 1
    assert preview["assignment_changed_count"] == 1
    assert preview["assignment_continued_count"] == 1
    assert preview["assignment_rejected_count"] == 0

    result = svc.ingest_rows([row], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    assert result["assignment_committed"] == 2
    detail = svc.detail("198701012026011001")
    assert [(item["effective_month"], item["assignment_type"], item["assignment_detail"])
            for item in reversed(detail["temporary_assignments"])] == [
        ("2026-06", "TENDIK", "Walih Asuh"),
        ("2026-08", "SDM PKH", ""),
    ]
    assert svc.snapshot_map("2026-06")["198701012026011001"]["status_tendik"] == "TENDIK"
    assert svc.snapshot_map("2026-07")["198701012026011001"]["jabatan_osdm"] == "Walih Asuh"
    august = svc.snapshot_map("2026-08")["198701012026011001"]
    assert august["status_tendik"] == "SDM PKH"
    assert august["temporary_assignment_effective_month"] == "2026-08"


def test_template_headers_jabatan_formal_and_wilayah_yes_are_supported(tmp_path):
    svc = master_service(tmp_path)
    row = base_row()
    row.pop("Jabatan")
    row["JABATAN FORMAL"] = "ANALIS SDM"
    row["WILAYAH 3T"] = "YA"
    row["FLAG TENDIK JUNI 2026"] = "-"
    svc.ingest_rows([row], "2026-01-01", "template.xlsx", "Pemeriksa", True)
    snapshot = svc.snapshot_map("2026-06")["198701012026011001"]
    assert snapshot["jabatan"] == "ANALIS SDM"
    assert snapshot["wilayah_3t"] is True


def test_flag_without_year_uses_master_effective_year_and_blank_initial_is_rejected(tmp_path):
    svc = master_service(tmp_path)
    invalid = base_row(**{"FLAG TENDIK JUNI": "", "FLAG TENDIK JULI": "-"})
    preview = svc.preview([invalid], "2026-01-01")
    assert preview["assignment_rejected_count"] == 1
    assert preview["assignment_rejections"][0]["period"] == "2026-06"

    valid = base_row(**{"FLAG TENDIK JUNI": "-", "FLAG TENDIK JULI": "Walih Asuh"})
    result = svc.ingest_rows([valid], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    assert result["assignment_committed"] == 2
    assert svc.snapshot_map("2026-07")["198701012026011001"]["status_tendik"] == "TENDIK"


def test_temporary_assignment_cannot_change_locked_tukin_period(tmp_path):
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    annual = TukinAnnualService(svc.db_path)
    annual.ensure_period("2026-08", "2026-09")
    annual.lock_period("2026-08", "LOCKED")

    preview = svc.preview([{"NIP": "198701012026011001", "FLAG TENDIK JUNI 2026": "-"}], "2026-01-01")
    assert preview["assignment_rejected_count"] == 1
    assert "dikunci" in preview["assignment_rejections"][0]["reason"]


def test_inactive_import_is_inactive_and_profile_update_does_not_reactivate(tmp_path):
    svc = master_service(tmp_path)
    row = base_row(**{"Status Kepegawaian": "TIDAK AKTIF"})
    svc.ingest_rows([row], "2026-01-01", "inactive.xlsx", "Pemeriksa", True)
    assert svc.list(active=False)["total"] == 1

    svc.ingest_rows([{"NIP": row["NIP"], "Bank": "MANDIRI"}], "2026-08-01", "bank.xlsx", "Pemeriksa", True)
    assert svc.list(active=False)["total"] == 1
    assert svc.detail(row["NIP"])["person"]["bank_name"] == "MANDIRI"


def test_rejected_master_row_cancels_entire_batch(tmp_path):
    svc = master_service(tmp_path)
    rows = [base_row(), {"NIP": "", "Nama": "INVALID"}]
    try:
        svc.ingest_rows(rows, "2026-01-01", "invalid.xlsx", "Pemeriksa", True)
        assert False, "batch dengan baris invalid seharusnya ditolak"
    except ValueError as exc:
        assert "Seluruh impor dibatalkan" in str(exc)
    assert svc.list()["total"] == 0


def test_preview_token_binds_rows_effective_date_and_master_version(tmp_path):
    svc = master_service(tmp_path)
    row = base_row()
    preview = svc.preview([row], "2026-01-01")
    svc.ingest_rows([row], "2026-01-01", "master.xlsx", "Pemeriksa", True,
                    preview_token=preview["preview_token"], require_preview_token=True)

    stale = svc.preview([{"NIP": row["NIP"], "Bank": "BNI"}], "2026-08-01")
    svc.set_active(row["NIP"], False, "Berhenti", "Pemeriksa", "2026-07-01")
    try:
        svc.ingest_rows([{"NIP": row["NIP"], "Bank": "BNI"}], "2026-08-01", "bank.xlsx", "Pemeriksa", True,
                        preview_token=stale["preview_token"], require_preview_token=True)
        assert False, "token lama seharusnya ditolak setelah versi master berubah"
    except ValueError as exc:
        assert "Preview sudah tidak berlaku" in str(exc)


def test_active_lifecycle_preserves_prior_period_and_reset_is_recoverable(tmp_path):
    svc = master_service(tmp_path)
    svc.ingest_rows([base_row(), base_row(NIP="2", Nama="B")], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    svc.set_active("198701012026011001", False, "Berhenti", "Pemeriksa", "2026-08-01")
    assert svc.snapshot_map("2026-07")["198701012026011001"]["eligible"] is True
    assert svc.snapshot_map("2026-08")["198701012026011001"]["eligible"] is False

    result = svc.deactivate_all("Reset administratif", "Pemeriksa", "2026-09-01")
    assert result == {"status": "ok", "deactivated": 1, "recoverable": True}
    assert svc.list(active=False)["total"] == 2
    svc.set_active("2", True, "Dipulihkan", "Pemeriksa", "2026-09-01")
    assert svc.list(active=True)["total"] == 1


def test_projection_failure_does_not_report_canonical_commit_as_failed(tmp_path, monkeypatch):
    svc = master_service(tmp_path)
    monkeypatch.setattr(svc, "refresh_legacy_projection", lambda: (_ for _ in ()).throw(RuntimeError("projection busy")))
    result = svc.ingest_rows([base_row()], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    assert result["committed"] == 1
    assert result["projection_status"] == "warning"
    with svc.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sdm_master").fetchone()[0] == 1
