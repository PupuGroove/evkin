from pathlib import Path
import importlib

import duckdb

from backend.tukin_annual import TukinAnnualService, _number, _rate
ensure_third_missing_skp_unpaid = importlib.import_module(
    "backend.migrations.041_enforce_third_missing_skp_unpaid"
).ensure_third_missing_skp_unpaid


def service(tmp_path: Path) -> TukinAnnualService:
    return TukinAnnualService(str(tmp_path / "annual.duckdb"))


def final_row(nip="198701012026011001"):
    return {
        "NIP": nip,
        "Nama": "ANI UJI",
        "Jabatan": "ANALIS",
        "Tukin": "Rp10,000,000",
        "Potongan Absensi e-Absensi (%)": "10,00%",
        "potongan absen final": "Rp300,000",
        "FINAL TUKIN DIBAYAR": "Rp9,700,000",
        "STATUS PEMBAYARAN": "dibayarkan",
        "NO REKENING": "001234567890",
    }


def test_localized_number_and_rate_parser():
    assert _number("Rp 3.915.950") == 3_915_950
    assert _number("Rp3,915,950") == 3_915_950
    assert _rate("3,00%") == 3
    assert _rate("0.03") == 3


def test_three_month_skp_streak_and_annual_export(tmp_path):
    svc = service(tmp_path)
    for month in ("2026-01", "2026-02", "2026-03", "2026-04"):
        svc.import_rows({"source_type": "FINAL", "assessment_period": month,
                         "source_file": "final.xlsx", "rows": [final_row()]})
        svc.import_rows({"source_type": "SKP", "assessment_period": month,
                         "source_file": "skp.xlsx", "rows": [{
                             "NIP": "198701012026011001", "Nama": "ANI UJI",
                             "Predikat Kinerja Periodik": "Tidak Mengerjakan SKP",
                         }]})
    svc.import_rows({"source_type": "FINAL", "assessment_period": "2026-05",
                     "source_file": "final.xlsx", "rows": [final_row()]})
    svc.import_rows({"source_type": "SKP", "assessment_period": "2026-05",
                     "source_file": "skp.xlsx", "rows": [{
                         "NIP": "198701012026011001", "Nama": "ANI UJI",
                         "Predikat Kinerja Periodik": "Baik",
                     }]})

    with svc.connect() as conn:
        skp = conn.execute(
            "SELECT consecutive_missing,skp_reduction_rate,payment_eligible "
            "FROM tukin_skp_monthly ORDER BY assessment_period"
        ).fetchall()
        final = conn.execute(
            "SELECT skp_deduction,paid_amount,payment_status,payment_reason "
            "FROM tukin_final_monthly ORDER BY assessment_period"
        ).fetchall()
    assert skp == [(1, 35, True), (2, 70, True), (3, 100, False), (4, 100, False), (0, 0, True)]
    assert [float(row[0]) for row in final] == [2_450_000, 4_900_000, 7_000_000, 7_000_000, 0]
    assert float(final[2][1]) == 0 and float(final[3][1]) == 0
    assert final[2][2] == "UNPAID" and final[3][2] == "UNPAID"
    assert "3 bulan berturut-turut atau lebih" in final[2][3]
    assert final[4][2] in {"READY_TO_PAY", "PAID"} and float(final[4][1]) == 9_700_000

    annual = svc.annual(2026)
    assert annual["total"] == 1
    assert annual["rows"][0]["semester_1"]["months_available"] == 5
    exported = svc.export_annual(2026).getvalue()
    assert exported[:2] == b"PK"
    assert len(exported) > 10_000


