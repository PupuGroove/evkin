import duckdb

from backend.pengembalian_archive import ArchiveService


def test_empty_totals_remain_null_while_explicit_zero_is_preserved():
    empty = ArchiveService.normalize_row({"NIP": "42"})
    zero = ArchiveService.normalize_row({
        "NIP": "42",
        "Total Awal Tukin": 0,
        "Final Total Pengembalian Tukin": 0,
    })

    assert empty["total_awal_tukin"] is None
    assert empty["final_total_pengembalian_tukin"] is None
    assert empty["selisih_total_tukin"] is None
    assert zero["total_awal_tukin"] == 0
    assert zero["final_total_pengembalian_tukin"] == 0
    assert zero["selisih_total_tukin"] == 0


def test_final_projection_falls_back_to_generic_total_without_inventing_zero(tmp_path):
    service = ArchiveService(str(tmp_path / "empty-vs-zero.duckdb"))
    service.import_rows([
        {"NIP": "42", "Total Pengembalian": 125},
        {"NIP": "43", "Total Pengembalian": 0},
    ], "DATA_AWAL")

    rows = {row["nip"]: row for row in service.final()["rows"]}

    assert rows["42"]["nilai_awal"] == 125
    assert rows["42"]["nilai_final"] == 125
    assert rows["43"]["nilai_awal"] == 0
    assert rows["43"]["nilai_final"] == 0


def test_preview_infers_period_id_from_excel_month_columns():
    service = ArchiveService()
    preview = service.preview([
        {"NIP": "42", "Nama Pegawai": "Sari", "Tahun": 2025, "Bulan": 2, "Total Pengembalian": 100}
    ], "DATA_AWAL")

    assert preview["metadata"]["periode_id"] == "RET-2025-02-02"
    assert preview["rows"][0]["periode_id"] == "RET-2025-02-02"


def test_normalize_period_accepts_month_names():
    assert ArchiveService.normalize_row({"NIP": "42", "Periode": "Januari 2025"})["periode"] == "2025-01"


def test_tolerant_bnba_headers_are_normalized_and_derived_flags_persist(tmp_path):
    service = ArchiveService(str(tmp_path / "bnba.duckdb"))
    source = {
        "No NIP": " 42 ",
        "Nama Pegawai": "Sari",
        "Tahun SP2D": "2025",
        "Tahun-Bulan": "2025-02",
        "Nomor Batch": "batch 2",
        "Kabupaten": "Bandung",
        "Total Pengembalian": "1.234,50",
        "Kolom Baru Dari BNBA": "tetap tersimpan",
    }
    service.import_rows([source], "DATA_AWAL")
    row = service.list("DATA_AWAL")[0]
    assert row["nip"] == "42"
    assert row["kabupaten_kota"] == "Bandung"
    assert row["normalized_batch"] == "BATCH-2"
    assert row["is_monthly"] is True
    assert row["is_total"] is True
    assert row["raw_data"]["Kolom Baru Dari BNBA"] == "tetap tersimpan"
    # Operational archive values are integer Rupiah after import reconciliation.
    assert service.aggregate(group_by=("periode",))[0]["total_potongan_tukin"] == 1235


def test_projection_columns_are_available_on_legacy_archive(tmp_path):
    path = tmp_path / "schema.duckdb"
    service = ArchiveService(str(path))
    service.repository.ensure_schema()
    conn = duckdb.connect(str(path))
    try:
        columns = {item[1] for item in conn.execute(
            "PRAGMA table_info('pengembalian_archive_data_awal')"
        ).fetchall()}
    finally:
        conn.close()
    assert {"bnba_normalized", "normalized_batch", "is_monthly", "is_total",
            "provinsi", "kabupaten_kota", "kdanaksatker"} <= columns


def test_final_aggregate_uses_total_awal_pengembalian_not_total_tukin(tmp_path):
    service = ArchiveService(str(tmp_path / "final-aggregate.duckdb"))
    service.import_rows([{
        "NIP": "42",
        "Tahun SP2D": 2025,
        "Total Tukin": 3_000,
        "Total Awal Tukin": 125,
        "Total Pengembalian": 100,
    }], "DATA_AWAL")

    aggregate = service.aggregate("DATA_FINAL", group_by=("tahun_sp2d",))[0]

    assert aggregate["total_awal_tukin"] == 125
    assert aggregate["total_potongan_tukin"] == 100
    assert "total_tukin" not in aggregate


