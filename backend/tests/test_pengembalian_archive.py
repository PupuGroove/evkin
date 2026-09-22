import importlib.util
from pathlib import Path

import duckdb

from backend.pengembalian_archive import ArchiveService


def make_service(tmp_path):
    path = tmp_path / "archive.duckdb"
    migration = importlib.util.spec_from_file_location(
        "m023", str(Path(__file__).resolve().parents[1] / "migrations" /
                   "023_create_pengembalian_archive_compare.py")
    )
    # The test file may be copied independently; use the repository migration
    # location in the normal pytest layout.
    if migration is None:
        raise AssertionError("migration not found")
    module = importlib.util.module_from_spec(migration)
    migration.loader.exec_module(module)
    module.main(str(path))
    return ArchiveService(str(path)), path


def test_daily_base_snapshot_schema_is_separate_and_traceable(tmp_path):
    path = tmp_path / "daily-base.duckdb"
    migration = importlib.util.spec_from_file_location(
        "m024", str(Path(__file__).resolve().parents[1] / "migrations" /
                   "024_create_pengembalian_dasar_harian_archive.py")
    )
    module = importlib.util.module_from_spec(migration)
    migration.loader.exec_module(module)
    module.main(str(path))
    conn = duckdb.connect(str(path))
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'pengembalian_dasar_harian_%'"
            ).fetchall()
        }
        assert "pengembalian_dasar_harian_awal" in tables
        assert "pengembalian_dasar_harian_penyesuaian" in tables
        columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info('pengembalian_dasar_harian_awal')"
            ).fetchall()
        }
        assert {
            "nip", "tanggal", "jam_masuk", "jam_pulang", "nilai_potongan_harian",
            "master_comparison_key", "import_id", "source_version", "archive_version"
        } <= columns
        conn.execute(
            """INSERT INTO pengembalian_dasar_harian_awal
               (record_id, nip, import_id, dataset_type, master_comparison_key)
               VALUES ('awal-1', '100', 'import-1', 'DATA_DASAR_AWAL', 'nip=100|tahun=2025')"""
        )
        conn.execute(
            """INSERT INTO pengembalian_dasar_harian_penyesuaian
               (record_id, nip, import_id, dataset_type, master_comparison_key)
               VALUES ('adjust-1', '100', 'import-2', 'DATA_DASAR_PENYESUAIAN', 'nip=100|tahun=2025')"""
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM pengembalian_dasar_harian_awal"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM pengembalian_dasar_harian_penyesuaian"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def row(**changes):
    value = {
        "NIP": "100", "Tahun SP2D": 2025, "Periode": "2025-01", "Bulan": 1,
        "Batch": "B1", "Komponen": "TUKIN", "Total Tukin": 1000,
        "Tukin SKP 70%": 700, "Potongan SKP": 10, "ESDM": 25,
        "E-Absensi": 30, "Tendik": 5,
        "daily_id": "D1", "monthly_id": "M1", "absence_id": "A1",
        "total_tukin_id": "T1",
    }
    value.update(changes)
    return value


def test_unchanged_and_traceability(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row()], "DATA_AWAL")
    archive.import_rows([row()], "DATA_PENYESUAIAN")
    result = archive.compare()
    assert result["unchanged_count"] == 1
    assert result["details"][0]["data_awal"][0]["daily_ref"] == "D1"
    assert result["details"][0]["data_awal"][0]["monthly_ref"] == "M1"
    assert result["details"][0]["data_awal"][0]["absence_ref"] == "A1"


def test_component_changes_and_minimum_rule(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row()], "DATA_AWAL")
    archive.import_rows([row(**{"Tukin SKP 70%": 750, "ESDM": 50, "E-Absensi": 20})],
                        "DATA_PENYESUAIAN")
    detail = archive.compare()["details"][0]
    assert detail["result_type"] == "BERUBAH"
    assert detail["changes"]["tukin_skp_70"]["delta"] == 50
    assert detail["changes"]["esdm"]["delta"] == 25
    assert detail["changes"]["e_absensi"]["delta"] == -10
    assert detail["changes"]["total_potongan_absen"]["data_penyesuaian"] == 20
    assert detail["changes"]["total_potongan_tukin"]["data_penyesuaian"] == 30


