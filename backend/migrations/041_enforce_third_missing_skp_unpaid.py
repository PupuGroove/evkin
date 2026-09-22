"""Migration 041: month three and later without SKP is unpaid."""
from pathlib import Path
import os

import duckdb


def ensure_third_missing_skp_unpaid(conn: duckdb.DuckDBPyConnection) -> None:
    config_table = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name='skp_rule_config'"
    ).fetchone()
    if config_table:
        conn.execute(
            """UPDATE skp_rule_config
               SET third_month_action='UNPAID',third_month_rate=100,
                   updated_by='SYSTEM-MIGRATION-041',updated_at=now()
               WHERE id='DEFAULT' AND third_month_action<>'UNPAID'"""
        )
    tables = {
        row[0] for row in conn.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_name IN ('tukin_skp_monthly','tukin_final_monthly','tukin_period')"""
        ).fetchall()
    }
    if "tukin_skp_monthly" in tables:
        conn.execute(
            """UPDATE tukin_skp_monthly
               SET skp_reduction_rate=100,payment_eligible=false,updated_at=now()
               WHERE report_status='NOT_SUBMITTED_VERIFIED' AND consecutive_missing>=3"""
        )
    if {"tukin_skp_monthly", "tukin_final_monthly", "tukin_period"} <= tables:
        conn.execute(
            """UPDATE tukin_final_monthly AS f SET
                   skp_reduction_rate=100,
                   skp_deduction=round(f.tukin_gross*.70*100/100),
                   total_deduction=f.attendance_deduction+round(f.tukin_gross*.70*100/100)-f.manual_adjustment,
                   calculated_entitlement=greatest(0,f.tukin_gross-(f.attendance_deduction+round(f.tukin_gross*.70*100/100)-f.manual_adjustment)),
                   paid_amount=0,payment_status='UNPAID',
                   payment_reason='Tidak membuat laporan SKP 3 bulan berturut-turut atau lebih - Tukin tidak dibayarkan',
                   updated_at=now()
               FROM tukin_skp_monthly AS s JOIN tukin_period AS p
                 ON p.assessment_period=s.assessment_period
               WHERE f.assessment_period=s.assessment_period AND f.nip=s.nip
                 AND s.report_status='NOT_SUBMITTED_VERIFIED' AND s.consecutive_missing>=3
                 AND p.status NOT IN ('HISTORICAL_LOCKED','LOCKED','PAID')
                 AND coalesce(f.death_record_id,'')=''
                 AND NOT EXISTS (
                     SELECT 1 FROM tukin_condition c
                     WHERE c.assessment_period=f.assessment_period AND c.nip=f.nip
                       AND c.effect_type IN ('HOLD','UNPAID')
                 )"""
        )


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_third_missing_skp_unpaid(conn)
    print(f"Migration 041 applied: third consecutive missing SKP is UNPAID at {db_path}")


if __name__ == "__main__":
    main()
