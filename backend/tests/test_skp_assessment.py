from pathlib import Path
from io import BytesIO

import pandas as pd
import pytest

from backend.shared_master import SharedMasterService
from backend.skp_assessment import SkpAssessmentService
from backend.tukin_annual import TukinAnnualService


NIP = "198701012026011001"


def services(tmp_path: Path):
    db_path = str(tmp_path / "skp.duckdb")
    master = SharedMasterService(db_path)
    master.ingest_rows([{
        "NIP": NIP, "Nama": "ANI UJI", "Jabatan": "PENDAMPING SOSIAL",
        "Penilai": "ATASAN UJI", "Tukin": "Rp10.000.000", "Berhak Tukin": "YA",
    }], "2026-01-01", "master.xlsx", "Pemeriksa", True)
    return master, SkpAssessmentService(db_path), TukinAnnualService(db_path)


def test_preview_rejects_unknown_predicate_duplicate_and_unknown_master(tmp_path):
    _, skp, _ = services(tmp_path)
    result = skp.preview({
        "assessment_period": "2026-08",
        "rows": [
            {"NIP": NIP, "Predikat Kinerja Periodik": "Cukup"},
            {"NIP": NIP, "Predikat Kinerja Periodik": "Baik"},
            {"NIP": "999", "Predikat Kinerja Periodik": "Baik"},
        ],
    })
    assert result["valid_count"] == 0
    codes = {issue["code"] for issue in result["issues"]}
    assert {"INVALID_PREDICATE", "DUPLICATE_NIP", "NIP_NOT_IN_MASTER"} <= codes


def test_import_holds_then_approval_updates_tukin(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000",
                  "Potongan Absensi e-Absensi (%)": "10%", "potongan absen final": "Rp300.000",
                  "FINAL TUKIN DIBAYAR": "Rp9.700.000", "STATUS PEMBAYARAN": "dibayarkan"}],
    })
    payload = {
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "imported_by": "IMPORTIR", "rows": [{
            "NIP": NIP, "Nama": "ANI UJI", "Predikat Kinerja Periodik": "Kurang",
            "HEK": "Mencapai", "Verkom": "Kurang", "Alasan": "Verkom tidak mencapai target",
        }],
    }
    result = skp.import_rows(payload)
    assert result["imported"] == 1
    with annual.connect() as conn:
        assert conn.execute("SELECT report_status,payment_eligible FROM tukin_skp_monthly").fetchone() == ("REVIEW_REQUIRED", False)
        assert conn.execute("SELECT payment_status,paid_amount FROM tukin_final_monthly").fetchone() == ("HOLD", 0)

    skp.bulk_recommend({
        "assessment_period": "2026-08", "nips": [NIP], "recommended_predicate": "Kurang",
        "reason": "Verkom tidak mencapai target", "verkom_status": "KURANG", "reviewed_by": "REVIEWER",
    })
    approved = skp.review({
        "assessment_period": "2026-08", "nips": [NIP], "action": "APPROVE", "approved_by": "PEJABAT",
    })
    assert approved["updated"] == 1
    with annual.connect() as conn:
        monthly = conn.execute(
            "SELECT predicate_normalized,skp_reduction_rate,payment_eligible FROM tukin_skp_monthly"
        ).fetchone()
        final = conn.execute(
            "SELECT skp_deduction,attendance_deduction,paid_amount,payment_status FROM tukin_final_monthly"
        ).fetchone()
        audit_count = conn.execute("SELECT count(*) FROM skp_assessment_audit").fetchone()[0]
    assert monthly == ("Kurang", 10, True)
    assert tuple(map(float, final[:3])) == (700_000, 300_000, 9_000_000)
    assert final[3] == "READY_TO_PAY"
    assert audit_count == 3


def test_annual_documentation_and_export(tmp_path):
    _, skp, _ = services(tmp_path)
    skp.import_rows({
        "assessment_period": "2026-01", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Tidak Mengerjakan SKP"}],
    })
    skp.review({"assessment_period": "2026-01", "nips": [NIP], "action": "APPROVE", "approved_by": "PEJABAT"})
    annual = skp.annual(2026)
    assert annual["rows"][0]["not_submitted_months"] == ["2026-01"]
    exported = skp.export_annual(2026).getvalue()
    assert exported[:2] == b"PK" and len(exported) > 5_000


