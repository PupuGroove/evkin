from backend.pengembalian_archive import ArchiveService


PERIOD = "RET-2025-10-12"


def _service(tmp_path):
    service = ArchiveService(str(tmp_path / "dasar-absensi.duckdb"))
    service.create_period({
        "periode_id": PERIOD,
        "nama_periode": "Oktober-Desember 2025",
        "tahun": 2025,
        "bulan_awal": 10,
        "bulan_akhir": 12,
    })
    service.import_bnba_combined([{
        "NIP": "42",
        "Nama": "Pegawai Uji",
        "Tahun SP2D": 2025,
        "Komponen": "TUKIN",
        "Total Tukin": 1_000_000,
        "Tukin Pengembalian Oktober": 0,
        "Final Pengembalian Tukin Oktober": 0,
        "Final Pengembalian Tukin November": 0,
        "Final Pengembalian Tukin Desember": 0,
        "Final Total Pengembalian Tukin": 0,
    }], {"periode_id": PERIOD, "file_hash": "bnba-test"})
    return service


def _recap(service, sheet, value):
    return service.import_dataset(
        [{"NIP": "42", "Sum of Total Potongan (%)": value}],
        {"periode_id": PERIOD, "filename": "absensi.xlsx", "sheet_name": sheet,
         "jenis_dataset": "DATA_DASAR_PERHITUNGAN_REKAP"},
    )


def test_rekap_is_materialized_and_attached_to_final_detail(tmp_path):
    service = _service(tmp_path)
    for sheet in ("REKAP OKT", "REKAP NOV", "REKAP DES"):
        _recap(service, sheet, 0.1)

    row = service.final({"nip": "42", "periode_id": PERIOD})["rows"][0]
    basis = row["dasar_perhitungan_absensi"]

    assert basis["status"] == "VALID"
    assert basis["tukin_absen_30"] == 300_000
    assert basis["nominal_dasar_total"] == 90_000
    assert [basis["months"][month]["nominal_dasar"]
            for month in ("oktober", "november", "desember")] == [30_000] * 3
    assert row["nilai_final"] == 0  # derived basis never overwrites the official final

    tabs = service.daily_detail("42", period_id=PERIOD)["tabs"]
    assert len(tabs["data_dasar_rekap"]["rows"]) == 3
    assert tabs["dasar_perhitungan_absensi"]["rows"][0]["nominal_dasar_total"] == 90_000


def test_source_error_is_preserved_and_not_treated_as_zero(tmp_path):
    service = _service(tmp_path)
    _recap(service, "REKAP OKT", 0.1)
    _recap(service, "REKAP NOV", "#VALUE!")
    _recap(service, "REKAP DES", 0.1)

    basis = service.final({"nip": "42"})["rows"][0]["dasar_perhitungan_absensi"]
    november = basis["months"]["november"]

    assert basis["status"] == "ERROR"
    assert november["persentase_potongan"] is None
    assert november["nominal_dasar"] is None
    assert any("#VALUE!" in issue for issue in basis["issues"])
