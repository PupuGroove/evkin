from io import BytesIO

import duckdb
import pandas as pd

from backend.pengembalian_archive import ArchiveService
from backend.pengembalian_progress import ProgressService
from backend.duckdb_maintenance import clear_tables_without_secondary_indexes


def test_safe_reset_temporarily_removes_and_restores_indexes(tmp_path):
    path = tmp_path / "safe-reset.duckdb"
    import duckdb

    conn = duckdb.connect(str(path))
    try:
        conn.execute("CREATE TABLE wide_archive (nip TEXT, tahun INTEGER, payload TEXT)")
        conn.execute("CREATE INDEX idx_wide_archive_key ON wide_archive(nip, tahun)")
        conn.executemany(
            "INSERT INTO wide_archive VALUES (?, ?, ?)",
            [(f"19800101202521{i:04d}", 2025, "x" * 1000) for i in range(2500)],
        )

        result = clear_tables_without_secondary_indexes(conn, ["wide_archive"])

        assert result["deleted_rows"] == 2500
        assert conn.execute("SELECT COUNT(*) FROM wide_archive").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM duckdb_indexes() WHERE index_name='idx_wide_archive_key'"
        ).fetchone()[0] == 1
        # Reset is idempotent and keeps the restored index intact.
        assert clear_tables_without_secondary_indexes(conn, ["wide_archive"])["deleted_rows"] == 0
    finally:
        conn.close()


def combined_row(nip="100", initial=100_000, final=100_000):
    return {
        "NIP": nip, "Tahun SP2D": 2025, "Komponen": "TUKIN",
        "Tukin Pengembalian Oktober": initial,
        "Final Pengembalian Tukin Oktober": final,
        "Total Awal Tukin": initial,
        "Final Total Pengembalian Tukin": final,
    }


def test_master_reset_also_clears_final_progress_and_periods(tmp_path):
    path = tmp_path / "master-reset.duckdb"
    archive = ArchiveService(str(path))
    archive.create_period({
        "periode_id": "RET-SAFE", "nama_periode": "Periode Reset",
        "tahun": 2026, "bulan_awal": 1, "bulan_akhir": 12,
    })
    archive.import_bnba_combined(
        [combined_row("RESET-1")],
        {"periode_id": "RET-SAFE", "file_hash": "reset-master"},
    )
    progress = ProgressService(str(path))
    progress.backfill()
    progress.preview(
        [{
            "NIP": "RESET-1", "Tahun SP2D": 2025, "Nama Bank": "BRI",
            "Periode Debit": "Agustus 2026", "Tanggal Debit": "01/08/2026",
            "Status Debit": "BERHASIL", "Debit Tukin": 10_000,
            "Debit Uang Makan": 0,
        }],
        {"filename": "progress.xlsx", "file_hash": "reset-progress"},
    )
    conn = duckdb.connect(str(path))
    period_count_before = conn.execute("SELECT COUNT(*) FROM pengembalian_period").fetchone()[0]
    assert period_count_before > 0
    conn.close()

    result = archive.clear_database()

    progress_tables = {
        "pengembalian_progress_staging",
        "pengembalian_progress_transaction",
        "pengembalian_progress_import_batch",
        "pengembalian_progress_bulanan",
        "pengembalian_payment_transaction",
        "pengembalian_sp2d_lineage",
        "pengembalian_obligation",
    }
    assert progress_tables.issubset(result["deleted_tables"])
    assert result["deleted_tables"]["pengembalian_final"] == 1
    conn = duckdb.connect(str(path))
    try:
        for table in progress_tables | {"pengembalian_final", "pengembalian_archive_import"}:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pengembalian_period").fetchone()[0] == 0
    finally:
        conn.close()


def test_delete_period_removes_configuration_but_keeps_historical_archive(tmp_path):
    service = ArchiveService(str(tmp_path / "delete-period.duckdb"))
    service.create_period({
        "periode_id": "RET-2026-01-03", "nama_periode": "Januari-Maret 2026",
        "tahun": 2026, "bulan_awal": 1, "bulan_akhir": 3,
    })
    service.import_bnba_combined(
        [combined_row("PERIOD-1")],
        {"periode_id": "RET-2026-01-03", "file_hash": "period-history"},
    )

    result = service.delete_period("RET-2026-01-03")

    assert result["deleted_rows"] == 1
    assert all(row["periode_id"] != "RET-2026-01-03" for row in service.periods())
    assert service.final({"periode_id": "RET-2026-01-03"})["total"] == 1