@pytest.mark.parametrize("period_status", ["LOCKED", "PAID", "HISTORICAL_LOCKED"])
def test_locked_period_rejects_assessment_changes_and_reimport(tmp_path, period_status):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Predikat": "Baik"}],
    })
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Baik"}],
    })
    annual.lock_period("2026-08", period_status)
    with pytest.raises(ValueError, match="dikunci"):
        skp.bulk_recommend({
            "assessment_period": "2026-08", "nips": [NIP], "recommended_predicate": "Kurang",
            "reason": "Perubahan setelah dikunci",
        })
    with pytest.raises(ValueError, match="dikunci"):
        skp.import_rows({
            "assessment_period": "2026-08", "source_file": "skp-reimport.xlsx", "confirmed": True,
            "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Kurang"}],
        })

    with skp.connect() as conn:
        assessment = conn.execute(
            """SELECT source_predicate,review_status,source_file
               FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?""",
            ["2026-08", NIP],
        ).fetchone()
        batch_count = conn.execute(
            "SELECT count(*) FROM skp_import_batch WHERE assessment_period='2026-08'"
        ).fetchone()[0]
    assert assessment == ("Baik", "PENDING_REVIEW", "skp.xlsx")
    assert batch_count == 1


def test_versioned_indicator_config_calculates_target_actual_and_snapshot(tmp_path):
    _, skp, _ = services(tmp_path)
    created = skp.save_indicator_config({
        "indicator_code": "HEK", "display_name": "Hari Efektif Kerja", "unit": "hari",
        "target_mode": "FIXED", "target_value": 20, "reaches_min_percent": 100,
        "effective_from": "2026-08", "scope_type": "ALL", "status": "APPROVED",
        "meeting_document": "BA-01/2026", "created_by": "PEJABAT",
    })
    assert created["version"] == 1 and created["config_status"] == "APPROVED"
    preview = skp.preview({
        "assessment_period": "2026-08",
        "rows": [{
            "NIP": NIP, "Predikat Kinerja Periodik": "Baik", "Realisasi HEK": 18,
        }],
    })
    row = preview["rows"][0]
    assert row["hek_target"] == 20
    assert row["hek_actual"] == 18
    assert row["hek_achievement_pct"] == 90
    assert row["hek_status"] == "KURANG"
    assert "HEK-ALL-all-2026-08" in row["indicator_config_snapshot"]


def test_meeting_batch_exception_and_not_assessable_mapping(tmp_path):
    _, skp, _ = services(tmp_path)
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Tidak Bisa Dinilai"}],
    })
    with skp.connect() as conn:
        assert conn.execute("SELECT report_status FROM skp_assessment_monthly").fetchone()[0] == "NOT_SUBMITTED_VERIFIED"
    result = skp.bulk_recommend({
        "assessment_period": "2026-08", "nips": [NIP], "recommended_predicate": "Baik",
        "reason": "Keputusan rapat setelah verifikasi", "meeting_date": "2026-09-02",
        "document_number": "BA-02/2026", "reviewed_by": "TIM RAPAT",
    })
    assert result["updated"] == 1
    with skp.connect() as conn:
        batch = conn.execute("SELECT document_number,affected_count,status FROM skp_meeting_batch").fetchone()
        member_count = conn.execute("SELECT count(*) FROM skp_meeting_member").fetchone()[0]
    assert batch == ("BA-02/2026", 1, "RECORDED") and member_count == 1

    saved = skp.save_exception({
        "assessment_period": "2026-08", "nips": [NIP], "exception_code": "CUTI_MELAHIRKAN",
        "start_date": "2026-08-01", "end_date": "2026-08-31", "reason": "Cuti resmi",
        "evidence_ref": "SK-03/2026", "approved_by": "PEJABAT",
    })
    assert saved["updated"] == 1
    with skp.connect() as conn:
        assert conn.execute("SELECT report_status FROM skp_assessment_monthly").fetchone()[0] == "EXEMPT_MATERNITY"
    reimport = skp.preview({
        "assessment_period": "2026-08",
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Tidak Bisa Dinilai"}],
    })
    assert reimport["rows"][0]["report_status"] == "EXEMPT_MATERNITY"


