import pytest

from backend.tests.test_skp_assessment import services, NIP


def payload(period="2026-07", predicate="Baik", **extra):
    return {"assessment_period": period, "import_mode": "FINAL", "confirmed": True,
            "final_confirmed": True, "imported_by": "Petugas Final",
            "rows": [{"NIP": NIP, "Nama": "ANI UJI", "Predikat": predicate}], **extra}


def test_final_import_is_distinct_final_source_and_audited_without_configuration(tmp_path):
    _, skp, annual = services(tmp_path)
    result = skp.import_rows(payload(predicate="Kurang"))
    assert result["imported"] == 1
    with annual.connect() as conn:
        assert conn.execute("SELECT final_predicate,review_status,approved_by FROM skp_assessment_monthly").fetchone() == ("Kurang", "FINAL_IMPORTED", None)
        assert conn.execute("SELECT skp_reduction_rate,payment_eligible FROM tukin_skp_monthly").fetchone() == (10, True)
    assert result["source_type"] == "DIRECT_FINAL_IMPORT" and result["ready_for_tukin"] is True
    assert "IMPORT_FINAL" in str(skp.audit_detail("2026-07", NIP))


@pytest.mark.parametrize("extra", [{"final_confirmed": False}, {"imported_by": ""}, {"import_mode": "TYPO"}])
def test_final_requires_explicit_confirmation_actor_and_mode(tmp_path, extra):
    _, skp, _ = services(tmp_path)
    with pytest.raises(ValueError):
        skp.import_rows(payload(**extra))


def test_equivalent_missing_labels_follow_consecutive_month_rules(tmp_path):
    _, skp, annual = services(tmp_path)
    for month, label in [(7, "-"), (8, "tidak bisa dinilai"), (9, "tidak membuat SKP")]:
        skp.import_rows(payload(f"2026-{month:02}", label))
    with annual.connect() as conn:
        rows = conn.execute("SELECT report_status,consecutive_missing,skp_reduction_rate,payment_eligible FROM tukin_skp_monthly ORDER BY assessment_period").fetchall()
    assert [r[0] for r in rows] == ["NOT_SUBMITTED_VERIFIED"] * 3
    assert [r[1] for r in rows] == [1, 2, 3]
    assert rows[0][2] == 35
    assert rows[1][2] == 70
    assert rows[2][3] is False


def test_blank_is_not_missing_report_penalty(tmp_path):
    _, skp, _ = services(tmp_path)
    result = skp.preview(payload(predicate=""))
    assert result["valid_count"] == 0
    assert result["rows"][0]["report_status"] == "DATA_MISSING"


def test_gap_resets_streak(tmp_path):
    _, skp, annual = services(tmp_path)
    skp.import_rows(payload("2026-07", "-"))
    skp.import_rows(payload("2026-09", "tidak membuat SKP"))
    with annual.connect() as conn:
        assert conn.execute("SELECT consecutive_missing FROM tukin_skp_monthly WHERE assessment_period='2026-09'").fetchone() == (1,)
