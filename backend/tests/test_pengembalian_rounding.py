from backend.pengembalian_archive import ArchiveService, sum_preserving_round


def test_basic_and_identical_decimals():
    result = sum_preserving_round([100.4, 100.4, 100.2], ["A", "B", "C"])
    assert result["values"] == [101, 100, 100]
    assert result["rounded_total"] == 301
    assert result["difference"] == 0
    identical = sum_preserving_round([250000.25] * 4, ["A", "B", "C", "D"])
    assert sum(identical["values"]) == 1000001


def test_zero_null_blank_and_integer_are_locked():
    result = sum_preserving_round([100.40, 200.40, 300.20, 0, 0], list("ABCDE"))
    assert result["values"][3:] == [0, 0]
    assert result["zero_modified_count"] == 0
    mixed = sum_preserving_round([100.50, None, "", 200.50], list("ABCD"))
    assert mixed["values"][1:3] == [None, None]
    integers = sum_preserving_round([100000, 200000, 300000])
    assert integers["values"] == [100000, 200000, 300000]
    combined = sum_preserving_round([100000, 200000.40, 300000.60, 0, 400000])
    assert combined["values"] == [100000, 200000, 300001, 0, 400000]


def test_negative_and_deterministic():
    values = [-100.4, -100.4, -100.2]
    outputs = [sum_preserving_round(values, ["A", "B", "C"])["values"] for _ in range(5)]
    assert outputs == [[-100, -101, -100]] * 5
    forced = sum_preserving_round([10.75, 20.25], ["A", "B"], target_total=30)
    assert forced["values"] == [10, 20]


def test_service_reconciles_by_year_and_derives_totals():
    rows = [
        {"NIP": "A", "Tahun SP2D": 2025, "Tukin Pengembalian Oktober": 100000.40,
         "Tukin Pengembalian November": 0, "Tukin Pengembalian Desember": 0},
        {"NIP": "B", "Tahun SP2D": 2025, "Tukin Pengembalian Oktober": 200000.40,
         "Tukin Pengembalian November": 0, "Tukin Pengembalian Desember": 0},
        {"NIP": "C", "Tahun SP2D": 2025, "Tukin Pengembalian Oktober": 300000.20,
         "Tukin Pengembalian November": 0, "Tukin Pengembalian Desember": 0},
        {"NIP": "D", "Tahun SP2D": 2025, "Tukin Pengembalian Oktober": 0},
    ]
    preview = ArchiveService().validate(rows)
    normalized = preview["rows"]
    assert sum(row["tukin_pengembalian_oktober"] for row in normalized) == 600001
    assert normalized[-1]["tukin_pengembalian_oktober"] == 0
    assert all(isinstance(row["total_awal_tukin"], int) for row in normalized)
    assert preview["rounding_reconciliation"]["zero_modified_count"] == 0
    assert normalized[0]["_raw_data"]["Tukin Pengembalian Oktober"] == 100000.40
    assert normalized[0]["_bnba_normalized"]["rounding_audit"]


def test_large_dataset_is_reconciled():
    values = [100.25] * 100_001
    result = sum_preserving_round(values, range(len(values)))
    assert result["rounded_total"] == 10_025_100
    assert result["difference"] == 0
    assert all(isinstance(value, int) for value in result["values"])