def test_capture_live_preserves_approved_skp_assessment(tmp_path):
    _, skp, annual = services(tmp_path)
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Predikat Kinerja Periodik": "Kurang"}],
    })
    skp.bulk_recommend({
        "assessment_period": "2026-08", "nips": [NIP], "recommended_predicate": "Kurang",
        "reason": "Capaian kurang", "meeting_date": "2026-09-01", "document_number": "BA-04",
    })
    skp.review({"assessment_period": "2026-08", "nips": [NIP], "action": "APPROVE", "approved_by": "PEJABAT"})
    with annual.connect() as conn:
        conn.execute("CREATE OR REPLACE TABLE final_absensi AS SELECT ? nip, ? nama, ? jabatan, 10000000 tukin, 0 potPct, 0 nominal", [NIP, "ANI UJI", "PENDAMPING"])
        conn.execute("CREATE OR REPLACE TABLE final_skp AS SELECT ? nip, 'Baik' predikat", [NIP])
    annual.capture_live("2026-08", "2026-09")
    with annual.connect() as conn:
        monthly = conn.execute("SELECT predicate_normalized,skp_reduction_rate FROM tukin_skp_monthly WHERE assessment_period='2026-08'").fetchone()
        final = conn.execute("SELECT predicate_skp,skp_deduction FROM tukin_final_monthly WHERE assessment_period='2026-08'").fetchone()
    assert monthly == ("Kurang", 10)
    assert final[0] == "Kurang" and float(final[1]) == 700_000


def test_deceased_defaults_to_hold_exempts_skp_and_stops_future_transactions(tmp_path):
    master, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000",
                  "Potongan Absensi e-Absensi (%)": "10%", "Potongan Absen Final": "Rp300.000",
                  "FINAL TUKIN DIBAYAR": "Rp9.700.000", "STATUS PEMBAYARAN": "dibayarkan"}],
    })
    annual.import_rows({
        "source_type": "ATTENDANCE_DAILY", "assessment_period": "2026-08", "source_file": "daily.xlsx",
        "rows": [
            {"NIP": NIP, "Tanggal": "2026-08-10", "Potongan Harian": "2%"},
            {"NIP": NIP, "Tanggal": "2026-08-20", "Potongan Harian": "4%"},
        ],
    })
    saved = skp.save_exception({
        "assessment_period": "2026-08", "nips": [NIP], "exception_code": "MENINGGAL",
        "start_date": "2026-08-15", "reason": "Meninggal dunia",
        "evidence_ref": "AKTA-KEMATIAN-01", "approved_by": "PEJABAT",
    })
    assert saved["payment_decision"] == "HOLD_REVIEW"
    with annual.connect() as conn:
        death = conn.execute(
            "SELECT stop_effective_period,payment_decision,pay_to_heir FROM sdm_death_record WHERE nip=?", [NIP]
        ).fetchone()
        final = conn.execute(
            """SELECT report_status,skp_deduction,attendance_reduction_rate,attendance_deduction,
                      calculated_entitlement,paid_amount,payment_status,recipient_type
               FROM tukin_final_monthly WHERE assessment_period='2026-08' AND nip=?""", [NIP]
        ).fetchone()
        change = conn.execute(
            "SELECT effective_date,new_value,status FROM sdm_change_request WHERE batch_id LIKE 'DEATH-%'"
        ).fetchone()
    assert death == ("2026-09", "HOLD_REVIEW", False)
    assert final[0] == "EXEMPT_DECEASED" and float(final[1]) == 0
    assert float(final[2]) == 2 and float(final[3]) == 60_000
    assert float(final[4]) == 9_940_000 and float(final[5]) == 0
    assert final[6:] == ("HOLD", "EMPLOYEE_ACCOUNT")
    assert str(change[0]) == "2026-09-01" and change[1:] == ("false", "APPROVED")

    future = skp.preview({
        "assessment_period": "2026-09",
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Baik"}],
    })
    assert future["valid_count"] == 0
    assert "SDM_INACTIVE_DECEASED" in {issue["code"] for issue in future["issues"]}

    with annual.connect() as conn:
        conn.execute(
            "CREATE OR REPLACE TABLE final_absensi AS SELECT ? nip, 'ANI UJI' nama, 'PENDAMPING' jabatan, 10000000 tukin, 0 potPct, 0 nominal",
            [NIP],
        )
    captured = annual.capture_live("2026-09", "2026-10")
    assert captured["captured"] == 0
    with annual.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM tukin_final_monthly WHERE assessment_period='2026-09' AND nip=?", [NIP]
        ).fetchone()[0] == 0