def test_new_missing_and_duplicate_are_not_aggregated(tmp_path):
    archive, path = make_service(tmp_path)
    archive.import_rows([row(), row(**{"Total Tukin": 1100}),
                         row(**{"NIP": "300"})], "DATA_AWAL")
    archive.import_rows([row(**{"NIP": "200"})], "DATA_PENYESUAIAN")
    result = archive.compare()
    duplicate = [d for d in result["details"] if d["result_type"] == "DUPLIKASI"]
    assert duplicate and "DUPLIKASI" in duplicate[0]["flags"]
    assert "RECORD GANDA - PERLU KONFIRMASI" in duplicate[0]["flags"]
    assert len(duplicate[0]["data_awal"]) == 2
    assert "DUPLIKASI" in duplicate[0]["data_awal"][0]["validation_flags"]
    assert result["new_count"] == 1
    assert result["missing_count"] == 1
    conn = duckdb.connect(str(path))
    try:
        assert conn.execute("select count(*) from pengembalian_archive_data_awal").fetchone()[0] == 3
    finally:
        conn.close()


def test_missing_source_is_flagged_and_validation_preserves_row(tmp_path):
    archive, _ = make_service(tmp_path)
    preview = archive.preview([{"Tahun SP2D": 2025}], "DATA_AWAL")
    assert not preview["valid"]
    assert "NIP WAJIB DIISI" in preview["errors"][0]["flags"]


def test_tukin_percentage_validation_preserves_source_values():
    valid = ArchiveService.normalize_row(row(**{
        "Total Tukin": 10_000_000,
        "Tukin Absen 30%": 3_000_000,
        "Tukin SKP 70%": 7_000_000,
    }))
    assert valid["_tukin_validation"]["tukin_absen_30"]["status"] == "VALID"
    assert valid["_tukin_validation"]["tukin_skp_70"]["status"] == "VALID"
    invalid = ArchiveService.normalize_row(row(**{
        "Total Tukin": 10_000_000,
        "Tukin Absen 30%": 2_500_000,
        "Tukin SKP 70%": 7_500_000,
    }))
    assert invalid["tukin_absen_30"] == 2_500_000
    assert invalid["_tukin_validation"]["tukin_absen_30"]["status"] == "TIDAK SESUAI"


def test_traceability_and_unknown_source_flags(tmp_path):
    archive, _ = make_service(tmp_path)
    daily_a = [{"tanggal": "2025-10-15", "jam_masuk": "07:30",
                "potongan_telat": 5, "total_potongan_harian": 5}]
    daily_b = [{"tanggal": "2025-10-15", "jam_masuk": "07:15",
                "potongan_telat": 3, "total_potongan_harian": 3}]
    archive.import_rows([row(daily_data=daily_a)], "DATA_AWAL")
    archive.import_rows([row(daily_data=daily_b, **{"E-Absensi": 20})], "DATA_PENYESUAIAN")
    detail = archive.compare()["details"][0]
    assert detail["source_type"] == "ABSENSI_HARIAN"
    assert detail["source_status"] == "TERIDENTIFIKASI"
    assert detail["traceability"]["chain"] == [
        "Data Harian", "Rekap Bulanan", "Potongan Absen", "Total Potongan Tukin"
    ]

    archive2, _ = make_service(tmp_path / "unknown")
    archive2.import_rows([row()], "DATA_AWAL")
    archive2.import_rows([row(**{"E-Absensi": 20})], "DATA_PENYESUAIAN")
    unknown = archive2.compare()["details"][0]
    assert unknown["source_type"] == "UNKNOWN"
    assert unknown["source_status"] == "SUMBER PERUBAHAN TIDAK TERIDENTIFIKASI"
    assert "SUMBER PERUBAHAN TIDAK TERIDENTIFIKASI" in unknown["flags"]


