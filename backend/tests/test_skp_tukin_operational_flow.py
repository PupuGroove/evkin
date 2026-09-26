import duckdb
import pytest

from backend.final_tukin import FinalTukinService
from backend.shared_master import SharedMasterService
from backend.skp_assessment import SkpAssessmentService
from backend.tukin_combined import create_calculation_snapshot


NIP = "198701012026011099"


def service(tmp_path, wilayah="3T"):
    path = str(tmp_path / "operational.duckdb")
    SharedMasterService(path).ingest_rows([{
        "NIP": NIP, "Nama": "OPERATOR TEST", "Tukin": 10_000_000,
        "Berhak Tukin": "YA", "Wilayah 3T": wilayah,
    }], "2026-01-01", "master.xlsx", "ADMIN", True)
    return path, SkpAssessmentService(path)


def test_flag_scoped_rule_recommends_predicate_and_rate(tmp_path):
    _, skp = service(tmp_path)
    skp.save_assessment_rule({
        "rule_name": "HEK 3T di bawah target", "flag_scope": "3T",
        "condition_field": "hek_achievement_pct", "comparison_operator": "LT",
        "threshold_value": "100", "result_if_met": "Kurang", "reduction_if_met": 12,
        "result_if_not_met": "Baik", "reduction_if_not_met": 0,
        "effective_from": "2026-01", "created_by": "ADMIN",
    })
    preview = skp.preview({
        "assessment_period": "2026-09", "import_mode": "REVIEW",
        "rows": [{"NIP": NIP, "Predikat": "Baik", "Target HEK": 20, "Realisasi HEK": 18}],
    })
    row = preview["rows"][0]
    assert row["sdm_flag"] == "3T"
    assert row["recommended_predicate"] == "Kurang"
    assert row["recommended_reduction_rate"] == 12
    assert row["assessment_rule_id"]


def test_final_import_bypasses_rules_preserves_source_without_internal_finalization(tmp_path):
    _, skp = service(tmp_path)
    skp.save_assessment_rule({
        "rule_name": "Rule yang tidak boleh menimpa keputusan final", "flag_scope": "ALL",
        "condition_field": "source_predicate", "comparison_operator": "EQ",
        "threshold_value": "Baik", "result_if_met": "Sangat Kurang",
        "effective_from": "2026-01", "created_by": "ADMIN",
    })
    result = skp.import_rows({
        "assessment_period": "2026-09", "import_mode": "FINAL", "confirmed": True,
        "final_confirmed": True, "imported_by": "PEJABAT", "source_file": "final-skp.xlsx",
        "rows": [{"NIP": NIP, "Nama": "OPERATOR TEST", "Predikat Kinerja Periodik": "Baik"}],
    })
    assert result["imported"] == 1
    summary = skp.period_summary("2026-09")["summary"]
    assert summary["status"] == "FINAL_IMPORTED" and summary["final_count"] == 1
    assert summary["direct_final_count"] == 1 and summary["review_count"] == 0
    with skp.connect() as conn:
        assessment = conn.execute(
            "SELECT final_predicate,assessment_rule_id,review_status FROM skp_assessment_monthly"
        ).fetchone()
        raw = conn.execute("SELECT raw_json FROM skp_import_source").fetchone()[0]
    assert assessment == ("Baik", None, "FINAL_IMPORTED")
    assert "Predikat Kinerja Periodik" in raw


def test_manual_override_requires_reason_and_audits_before_after(tmp_path):
    _, skp = service(tmp_path, "NON_3T")
    skp.import_rows({
        "assessment_period": "2026-09", "confirmed": True, "imported_by": "IMPORTIR",
        "rows": [{"NIP": NIP, "Predikat": "Baik"}],
    })
    with pytest.raises(ValueError, match="manual override"):
        skp.review({"assessment_period": "2026-09", "nips": [NIP], "action": "APPROVE",
                    "final_predicate": "Kurang", "approved_by": "REVIEWER"})
    skp.review({"assessment_period": "2026-09", "nips": [NIP], "action": "APPROVE",
                "final_predicate": "Kurang", "final_reduction_rate": 15,
                "notes": "Keputusan rapat BA-09", "approved_by": "REVIEWER"})
    with skp.connect() as conn:
        current = conn.execute(
            "SELECT final_predicate,final_reduction_rate,manual_override_reason,manual_override_by FROM skp_assessment_monthly"
        ).fetchone()
        audit = conn.execute(
            "SELECT action,old_value,new_value,actor FROM skp_assessment_audit WHERE action='MANUAL_OVERRIDE'"
        ).fetchone()
    assert current == ("Kurang", 15, "Keputusan rapat BA-09", "REVIEWER")
    assert audit[0] == "MANUAL_OVERRIDE" and "Baik" in audit[1] and "Kurang" in audit[2]
    assert audit[3] == "REVIEWER"


def test_non_submission_streak_action_is_configuration_driven(tmp_path):
    _, skp = service(tmp_path)
    rules = skp.non_submission_rules()["rows"]
    for row in rules:
        if row["streak_from"] == 1:
            row.update(action="PERCENT", reduction_rate=20, effective_from="2026-01")
        elif row["streak_from"] == 2:
            row.update(action="UNPAID", reduction_rate=100, effective_from="2026-01")
        else:
            row.update(active=False, effective_from="2026-01")
    skp.save_non_submission_rules({"rules": rules, "updated_by": "ADMIN"})
    for period in ("2026-01", "2026-02"):
        skp.import_rows({
            "assessment_period": period, "confirmed": True, "imported_by": "IMPORTIR",
            "rows": [{"NIP": NIP, "Predikat": "Tidak Mengerjakan SKP"}],
        })
        skp.review({"assessment_period": period, "nips": [NIP], "action": "APPROVE",
                    "approved_by": "REVIEWER"})
    with skp.connect() as conn:
        rows = conn.execute(
            "SELECT consecutive_missing,skp_reduction_rate,payment_eligible FROM tukin_skp_monthly ORDER BY assessment_period"
        ).fetchall()
    assert rows == [(1, 20, True), (2, 100, False)]


def test_master_only_employee_does_not_block_workflow_finalization(tmp_path):
    path, skp = service(tmp_path)
    with skp.connect() as conn:
        conn.execute("CREATE TABLE final_absensi(nip TEXT,nama TEXT,bulan TEXT,potPct DECIMAL(9,4))")
        conn.execute("INSERT INTO final_absensi VALUES (?, 'OPERATOR TEST', '2026-09', 0)", [NIP])
        conn.execute("INSERT INTO sdm_master(sdm_id,nip,nama,active) VALUES ('MISSING','999','BELUM LENGKAP',true)")
    skp.import_rows({
        "assessment_period": "2026-09", "import_mode": "FINAL", "confirmed": True,
        "final_confirmed": True, "imported_by": "PEJABAT",
        "rows": [{"NIP": NIP, "Predikat": "Baik"}],
    })
    calculation = create_calculation_snapshot(path, "2026-09", "OPERATOR")
    assert calculation["scope"] == "workflow"
    assert calculation["target_count"] == 1
    assert calculation["mismatch"] == 0
    final = FinalTukinService(path).approve_calculation(
        calculation["calculation_id"], "APPROVER", "Peserta workflow lengkap"
    )
    assert final["status"] == "FINAL"