def test_deceased_heir_payment_is_optional_and_separate_from_master_account(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000",
                  "NO REKENING": "11112222", "BANK": "BANK PEGAWAI",
                  "PEMILIK REKENING": "ANI UJI", "STATUS PEMBAYARAN": "dibayarkan"}],
    })
    with pytest.raises(ValueError, match="Data pembayaran ahli waris belum lengkap"):
        skp.save_exception({
            "assessment_period": "2026-08", "nips": [NIP], "exception_code": "MENINGGAL",
            "start_date": "2026-08-15", "reason": "Meninggal dunia", "evidence_ref": "AKTA-01",
            "pay_to_heir": True, "heir_name": "BUDI",
        })

    saved = skp.save_exception({
        "assessment_period": "2026-08", "nips": [NIP], "exception_code": "MENINGGAL",
        "start_date": "2026-08-15", "reason": "Meninggal dunia", "evidence_ref": "AKTA-01",
        "approved_by": "PEJABAT", "pay_to_heir": True, "heir_name": "BUDI",
        "heir_relationship": "Suami", "heir_bank_name": "BANK AHLI WARIS",
        "heir_account_number": "99998888", "heir_account_holder": "BUDI",
        "heir_document_ref": "SK-AHLI-WARIS-01", "payment_notes": "Disetujui bendahara",
    })
    assert saved["payment_decision"] == "HEIR"
    with annual.connect() as conn:
        final = conn.execute(
            """SELECT payment_status,paid_amount,recipient_type,recipient_name,recipient_bank_name,
                      recipient_account_number,beneficiary_document_ref,bank_name,account_number
               FROM tukin_final_monthly WHERE assessment_period='2026-08' AND nip=?""", [NIP]
        ).fetchone()
    assert final[:7] == ("READY_TO_PAY", 10_000_000, "HEIR", "BUDI", "BANK AHLI WARIS", "99998888", "SK-AHLI-WARIS-01")
    assert final[7:] == ("BANK PEGAWAI", "11112222")

    detail = annual.person_detail(NIP, 2026)
    assert detail["death"]["pay_to_heir"] is True
    assert detail["person"]["months"][7]["recipient_type"] == "HEIR"
    assert annual.export_final("2026-08").getvalue()[:2] == b"PK"
    assert annual.export_annual(2026).getvalue()[:2] == b"PK"


def test_hukdis_decision_is_governed_in_skp_and_synced_to_tukin(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000",
                  "FINAL TUKIN DIBAYAR": "Rp10.000.000", "STATUS PEMBAYARAN": "dibayarkan"}],
    })
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Predikat Kinerja Periodik": "Baik"}],
    })
    skp.review({"assessment_period": "2026-08", "nips": [NIP], "action": "APPROVE",
                "approved_by": "PEJABAT SKP"})
    saved = skp.save_condition_decision({
        "assessment_period": "2026-08", "nips": [NIP], "condition_code": "HUKDIS",
        "skp_effect": "NONE", "payment_effect": "UNPAID",
        "start_date": "2026-08-01", "end_date": "2026-08-31",
        "reason": "Keputusan hukuman disiplin", "document_number": "SK-HUKDIS-01",
        "evidence_ref": "ARSIP/HUKDIS/01", "approved_by": "PEJABAT KEPEGAWAIAN",
    })
    assert saved == {"status": "ok", "assessment_period": "2026-08", "updated": 1,
                     "synced_to_tukin": 1}
    with annual.connect() as conn:
        assessment = conn.execute(
            "SELECT final_predicate,review_status FROM skp_assessment_monthly"
        ).fetchone()
        final = conn.execute(
            "SELECT paid_amount,payment_status,payment_reason,special_conditions FROM tukin_final_monthly"
        ).fetchone()
        decision = conn.execute(
            "SELECT synced_to_tukin,document_number FROM skp_condition_decision"
        ).fetchone()
    assert assessment == ("Baik", "APPROVED")
    assert float(final[0]) == 0 and final[1] == "UNPAID"
    assert "Hukuman disiplin" in final[2] and "HUKDIS" in final[3]
    assert decision == (True, "SK-HUKDIS-01")
    register = annual.list_conditions(2026)["rows"]
    assert register[0]["condition_source"] == "PENILAIAN SKP"
    assert register[0]["condition_code"] == "HUKDIS"