def test_dashboard_business_metrics(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row(), row(**{"NIP": "200", "Potongan SKP": 20})], "DATA_AWAL")
    archive.import_rows([row(**{"E-Absensi": 20})], "DATA_PENYESUAIAN")
    dashboard = archive.dashboard()
    assert dashboard["total_sdm"] == 2
    assert dashboard["sdm_berubah"] == 1
    assert dashboard["sdm_tidak_berubah"] == 0
    assert dashboard["data_hilang"] == 1
    assert dashboard["total_selisih"] == -50


def test_bpk_history_survives_adjustment_and_exposes_batch(tmp_path):
    archive, _ = make_service(tmp_path)
    awal = archive.import_rows([row()], "DATA_AWAL")
    archive.import_rows([row(**{"Total Tukin": 600})], "DATA_PENYESUAIAN")
    source_row = archive.list("DATA_AWAL")[0]
    sent = archive.record_bpk_history(
        "legacy-bpk-id",
        [{"archive_row_id": source_row["row_id"], "source_dataset": "DATA_AWAL",
          "bpk_reference": "BPK-001"}],
    )
    assert sent["bpk_batch"] == 1
    result = archive.compare()
    detail = result["details"][0]
    assert detail["is_send_bpk"] is True
    assert detail["bpk_batch"] == 1
    assert detail["bpk_batch_label"] == "SEND BPK BATCH 1"
    assert detail["bpk_reference"] == "BPK-001"
    assert detail["data_awal"][0]["import_id"] == awal["import_id"]
    assert detail["result_type"] == "BERUBAH"


def test_bpk_history_filter_does_not_change_source_rows(tmp_path):
    archive, path = make_service(tmp_path)
    archive.import_rows([row()], "DATA_AWAL")
    archive.import_rows([row(**{"NIP": "200"})], "DATA_AWAL")
    conn = duckdb.connect(str(path))
    try:
        conn.execute("UPDATE pengembalian_archive_import SET imported_at=TIMESTAMP '2026-01-01 00:00:00'")
        conn.execute("UPDATE pengembalian_archive_data_awal SET created_at=TIMESTAMP '2026-01-01 00:00:00'")
    finally:
        conn.close()

    first_read = archive.list("DATA_AWAL")
    second_read = archive.list("DATA_AWAL")
    assert [item["nip"] for item in first_read] == ["100", "200"]
    assert [item["row_id"] for item in second_read] == [item["row_id"] for item in first_read]
    assert all(item["source_row"] == 1 for item in first_read)

    source_row = first_read[0]
    archive.record_bpk_history("bpk-id", [{"archive_row_id": source_row["row_id"]}])
    filtered = archive.list("DATA_AWAL", {"bpk_batch": 1})
    assert len(filtered) == 1
    assert filtered[0]["nip"] == "100"
    conn = duckdb.connect(str(path))
    try:
        stored = conn.execute(
            "SELECT nip,source_row FROM pengembalian_archive_data_awal ORDER BY rowid"
        ).fetchall()
        assert stored == [("100", 1), ("200", 1)]
    finally:
        conn.close()


def test_final_preserves_omitted_adjustment_components_and_searches_partial_text(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row(Nama="Budi Santoso", **{"E-Absensi": 30})], "DATA_AWAL")
    # Adjustment contains only the corrected absence value.
    archive.import_rows([{"NIP": "100", "Tahun SP2D": 2025, "Periode": "2025-01",
                          "Bulan": 1, "Batch": "B1", "Komponen": "TUKIN",
                          "E-Absensi": 20}], "DATA_PENYESUAIAN")
    final = archive.final()["rows"][0]
    assert final["final_values"]["potongan_skp"] == 10
    assert final["final_values"]["e_absensi"] == 20
    assert len(archive.list("DATA_AWAL", {"search": "Budi Sant"})) == 1