def test_final_projection_supports_bnba_quick_filter_fields(tmp_path):
    service = ArchiveService(str(tmp_path / "final.duckdb"))
    initial = {
        "No NIP": "42",
        "Nama Pegawai": "Sari",
        "Periode": "2025-02",
        "Total Awal Tukin": "100",
        "Total Pengembalian": "100",
        "Tukin Pengembalian Oktober": "100",
        "Final Pengembalian Tukin Oktober": "100",
        "Final Bacth Tahap 1": "Batch 1",
    }
    adjustment = dict(initial)
    adjustment["Final Pengembalian Tukin Oktober"] = "125"
    adjustment["Total Pengembalian"] = "125"
    service.import_rows([initial], "DATA_AWAL")
    service.import_rows([adjustment], "DATA_PENYESUAIAN")

    changed = service.final({"flag_ada_perubahan": "BERUBAH"})["rows"]
    batch_one = service.final({"final_batch_normalized": "BATCH 1"})["rows"]

    assert len(changed) == 1
    assert changed[0]["arah_perubahan"] == "NAIK"
    assert len(batch_one) == 1
    dashboard = service.dashboard({"source": "DATA_FINAL", "flag_ada_perubahan": "BERUBAH"})
    assert dashboard["total"] == 1
    assert dashboard["sdm_berubah"] == 1


def test_final_projection_can_select_rows_for_export(tmp_path):
    service = ArchiveService(str(tmp_path / "selected.duckdb"))
    rows = [
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100"},
        {"No NIP": "43", "Nama Pegawai": "Budi", "Total Pengembalian": "200"},
    ]
    service.import_rows(rows, "DATA_AWAL")
    final_rows = service.final()["rows"]
    selected = service.final({"record_ids": final_rows[0]["record_id"]})["rows"]

    assert len(selected) == 1
    assert selected[0]["identity"]["nip"] == "42"


def test_final_dashboard_counts_unchanged_rows_with_display_status(tmp_path):
    service = ArchiveService(str(tmp_path / "dashboard.duckdb"))
    row = {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100"}
    service.import_rows([row], "DATA_AWAL")
    service.import_rows([row], "DATA_PENYESUAIAN")

    dashboard = service.dashboard({"source": "DATA_FINAL"})

    assert dashboard["total"] == 1
    assert dashboard["sdm_berubah"] == 0
    assert dashboard["sdm_tidak_berubah"] == 1


def test_final_dashboard_does_not_let_source_flag_hide_numeric_change(tmp_path):
    service = ArchiveService(str(tmp_path / "dashboard-flaging.duckdb"))
    service.import_rows([
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100"},
        {"No NIP": "43", "Nama Pegawai": "Budi", "Total Pengembalian": "100"},
    ], "DATA_AWAL")
    service.import_rows([
        # A positive source flag is retained, but a negative flag must not hide
        # a monetary change proven by the normalized values.
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100", "Flaging": "BERUBAH"},
        {"No NIP": "43", "Nama Pegawai": "Budi", "Total Pengembalian": "150", "Flaging": "TIDAK BERUBAH"},
    ], "DATA_PENYESUAIAN")

    final_rows = {row["identity"]["nip"]: row for row in service.final()["rows"]}
    dashboard = service.dashboard({"source": "DATA_FINAL"})

    assert final_rows["42"]["flag_ada_perubahan"] == "BERUBAH"
    assert final_rows["43"]["flag_ada_perubahan"] == "BERUBAH"
    assert dashboard["sdm_berubah"] == 2
    assert dashboard["sdm_tidak_berubah"] == 0


def test_materialized_dashboard_and_final_filter_recover_stale_negative_flag(tmp_path):
    service = ArchiveService(str(tmp_path / "dashboard-stale-flag.duckdb"))
    service.import_rows(
        [{"No NIP": "99", "Nama Pegawai": "Stale", "Total Pengembalian": "100"}],
        "DATA_AWAL",
    )
    service.import_rows(
        [{"No NIP": "99", "Nama Pegawai": "Stale", "Total Pengembalian": "150"}],
        "DATA_PENYESUAIAN",
    )
    conn = service.repository.connect()
    conn.execute("""UPDATE pengembalian_final SET flag_ada_perubahan='TIDAK BERUBAH',
        status_compare='TIDAK BERUBAH',ada_perubahan='TIDAK',
        row_json=json_merge_patch(row_json,'{"flag_ada_perubahan":"TIDAK BERUBAH","status_compare":"TIDAK BERUBAH","status_perubahan":"TIDAK BERUBAH","ada_perubahan":"TIDAK"}')""")
    service.repository.close(conn)

    dashboard = service.dashboard({"source": "DATA_FINAL"})
    changed = service.final({"status_perubahan": "BERUBAH"})
    unchanged = service.final({"status_perubahan": "TIDAK BERUBAH"})

    assert (dashboard["sdm_berubah"], dashboard["sdm_tidak_berubah"]) == (1, 0)
    assert dashboard["invariants"]["direction_ok"] is True
    assert changed["total"] == 1
    assert changed["rows"][0]["status_compare"] == "BERUBAH"
    assert unchanged["total"] == 0


def test_import_rows_materializes_saved_final_snapshot(tmp_path):
    service = ArchiveService(str(tmp_path / "materialized-final.duckdb"))
    service.import_rows([
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100"},
    ], "DATA_AWAL", {"periode_id": "RET-2025-01"})
    service.import_rows([
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "125"},
    ], "DATA_PENYESUAIAN", {"periode_id": "RET-2025-01"})

    final = service.final()

    assert final["materialized"] is True
    assert len(final["rows"]) == 1
    assert final["rows"][0]["nilai_final"] == 125


