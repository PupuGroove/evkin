import duckdb

from backend.tukin_uat_audit import audit_skp_sources, scan_periods


PERIOD = "2026-08"
NIP = "198701012026011001"


def setup_db(tmp_path):
    path = str(tmp_path / "uat-audit.duckdb")
    with duckdb.connect(path) as conn:
        conn.execute("CREATE TABLE master_data(nip VARCHAR)")
        conn.execute("INSERT INTO master_data VALUES (?)", [NIP])
        conn.execute("CREATE TABLE final_absensi(nip VARCHAR, bulan VARCHAR)")
        conn.execute("INSERT INTO final_absensi VALUES (?,?)", [NIP, PERIOD])
        conn.execute("""CREATE TABLE skp_assessment_monthly(
            assessment_period VARCHAR,nip VARCHAR,review_status VARCHAR,
            import_batch_id VARCHAR,approved_at TIMESTAMP)""")
        conn.execute("""CREATE TABLE skp_import_batch(
            id VARCHAR,assessment_period VARCHAR,status VARCHAR,created_at TIMESTAMP)""")
        conn.execute("""CREATE TABLE final_tukin_results(
            nip VARCHAR,periode VARCHAR,calculation_batch_id VARCHAR,
            status VARCHAR,created_at TIMESTAMP)""")
        conn.execute("""CREATE TABLE final_tukin_batches(
            id VARCHAR,periode VARCHAR,created_at TIMESTAMP)""")
    return path


def test_master_is_not_automatic_processing_scope(tmp_path):
    rows = scan_periods(setup_db(tmp_path))
    assert rows[0]["processing"] == 1
    assert rows[0]["scope_source_type"] == "FINAL_ABSENSI"
    assert rows[0]["scope_quality"] == "FALLBACK"


def test_authoritative_assessment_scope_beats_attendance_fallback(tmp_path):
    path = setup_db(tmp_path)
    with duckdb.connect(path) as conn:
        conn.execute(
            "INSERT INTO skp_assessment_monthly VALUES (?,?,?,?,now())",
            [PERIOD, NIP, "APPROVED", "SKP-BATCH-1"],
        )
    row = scan_periods(path)[0]
    assert row["scope_source_type"] == "SKP_ASSESSMENT_OR_IMPORT"
    assert row["scope_quality"] == "TRACEABLE"
    assert row["eligible_intersection_estimate"] == 1


def test_draft_skp_does_not_enter_eligible_intersection(tmp_path):
    path = setup_db(tmp_path)
    with duckdb.connect(path) as conn:
        conn.execute(
            "INSERT INTO skp_assessment_monthly VALUES (?,?,?,?,NULL)",
            [PERIOD, NIP, "PENDING_REVIEW", "SKP-BATCH-1"],
        )
    row = scan_periods(path)[0]
    assert row["skp_available"] == 1
    assert row["skp_final_approved"] == 0
    assert row["eligible_intersection_estimate"] == 0


def test_legacy_is_traceable_but_not_official_and_source_inventory_is_explicit(tmp_path):
    path = setup_db(tmp_path)
    with duckdb.connect(path) as conn:
        conn.execute(
            "INSERT INTO final_tukin_results VALUES (?,?,?,?,now())",
            [NIP, PERIOD, "LEGACY-BATCH-1", "FINALIZED"],
        )
    row = scan_periods(path)[0]
    assert row["legacy_source"] == "final_tukin_results"
    assert row["legacy_source_quality"] == "TRACEABLE_LEGACY"
    inventory = {item["source"]: item for item in audit_skp_sources(path)}
    assert inventory["skp_assessment_monthly"]["canonical_safe"] is False