def test_delete_archive_row_only_removes_selected_row_and_empty_import(tmp_path):
    service = ArchiveService(str(tmp_path / "delete-archive-row.duckdb"))
    first = service.import_rows([
        {"NIP": "100", "Nama": "Satu", "Tahun SP2D": 2026, "Total Tukin": 1000},
        {"NIP": "200", "Nama": "Dua", "Tahun SP2D": 2026, "Total Tukin": 2000},
    ], "DATA_AWAL", {"filename": "awal.xlsx"})
    rows = service.list("DATA_AWAL")

    deleted = service.delete_archive_row(rows[0]["row_id"], "DATA_AWAL")
    assert deleted["deleted_tables"]["pengembalian_archive_data_awal"] == 1
    assert len(service.list("DATA_AWAL")) == 1
    assert service.history("DATA_AWAL")["imports"][0]["import_id"] == first["import_id"]

    service.delete_archive_row(rows[1]["row_id"], "DATA_AWAL")
    assert service.list("DATA_AWAL") == []
    assert service.history("DATA_AWAL")["imports"] == []


def test_batch_bpk_aliases_and_rupiah_comparison_are_canonical():
    for header in ("batch", "Batch", "BATCH", "Batch BPK", "BATCH BPK", "batch_bpk", "batch bpk"):
        normalized = ArchiveService.normalize_row({header: "BATCH 1 SEND BPK"})
        assert normalized["batch"] == "BATCH 1 SEND BPK"
    assert ArchiveService.normalize_row({"Batch BPK": 0})["batch"] == 0
    assert ArchiveService.normalize_row({"Total Awal Tukin": "Rp1.000.000"})["total_awal_tukin"] == 1_000_000


def test_dashboard_business_status_sp2d_batch_and_invariants(tmp_path):
    service = ArchiveService(str(tmp_path / "comparison-dashboard.duckdb"))
    rows = [
        {**combined_row("A", 1_000_000, 1_000_000), "Tahun SP2D": 2025, "Batch BPK": "BATCH 1 SEND BPK"},
        {**combined_row("B", 1_000_000, 750_000), "Tahun SP2D": 2025, "Batch BPK": "BATCH 1 SEND BPK"},
        {**combined_row("C", 1_000_000, 1_250_000), "Tahun SP2D": 2025, "Batch BPK": "TAHAP 2 PEMUKTAHIRAN"},
        {**combined_row("D", 1_000_000, 1_000_000), "Tahun SP2D": 2026, "Batch BPK": "BATCH 2"},
    ]
    service.import_bnba_combined(rows, {"periode_id": "RET-AUDIT", "file_hash": "dashboard-audit"})

    final = {row["nip"]: row for row in service.final()["rows"]}
    assert final["A"]["batch"] == "BATCH 1 SEND BPK"
    assert final["A"]["status_compare"] == "TIDAK BERUBAH"
    assert final["A"]["arah_perubahan"] == "TETAP"
    assert final["B"]["status_compare"] == "BERUBAH"
    assert final["B"]["arah_perubahan"] == "TURUN"
    assert final["B"]["selisih"] == -250_000
    assert final["B"]["pengurangan_total"] == 250_000
    assert final["C"]["arah_perubahan"] == "NAIK"
    assert set(final["C"]["changed_fields"]) == {
        "final_pengembalian_tukin_oktober", "final_total_pengembalian_tukin"
    }

    dashboard = service.dashboard({"source": "DATA_FINAL"})
    assert (dashboard["total_sdm"], dashboard["sdm_berubah"], dashboard["sdm_tidak_berubah"]) == (4, 2, 2)
    assert (dashboard["total_naik"], dashboard["total_turun"]) == (1, 1)
    assert dashboard["invariants"] == {"status_ok": True, "direction_ok": True, "nominal_ok": True}
    assert {row["tahun_sp2d"]: row["total_sdm"] for row in dashboard["sp2d_summary"]} == {2025: 3, 2026: 1}
    groups = {(row["tahun_sp2d"], row["batch"]): row["total_sdm"] for row in dashboard["batch_summary"]}
    assert groups[(2025, "BATCH 1 SEND BPK")] == 2
    assert groups[(2025, "TAHAP 2 PEMUKTAHIRAN")] == 1
    assert groups[(2026, "BATCH 2")] == 1
    filtered = service.dashboard({"source": "DATA_FINAL", "tahun_sp2d": 2025,
                                  "batch": "BATCH 1 SEND BPK", "status_perubahan": "BERUBAH",
                                  "arah_perubahan": "TURUN"})
    assert filtered["total_sdm"] == filtered["sdm_berubah"] == filtered["total_turun"] == 1