def test_final_filters_support_multiple_values_with_and_across_fields(tmp_path):
    service = ArchiveService(str(tmp_path / "multi-filter.duckdb"))
    service.import_rows([
        {"No NIP": "42", "Nama Pegawai": "Sari", "Periode": "2025-01", "Total Pengembalian": "100"},
        {"No NIP": "43", "Nama Pegawai": "Budi", "Periode": "2025-02", "Total Pengembalian": "100"},
        {"No NIP": "44", "Nama Pegawai": "Dewi", "Periode": "2025-03", "Total Pengembalian": "100"},
    ], "DATA_AWAL")

    result = service.final({"nip": "42,43", "periode": "2025-02,2025-03"})

    assert [row["identity"]["nip"] for row in result["rows"]] == ["43"]


def test_upsert_mode_deduplicates_incoming_snapshot_without_overwriting_archive(tmp_path):
    service = ArchiveService(str(tmp_path / "upsert.duckdb"))
    result = service.import_rows([
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "100"},
        {"No NIP": "42", "Nama Pegawai": "Sari", "Total Pengembalian": "125"},
    ], "DATA_AWAL", {"import_mode": "UPSERT"})

    assert result["import_mode"] == "UPSERT"
    assert result["total"] == 1
    assert service.list("DATA_AWAL")[0]["total_potongan_tukin"] == 125


def test_final_is_read_only_and_cannot_be_imported(tmp_path):
    service = ArchiveService(str(tmp_path / "readonly.duckdb"))

    try:
        service.import_rows([{"No NIP": "42", "Total Pengembalian": "100"}], "DATA_FINAL")
    except ValueError as exc:
        assert "projection" in str(exc)
    else:
        raise AssertionError("DATA_FINAL import should be rejected")


def test_bnba_update_year_is_used_as_sp2d_identity_and_preview_uses_final_total(tmp_path):
    service = ArchiveService(str(tmp_path / "bnba-source.duckdb"))
    row = {
        "NIP": "19870001",
        "Nama sk": "Budi",
        "Tahun Sp2d UPDATE": 2025,
        "Total Awal Tukin": "1000",
        "FINAL TOTAL PENGEMBALIAN TUKIN": "800",
        "FINAL TOTAL PENGEMBALIAN UANG MAKAN": "200",
    }

    preview = service.preview([row], "DATA_AWAL")

    assert preview["valid"] is True
    assert preview["rows"][0]["tahun_sp2d"] == 2025
    # Combined total is derived from rounded Tukin + Uang Makan details.
    assert preview["total_pengembalian"] == 1000


def test_combined_bnba_import_archives_initial_and_final_columns_separately(tmp_path):
    service = ArchiveService(str(tmp_path / "combined.duckdb"))
    row = {
        "NIP": "19870001",
        "Nama sk": "Budi",
        "Tahun Sp2d": 2025,
        "Tukin Pengembalian Oktober": 100,
        "Final Pengembalian Tukin Oktober": 75,
        "Total Awal Tukin": 100,
        "FINAL TOTAL PENGEMBALIAN TUKIN": 75,
    }

    result = service.import_bnba_combined([row], {"file_hash": "combined-1"})

    assert result["embedded_final_columns"] is True
    assert len(service.list("DATA_AWAL")) == 1
    assert len(service.list("DATA_PENYESUAIAN")) == 1
    final = service.final()["rows"]
    assert final[0]["flag_ada_perubahan"] == "BERUBAH"
    assert final[0]["selisih_oktober"] == -25
