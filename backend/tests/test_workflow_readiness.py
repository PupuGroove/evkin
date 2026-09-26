import duckdb

from backend.workflow_readiness import (
    record_verification,
    validate_final_readiness,
)


PERIOD = "2026-08"


def setup_db(tmp_path, rekap_rows=None):
    path = str(tmp_path / "workflow.duckdb")
    with duckdb.connect(path) as conn:
        conn.execute("CREATE TABLE hitung_harian (nip VARCHAR, tanggalKey VARCHAR, bulan VARCHAR)")
        conn.execute("CREATE TABLE anomali (nip VARCHAR, tanggalKey VARCHAR, bulan VARCHAR)")
        conn.execute("CREATE TABLE rekap_sdm (nip VARCHAR, bulan VARCHAR, jumlahRecord INTEGER)")
        daily = [("001", "2026-08-01", PERIOD), ("002", "2026-08-01", PERIOD)]
        conn.executemany("INSERT INTO hitung_harian VALUES (?, ?, ?)", daily)
        conn.executemany("INSERT INTO anomali VALUES (?, ?, ?)", daily)
        conn.executemany(
            "INSERT INTO rekap_sdm VALUES (?, ?, ?)",
            rekap_rows or [("001", PERIOD, 1), ("002", PERIOD, 1)],
        )
    return path


def test_verification_persists_and_readiness_reload(tmp_path):
    path = setup_db(tmp_path)
    assert validate_final_readiness(path, PERIOD)["checks"]["semifinal_verified"] is False
    assert record_verification(path, PERIOD)["verified"] is True
    result = validate_final_readiness(path, PERIOD)
    assert result["checks"]["semifinal_verified"] is True
    assert result["ready"] is True


def test_verification_materializes_semifinal_from_canonical_daily_and_is_repeatable(tmp_path):
    path = setup_db(tmp_path)
    with duckdb.connect(path) as conn:
        conn.execute("CREATE OR REPLACE TABLE anomali (_empty VARCHAR)")
    first = record_verification(path, PERIOD)
    second = record_verification(path, PERIOD)
    assert first["rows"] == 2
    assert second["verified"] is True
    with duckdb.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM anomali WHERE bulan = ?", [PERIOD]).fetchone()[0] == 2


def test_final_gate_rejects_unverified_and_reports_reason(tmp_path):
    path = setup_db(tmp_path)
    result = validate_final_readiness(path, PERIOD)
    assert result["ready"] is False
    assert "Verifikasi Semi Final belum tercatat di database." in result["blocking_reasons"]


def test_duplicate_daily_key_blocks_readiness(tmp_path):
    path = setup_db(tmp_path)
    with duckdb.connect(path) as conn:
        conn.execute("INSERT INTO hitung_harian VALUES ('001', '2026-08-01', ?)", [PERIOD])
    result = validate_final_readiness(path, PERIOD)
    assert result["checks"]["harian_duplicates"] is True


def test_duplicate_rekap_nip_blocks_readiness(tmp_path):
    path = setup_db(tmp_path, [("001", PERIOD, 1), ("001", PERIOD, 1), ("002", PERIOD, 1)])
    result = validate_final_readiness(path, PERIOD)
    assert result["checks"]["rekap_duplicates"] is True
    assert result["checks"]["rekap_consistent"] is False


def test_rekap_mismatch_blocks_readiness(tmp_path):
    path = setup_db(tmp_path, [("001", PERIOD, 2), ("002", PERIOD, 1)])
    result = validate_final_readiness(path, PERIOD)
    assert result["checks"]["rekap_consistent"] is False
    assert any("Rekap SDM tidak konsisten" in reason for reason in result["blocking_reasons"])


def test_upstream_change_invalidates_verification(tmp_path):
    path = setup_db(tmp_path)
    record_verification(path, PERIOD)
    with duckdb.connect(path) as conn:
        conn.execute("INSERT INTO hitung_harian VALUES ('003', '2026-08-02', ?)", [PERIOD])
    result = validate_final_readiness(path, PERIOD)
    assert result["checks"]["stale_state"] is True
    assert result["ready"] is False


def test_invalid_period_is_blocking(tmp_path):
    result = validate_final_readiness(setup_db(tmp_path), "2026-13")
    assert result["ready"] is False
    assert result["checks"]["period_valid"] is False