def test_single_import_period_and_required_change_flags(tmp_path):
    service = ArchiveService(str(tmp_path / "v2.duckdb"))
    service.import_bnba_combined([
        combined_row("A", 100_000, 100_000),
        combined_row("B", 100_000, 80_000),
        combined_row("C", 100_000, 0),
        combined_row("D", 0, 50_000),
    ], {"periode_id": "RET-2025-10-12", "file_hash": "flags"})

    rows = {row["nip"]: row for row in service.final()["rows"]}
    assert rows["A"]["klasifikasi_oktober"] == "TIDAK BERUBAH"
    assert rows["B"]["klasifikasi_oktober"] == "TURUN"
    assert rows["B"]["selisih_oktober"] == -20_000
    assert rows["B"]["pengurangan_oktober"] == 20_000
    assert rows["C"]["klasifikasi_oktober"] == "MENJADI 0"
    assert rows["D"]["klasifikasi_oktober"] == "DARI 0 MENJADI ADA"
    assert all(row["periode_id"] == "RET-2025-10-12" for row in rows.values())


def test_dynamic_dataset_round_trip_excel(tmp_path):
    service = ArchiveService(str(tmp_path / "dataset.duckdb"))
    source = [{"Kolom Bebas": "A", "Nilai": 10}, {"Kolom Bebas": "B", "Nilai": 20}]
    result = service.import_dataset(source, {
        "periode_id": "RET-2025-10-12", "filename": "bebas.xlsx", "sheet_name": "DATA"
    })
    stored = service.dataset_rows(result["dataset_id"])
    assert stored["rows"] == source
    exported = pd.read_excel(BytesIO(service.export_dataset_xlsx(result["dataset_id"])))
    assert len(exported) == 2
    assert list(exported.columns) == ["Kolom Bebas", "Nilai"]


def test_success_failed_payment_progress_and_status(tmp_path):
    service = ArchiveService(str(tmp_path / "payment.duckdb"))
    service.import_bnba_combined([combined_row("100", 900_000, 900_000)], {
        "periode_id": "RET-2025-10-12", "file_hash": "payment-master"
    })
    key = service.final()["rows"][0]["comparison_key"]
    service.import_payments([
        {"NIP": "100", "obligation_key": key, "tanggal": "2026-07-01", "nominal": 300_000, "status": "BERHASIL"},
        {"NIP": "100", "obligation_key": key, "tanggal": "2026-08-01", "nominal": 300_000, "status": "GAGAL", "alasan": "Saldo Tidak Cukup"},
    ])
    progress = service.repayment_progress()["rows"][0]
    assert progress["berhasil_debit"] == 300_000
    assert progress["gagal_debit"] == 300_000
    assert progress["sisa_piutang"] == 600_000
    assert progress["status"] == "SEBAGIAN"
    service.import_payments([
        {"NIP": "100", "obligation_key": key, "tanggal": "2026-09-01", "nominal": 600_000, "status": "SUCCESS"},
    ])
    final_progress = service.repayment_progress()["rows"][0]
    assert final_progress["sisa_piutang"] == 0
    assert final_progress["status"] == "LUNAS"


def test_final_excel_count_and_filtered_values_match_database(tmp_path):
    service = ArchiveService(str(tmp_path / "export.duckdb"))
    service.import_bnba_combined([
        combined_row("A", 100, 80), combined_row("B", 100, 100)
    ], {"periode_id": "RET-2025-10-12", "file_hash": "export"})

    all_rows = service.final()["rows"]
    workbook = pd.ExcelFile(BytesIO(service.export_xlsx("DATA_FINAL")))
    exported = pd.read_excel(workbook, sheet_name="BNBA PENGEMBALIAN ALL SDM")
    filtered = pd.read_excel(BytesIO(service.export_xlsx(
        "DATA_FINAL", {"flag_ada_perubahan": "BERUBAH"}
    )), sheet_name="BNBA PENGEMBALIAN ALL SDM")

    assert len(exported) == len(all_rows) == 2
    assert len(filtered) == 1
    assert filtered.iloc[0]["NIP"] == "A"
    assert filtered.iloc[0]["Selisih Oktober"] == -20