def test_migration_corrects_existing_open_third_month_but_preserves_locked_final(tmp_path):
    svc = service(tmp_path)
    nip = "198701012026011001"
    for month in ("2026-01", "2026-02", "2026-03"):
        svc.import_rows({"source_type": "FINAL", "assessment_period": month,
                         "source_file": "final.xlsx", "rows": [final_row(nip)]})
        svc.import_rows({"source_type": "SKP", "assessment_period": month,
                         "source_file": "skp.xlsx", "rows": [{
                             "NIP": nip, "Predikat Kinerja Periodik": "Tidak Membuat SKP",
                         }]})
    with svc.connect() as conn:
        conn.execute(
            """UPDATE tukin_final_monthly SET payment_status='HOLD',paid_amount=123,
                      payment_reason='aturan lama' WHERE assessment_period='2026-03'"""
        )
        ensure_third_missing_skp_unpaid(conn)
        corrected = conn.execute(
            "SELECT payment_status,paid_amount,payment_reason FROM tukin_final_monthly WHERE assessment_period='2026-03'"
        ).fetchone()
        conn.execute("UPDATE tukin_period SET status='LOCKED' WHERE assessment_period='2026-03'")
        conn.execute(
            """UPDATE tukin_final_monthly SET payment_status='HOLD',paid_amount=456,
                      payment_reason='keputusan terkunci' WHERE assessment_period='2026-03'"""
        )
        ensure_third_missing_skp_unpaid(conn)
        locked = conn.execute(
            "SELECT payment_status,paid_amount,payment_reason FROM tukin_final_monthly WHERE assessment_period='2026-03'"
        ).fetchone()
    assert corrected[0] == "UNPAID" and float(corrected[1]) == 0
    assert "Tukin tidak dibayarkan" in corrected[2]
    assert locked == ("HOLD", 456, "keputusan terkunci")


def test_maternity_full_and_partial_month_rules(tmp_path):
    svc = service(tmp_path)
    nip = "198701012026011001"
    svc.import_rows({"source_type": "FINAL", "assessment_period": "2026-08",
                     "source_file": "final.xlsx", "rows": [final_row(nip)]})
    svc.import_rows({"source_type": "SKP", "assessment_period": "2026-08",
                     "source_file": "skp.xlsx", "rows": [{
                         "NIP": nip, "Nama": "ANI UJI", "Predikat Kinerja Periodik": "Kurang"
                     }]})
    svc.import_rows({"source_type": "ATTENDANCE_DAILY", "assessment_period": "2026-08",
                     "source_file": "daily.xlsx", "rows": [
                         {"NIP": nip, "Tanggal": "2026-08-10", "Total Harian": "2%", "Alasan": "Terlambat"},
                         {"NIP": nip, "Tanggal": "2026-08-25", "Total Harian": "3%", "Alasan": "Tidak lengkap"},
                     ]})
    result = svc.add_condition({
        "assessment_period": "2026-08", "nip": nip,
        "condition_code": "CUTI_MELAHIRKAN", "effect_type": "EXEMPT_SKP",
        "start_date": "2026-08-01", "end_date": "2026-08-20", "reason": "Surat cuti",
    })
    assert result["effect_type"] == "EXEMPT_SKP"
    with svc.connect() as conn:
        row = conn.execute(
            "SELECT skp_deduction,attendance_reduction_rate,attendance_deduction "
            "FROM tukin_final_monthly WHERE assessment_period='2026-08' AND nip=?", [nip]
        ).fetchone()
    assert float(row[0]) == 0
    assert float(row[1]) == 3
    assert float(row[2]) == 90_000

    full = svc.add_condition({
        "assessment_period": "2026-08", "nip": nip,
        "condition_code": "CUTI_MELAHIRKAN", "effect_type": "REVIEW",
        "start_date": "2026-07-25", "end_date": "2026-09-15", "reason": "Surat cuti penuh",
    })
    assert full["effect_type"] == "EXEMPT_BOTH"
    with svc.connect() as conn:
        row = conn.execute(
            "SELECT skp_deduction,attendance_deduction,paid_amount "
            "FROM tukin_final_monthly WHERE assessment_period='2026-08' AND nip=?", [nip]
        ).fetchone()
    assert tuple(map(float, row)) == (0, 0, 10_000_000)


def test_mark_period_paid_records_payment_events(tmp_path):
    svc = service(tmp_path)
    svc.import_rows({"source_type": "FINAL", "assessment_period": "2026-07",
                     "source_file": "final.xlsx", "rows": [final_row()]})
    svc.lock_period("2026-07", "PAID")
    with duckdb.connect(str(tmp_path / "annual.duckdb")) as conn:
        assert conn.execute("SELECT payment_status FROM tukin_final_monthly").fetchone()[0] == "PAID"
        assert conn.execute("SELECT count(*) FROM tukin_payment_event").fetchone()[0] == 1