def test_import_metadata_preview_and_identical_import_protection(tmp_path):
    archive, path = make_service(tmp_path)
    metadata = {
        "dataset_type": "DATA_AWAL",
        "send_bpk_status": "SEND BPK BATCH 1",
        "bpk_batch": 1,
        "source_file_name": "DATA_AWAL_OKTOBER.xlsx",
        "version": "v1",
    }
    preview = archive.preview([row()], "DATA_AWAL", metadata)
    assert preview["dataset_type"] == "DATA_AWAL"
    assert preview["send_bpk_status"] == "SEND BPK BATCH 1"
    assert preview["total_pengembalian"] == 35
    imported = archive.import_rows([row()], "DATA_AWAL", metadata)
    assert imported["bpk_batch"] == 1
    assert archive.repository.imports("DATA_AWAL", 1)[0]["dataset_type"] == "DATA_AWAL"
    try:
        archive.import_rows([row()], "DATA_AWAL", metadata)
    except ValueError as exc:
        assert "IMPORT IDENTIK" in str(exc)
    else:
        raise AssertionError("identical import must be rejected")
    conn = duckdb.connect(str(path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_archive_data_awal").fetchone()[0] == 1
    finally:
        conn.close()


def test_reconciliation_changed_fields_and_period_key(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row()], "DATA_AWAL")
    archive.import_rows([row(**{"Potongan SKP": 20, "ESDM": 30, "E-Absensi": 10})],
                        "DATA_PENYESUAIAN")
    detail = archive.compare()["details"][0]
    assert detail["compare_status"] == "BERUBAH"
    assert {"potongan_skp", "esdm", "e_absensi"} <= set(detail["changed_fields"])
    assert detail["changes"]["esdm"]["delta"] == 5
    assert detail["changes"]["total_potongan_tukin"]["delta"] == -5

    period_archive, _ = make_service(tmp_path / "period")
    period_archive.import_rows([row()], "DATA_AWAL")
    period_archive.import_rows([row(Periode="2025-02", Bulan=2)], "DATA_PENYESUAIAN")
    statuses = {item["compare_status"] for item in period_archive.compare()["details"]}
    assert statuses == {"DATA BARU", "DATA HILANG"}


def test_final_is_current_projection_and_preserves_full_lineage(tmp_path):
    archive, path = make_service(tmp_path)
    awal = archive.import_rows([row()], "DATA_AWAL")
    adjustment = archive.import_rows([row(**{"Total Tukin": 600})], "DATA_PENYESUAIAN")
    source = archive.list("DATA_AWAL")[0]
    archive.record_bpk_history("bpk-1", [{"archive_row_id": source["row_id"]}])
    final = archive.final()["rows"][0]
    assert final["initial_record_id"] == source["row_id"]
    assert final["tahun_sp2d"] == 2025
    assert final["latest_adjustment_record_id"] == archive.list("DATA_PENYESUAIAN")[0]["row_id"]
    assert final["nilai_awal"] == 35
    assert final["nilai_final"] == 35
    assert final["selisih"] == 0
    assert final["pernah_send_bpk"] is True
    assert final["bpk_batch"] == 1
    assert final["source_version"] == awal["import_id"]
    assert final["current_version"] == adjustment["import_id"]
    assert final["traceability"]["send_bpk"][0]["bpk_batch_label"] == "SEND BPK BATCH 1"
    conn = duckdb.connect(str(path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_archive_data_awal").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_archive_data_penyesuaian").fetchone()[0] == 1
    finally:
        conn.close()


def test_bpk_reconciliation_aggregate_and_export(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([row(), row(**{"NIP": "200"})], "DATA_AWAL")
    archive.import_rows([row(**{"Total Tukin": 600})], "DATA_PENYESUAIAN")
    awal_rows = archive.list("DATA_AWAL")
    archive.record_bpk_history("bpk-1", [{"archive_row_id": item["row_id"]} for item in awal_rows])
    result = archive.bpk_reconciliation()
    assert result["kpi"]["jumlah_sdm_awal_send_bpk"] == 2
    assert result["kpi"]["total_pengembalian_awal"] == 70
    assert result["kpi"]["total_pengembalian_final"] == 35
    assert result["kpi"]["selisih_nominal"] == -35
    assert result["kpi"]["pengurangan_kewajiban"] == 35
    assert result["kpi"]["jumlah_sdm_berubah"] == 1
    assert result["kpi"]["jumlah_tidak_berubah"] == 0
    assert result["kpi"]["data_baru"] == 0
    assert result["kpi"]["data_hilang"] == 1
    assert result["kpi"]["need_review"] == 0
    assert archive.export_xlsx(compare_result={"details": result["rows"]})


def test_bpk_reconciliation_uses_source_batch_and_returns_per_batch_summary(tmp_path):
    archive, _ = make_service(tmp_path)
    archive.import_rows([
        row(**{"NIP": "100", "Batch": "B1"}),
        row(**{"NIP": "200", "Batch": "Batch 1"}),
        row(**{"NIP": "300", "Batch": "2"}),
    ], "DATA_AWAL")
    archive.import_rows([
        row(**{"NIP": "100", "Batch": "B1", "Potongan SKP": 20}),
        row(**{"NIP": "200", "Batch": "Batch 1"}),
        row(**{"NIP": "300", "Batch": "2"}),
    ], "DATA_PENYESUAIAN")

    all_batches = archive.bpk_reconciliation()
    assert all_batches["available_batches"] == ["BATCH 1", "BATCH 2"]
    assert len(all_batches["batch_summaries"]) == 2

    batch_one = archive.bpk_reconciliation({"bpk_batch": 1})
    assert batch_one["selected_batch"] == "BATCH 1"
    assert batch_one["kpi"]["jumlah_sdm_awal_send_bpk"] == 2
    assert batch_one["kpi"]["jumlah_sdm_berubah"] == 1
    assert batch_one["kpi"]["jumlah_tidak_berubah"] == 1
    assert batch_one["kpi"]["status_summary"]["BERUBAH"]["selisih_nominal"] == 10
    assert {item["reconciliation_batch"] for item in batch_one["rows"]} == {"BATCH 1"}


def test_daily_compare_statuses_and_changed_fields(tmp_path):
    archive, path = make_service(tmp_path)
    migration = importlib.util.spec_from_file_location(
        "m024_daily", str(Path(__file__).resolve().parents[1] / "migrations" /
                          "024_create_pengembalian_dasar_harian_archive.py")
    )
    module = importlib.util.module_from_spec(migration)
    migration.loader.exec_module(module)
    module.main(str(path))
    conn = duckdb.connect(str(path))
    try:
        columns = ("record_id,nip,nama,tanggal,periode,jam_masuk,jam_pulang,"
                   "status_kehadiran,persentase_potongan_harian,nilai_potongan_harian,"
                   "nilai_tukin,dataset_type,import_id")
        conn.execute(
            f"""INSERT INTO pengembalian_dasar_harian_awal ({columns})
                VALUES ('a1','100','A','2025-01-01','2025-01','07:30','16:00',
                        'HADIR',5,50,1000,'DATA_DASAR_AWAL','i1')"""
        )
        conn.execute(
            f"""INSERT INTO pengembalian_dasar_harian_penyesuaian ({columns})
                VALUES ('b1','100','A','2025-01-01','2025-01','07:15','16:00',
                        'HADIR',3,30,1000,'DATA_DASAR_PENYESUAIAN','i2')"""
        )
        conn.execute(
            f"""INSERT INTO pengembalian_dasar_harian_penyesuaian ({columns})
                VALUES ('b2','100','A','2025-01-02','2025-01','07:30','16:00',
                        'HADIR',0,0,1000,'DATA_DASAR_PENYESUAIAN','i2')"""
        )
    finally:
        conn.close()
    result = archive.compare_daily("100", "2025-01")
    by_date = {item["tanggal"]: item for item in result["rows"]}
    assert by_date["2025-01-01"]["status"] == "BERUBAH"
    assert "jam_masuk" in by_date["2025-01-01"]["changed_fields"]
    assert by_date["2025-01-02"]["status"] == "BARU"
    assert len(archive.daily_detail("100", "2025-01")["tabs"]["perubahan_absensi"]) == 1