def test_hukdis_recommendation_returns_to_review_and_approved_export_filters(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000"}],
    })
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Predikat Kinerja Periodik": "Baik"}],
    })
    skp.save_condition_decision({
        "assessment_period": "2026-08", "nips": [NIP], "condition_code": "HUKDIS",
        "skp_effect": "RECOMMEND_PREDICATE", "recommended_predicate": "Kurang",
        "payment_effect": "HOLD", "reason": "Hasil rapat dan verifikasi Hukdis",
        "document_number": "BA-HUKDIS-02", "evidence_ref": "ARSIP/HUKDIS/02",
        "approved_by": "TIM RAPAT",
    })
    with skp.connect() as conn:
        assert conn.execute(
            "SELECT recommended_predicate,final_predicate,review_status FROM skp_assessment_monthly"
        ).fetchone() == ("Kurang", None, "RECOMMENDED")

    empty = pd.read_excel(BytesIO(skp.export_annual(2026, "approved").getvalue()),
                          sheet_name="Hasil Approved")
    assert empty.empty
    skp.review({"assessment_period": "2026-08", "nips": [NIP], "action": "APPROVE",
                "approved_by": "PEJABAT SKP"})
    approved = pd.read_excel(BytesIO(skp.export_annual(2026, "approved").getvalue()),
                             sheet_name="Hasil Approved")
    assert approved.shape[0] == 1
    assert approved.loc[0, "Predikat Final"] == "Kurang"
    assert approved.loc[0, "Potongan SKP (%)"] == 10
    assert approved.loc[0, "Status Review"] == "APPROVED"
    assert approved.loc[0, "Kondisi Khusus"] == "HUKDIS"
    with annual.connect() as conn:
        assert conn.execute(
            "SELECT payment_status,paid_amount,skp_deduction FROM tukin_final_monthly"
        ).fetchone() == ("HOLD", 0, 700000)
    assert skp.get_config()["config"]["third_month_rate"] == 100


def test_neutral_condition_does_not_bypass_pending_skp_hold(tmp_path):
    _, skp, annual = services(tmp_path)
    annual.import_rows({
        "source_type": "FINAL", "assessment_period": "2026-08", "source_file": "final.xlsx",
        "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Tukin": "Rp10.000.000"}],
    })
    skp.import_rows({
        "assessment_period": "2026-08", "source_file": "skp.xlsx", "confirmed": True,
        "rows": [{"NIP": NIP, "Predikat Kinerja Periodik": "Baik"}],
    })
    skp.save_condition_decision({
        "assessment_period": "2026-08", "nips": [NIP], "condition_code": "LAINNYA",
        "skp_effect": "NONE", "payment_effect": "NONE", "reason": "Catatan administratif",
        "document_number": "BA-ADMIN-01", "evidence_ref": "ARSIP/ADMIN/01",
        "approved_by": "TIM VERIFIKASI",
    })
    with annual.connect() as conn:
        assert conn.execute(
            "SELECT payment_status,paid_amount,payment_reason FROM tukin_final_monthly"
        ).fetchone() == ("HOLD", 0, "Penilaian SKP belum valid/disetujui")


def test_third_missing_skp_rule_is_fixed_to_unpaid(tmp_path):
    _, skp, _ = services(tmp_path)
    assert skp.get_config()["config"]["third_month_action"] == "UNPAID"
    with pytest.raises(ValueError, match="wajib tidak dibayarkan"):
        skp.update_config({"third_month_action": "HOLD_REVIEW", "updated_by": "PENGUJI"})
