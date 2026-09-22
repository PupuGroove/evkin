"""
Rekonsiliasi script for Master Pengembalian.

Usage:
  python backend\tools\rekonsiliasi.py --db <path/to/EVKIN_MASTER.duckdb> --outdir ./reports --case-id RET-2026-07-abc123 --compare-a pengembalian_bpk_detail --compare-b pengembalian_bank_detail --keys nip,periode,komponen

Requirements:
  pip install duckdb pandas

What it does:
  - Runs a collection of read-only DuckDB queries that help reconcile stages:
    History Awal -> Dasar Perhitungan -> Send BPK -> Send Bank -> Result Bank -> History
  - Exports results as CSV files into the specified output directory.
  - Graceful when tables are missing; it will skip and continue.

"""
import os
import argparse
import datetime
from pathlib import Path

try:
    import duckdb
    import pandas as pd
except Exception as e:
    raise RuntimeError('Dependencies missing: pip install duckdb pandas') from e


DEFAULT_DB = os.environ.get('EVKIN_DUCKDB_PATH') or str(Path(__file__).resolve().parent.parent / 'data' / 'EVKIN_MASTER.duckdb')


def now_ts():
    return datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')


def ensure_outdir(base: str):
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_query(conn, sql: str, params: tuple = ()):  # returns DataFrame or None
    try:
        if params:
            df = conn.execute(sql, params).df()
        else:
            df = conn.execute(sql).df()
        return df
    except Exception as e:
        print(f"[SKIP] Query failed or table missing: {e}")
        return None


def q_per_case_sisa():
    return """
WITH ha AS (
  SELECT case_id, nip, periode, komponen, MAX(nominal_awal) AS nominal_awal
  FROM pengembalian_history_awal
  GROUP BY case_id, nip, periode, komponen
),
dlatest AS (
  SELECT p.*
  FROM pengembalian_dasar_perhitungan p
  JOIN (
    SELECT case_id, MAX(calculated_at) AS maxt
    FROM pengembalian_dasar_perhitungan
    GROUP BY case_id
  ) m ON m.case_id = p.case_id AND m.maxt = p.calculated_at
),
realisasi AS (
  SELECT case_id, SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS total_valid_realisasi,
                 SUM(amount) AS position_from_history
  FROM pengembalian_tukin_history
  GROUP BY case_id
)
SELECT
  COALESCE(dlatest.case_id, ha.case_id) AS case_id,
  COALESCE(ha.nip, dlatest.nip) AS nip,
  COALESCE(dlatest.nominal_pengembalian, ha.nominal_awal, 0) AS kewajiban_final,
  COALESCE(realisasi.total_valid_realisasi, 0) AS total_realisasi_valid,
  COALESCE(dlatest.nominal_pengembalian, ha.nominal_awal, 0) - COALESCE(realisasi.total_valid_realisasi, 0) AS sisa_per_case,
  COALESCE(realisasi.position_from_history, 0) AS current_position_from_history
FROM ha
LEFT JOIN dlatest ON dlatest.case_id = ha.case_id
LEFT JOIN realisasi ON realisasi.case_id = ha.case_id
ORDER BY sisa_per_case DESC
"""


def q_nominal_change_history_vs_dasar():
    return """
SELECT
  ha.case_id,
  ha.nip,
  ha.periode,
  ha.komponen,
  ha.nominal_awal AS nominal_history_awal,
  d.nominal_pengembalian AS nominal_dasar_final,
  (d.nominal_pengembalian - ha.nominal_awal) AS delta
FROM (
  SELECT case_id, MAX(nominal_awal) AS nominal_awal, nip, periode, komponen
  FROM pengembalian_history_awal GROUP BY case_id, nip, periode, komponen
) ha
LEFT JOIN (
  SELECT p.* FROM pengembalian_dasar_perhitungan p
  JOIN (
    SELECT case_id, MAX(calculated_at) AS maxt FROM pengembalian_dasar_perhitungan GROUP BY case_id
  ) m ON m.case_id = p.case_id AND m.maxt = p.calculated_at
) d ON d.case_id = ha.case_id
WHERE d.nominal_pengembalian IS NOT NULL
  AND ROUND(COALESCE(d.nominal_pengembalian,0) - COALESCE(ha.nominal_awal,0), 2) <> 0
ORDER BY ABS(d.nominal_pengembalian - ha.nominal_awal) DESC
"""


def q_duplicates_history_awal():
    return """
SELECT nip, periode, komponen, COUNT(*) AS cnt,
       GROUP_CONCAT(case_id, ',') AS case_ids
FROM pengembalian_history_awal
GROUP BY nip, periode, komponen
HAVING COUNT(*) > 1
ORDER BY cnt DESC
"""


def q_not_sent_to_bpk():
    return """
SELECT ha.case_id, ha.nip, ha.periode, ha.komponen, ha.nominal_awal
FROM (
  SELECT case_id, nip, periode, komponen, MAX(nominal_awal) AS nominal_awal
  FROM pengembalian_history_awal GROUP BY case_id, nip, periode, komponen
) ha
LEFT JOIN pengembalian_bpk_detail b ON b.case_id = ha.case_id
WHERE b.case_id IS NULL
ORDER BY ha.case_id
"""


def q_bpk_not_sent_to_bank():
    return """
SELECT b.batch_id AS bpk_batch, b.case_id, b.nip, b.periode, b.komponen, b.nominal
FROM pengembalian_bpk_detail b
LEFT JOIN pengembalian_bank_detail bd ON bd.case_id = b.case_id AND bd.nominal = b.nominal
WHERE bd.id IS NULL
ORDER BY b.batch_id
"""


def q_bank_result_summary():
    return """
SELECT status, COUNT(*) AS cnt, SUM(COALESCE(nominal,0)) AS total_nominal
FROM pengembalian_bank_result
GROUP BY status
ORDER BY cnt DESC
"""


def q_bank_result_failures():
    return """
SELECT id, bank_batch_id, bank_detail_id, case_id, nip, nominal, status, reason, processed_at
FROM pengembalian_bank_result
WHERE UPPER(COALESCE(status,'')) NOT IN ('SUCCESS','BERHASIL')
ORDER BY processed_at DESC
LIMIT 500
"""


def q_nip_mismatch():
    return """
SELECT c.case_id, c.nip as case_nip, ha.nip as history_awal_nip
FROM pengembalian_tukin_case c
LEFT JOIN (
  SELECT case_id, MAX(nip) AS nip FROM pengembalian_history_awal GROUP BY case_id
) ha ON ha.case_id = c.case_id
WHERE (ha.nip IS NOT NULL AND c.nip IS NOT NULL AND ha.nip <> c.nip)
   OR (ha.nip IS NULL AND c.nip IS NOT NULL)
   OR (ha.nip IS NOT NULL AND c.nip IS NULL)
"""


def q_totals_consistency():
    return """
SELECT
  SUM(ha.nominal_awal) AS sum_nominal_awal,
  SUM(COALESCE(d.nominal_pengembalian, ha.nominal_awal)) AS sum_kewajiban_final,
  SUM(COALESCE(r.total_valid_realisasi,0)) AS sum_total_realisasi_valid,
  SUM(COALESCE(d.nominal_pengembalian, ha.nominal_awal)) - SUM(COALESCE(r.total_valid_realisasi,0)) AS sum_expected_sisa,
  SUM(COALESCE(h.position_from_history,0)) AS sum_positions
FROM (
  SELECT case_id, MAX(nominal_awal) AS nominal_awal FROM pengembalian_history_awal GROUP BY case_id
) ha
LEFT JOIN (
  SELECT p.* FROM pengembalian_dasar_perhitungan p
  JOIN (SELECT case_id, MAX(calculated_at) AS maxt FROM pengembalian_dasar_perhitungan GROUP BY case_id) m
    ON m.case_id = p.case_id AND m.maxt = p.calculated_at
) d ON d.case_id = ha.case_id
LEFT JOIN (
  SELECT case_id, SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS total_valid_realisasi, SUM(amount) AS position_from_history
  FROM pengembalian_tukin_history GROUP BY case_id
) r ON r.case_id = ha.case_id
LEFT JOIN (
  SELECT case_id, SUM(amount) AS position_from_history_sum FROM pengembalian_tukin_history GROUP BY case_id
) h ON h.case_id = ha.case_id
"""


def q_penyesuaian_list():
    return """
SELECT p.id, p.case_id, p.nip, p.periode, p.nominal_sebelum, p.nominal_setelah, p.selisih, p.jenis_penyesuaian, p.alasan_penyesuaian, p.created_at
FROM pengembalian_penyesuaian p
ORDER BY p.created_at DESC
LIMIT 500
"""


def q_audit_related():
    return """
SELECT * FROM audit_log
WHERE (table_name LIKE '%pengembalian%' OR source LIKE '%pengembalian%' OR details LIKE '%pengembalian%')
ORDER BY timestamp DESC
LIMIT 500
"""


def q_timeline(case_id: str):
    return f"""
WITH h0 AS (
  SELECT id as event_id, case_id, created_at AS ts, 'HISTORY_AWAL' AS stage, nominal_awal AS amount, '{{"src":"history_awal","source_file":source_file,"source_row":source_row}}' AS details
  FROM pengembalian_history_awal WHERE case_id = '{case_id}'
),
 d0 AS (
  SELECT id as event_id, case_id, calculated_at AS ts, 'DASAR_PERHITUNGAN' AS stage, nominal_pengembalian AS amount, '{{"calculation_version":calculation_version,"rule_version":rule_version}}' AS details
  FROM pengembalian_dasar_perhitungan WHERE case_id = '{case_id}'
),
 p0 AS (
  SELECT id as event_id, case_id, created_at AS ts, 'PENYESUAIAN' AS stage, (nominal_setelah - nominal_sebelum) AS amount, '{{"jenis":jenis_penyesuaian,"alasan":alasan_penyesuaian,"ref":reference_id}}' AS details
  FROM pengembalian_penyesuaian WHERE case_id = '{case_id}'
),
 bpk AS (
  SELECT id as event_id, case_id, created_at AS ts, 'SEND_BPK' AS stage, nominal AS amount, '{{"batch_id":batch_id,"bpk_id":id}}' AS details
  FROM pengembalian_bpk_detail WHERE case_id = '{case_id}'
),
 bank AS (
  SELECT id as event_id, case_id, created_at AS ts, 'SEND_BANK' AS stage, nominal AS amount, '{{"batch_id":batch_id,"bank_detail_id":id}}' AS details
  FROM pengembalian_bank_detail WHERE case_id = '{case_id}'
),
 bres AS (
  SELECT id as event_id, case_id, processed_at AS ts, 'RESULT_BANK' AS stage, nominal AS amount, '{{"status":status,"reason":reason,"bank_detail_id":bank_detail_id}}' AS details
  FROM pengembalian_bank_result WHERE case_id = '{case_id}'
),
 hist AS (
  SELECT id as event_id, case_id, created_at AS ts, 'HISTORY' AS stage, amount AS amount, '{{"event_type":event_type,"notes":notes,"source_table":source_table}}' AS details
  FROM pengembalian_tukin_history WHERE case_id = '{case_id}'
)
SELECT * FROM (
  SELECT * FROM h0 UNION ALL SELECT * FROM d0 UNION ALL SELECT * FROM p0 UNION ALL SELECT * FROM bpk UNION ALL SELECT * FROM bank UNION ALL SELECT * FROM bres UNION ALL SELECT * FROM hist
) t
ORDER BY ts NULLS LAST
"""


def q_generic_compare(table_a: str, table_b: str, keys: list):
    join_cond = ' AND '.join([f'a.{k} = b.{k}' for k in keys])
    select_keys = ', '.join([f'COALESCE(a.{k}, b.{k}) AS {k}' for k in keys])
    return f"""
WITH a AS (
  SELECT {', '.join(keys)}, SUM(COALESCE(nominal,0)) AS sum_nominal, COUNT(*) AS cnt
  FROM {table_a} GROUP BY {', '.join(keys)}
),
 b AS (
  SELECT {', '.join(keys)}, SUM(COALESCE(nominal,0)) AS sum_nominal, COUNT(*) AS cnt
  FROM {table_b} GROUP BY {', '.join(keys)}
)
SELECT
  {select_keys},
  a.sum_nominal AS sum_a,
  b.sum_nominal AS sum_b,
  CASE
    WHEN a.sum_nominal IS NOT NULL AND b.sum_nominal IS NOT NULL AND a.sum_nominal = b.sum_nominal THEN 'MATCH'
    WHEN a.sum_nominal IS NOT NULL AND b.sum_nominal IS NOT NULL AND a.sum_nominal <> b.sum_nominal THEN 'NOMINAL_DIFFERENCE'
    WHEN a.sum_nominal IS NOT NULL AND b.sum_nominal IS NULL THEN 'ONLY_A'
    WHEN a.sum_nominal IS NULL AND b.sum_nominal IS NOT NULL THEN 'ONLY_B'
    ELSE 'UNKNOWN'
  END AS status
FROM a FULL OUTER JOIN b ON {join_cond}
ORDER BY status, {', '.join(keys)}
LIMIT 2000
"""


def main():
    parser = argparse.ArgumentParser(description='Rekonsiliasi Master Pengembalian (DuckDB)')
    parser.add_argument('--db', default=DEFAULT_DB, help='Path to DuckDB file')
    parser.add_argument('--outdir', default=str(Path('backend') / 'reports' / f'rekons_{now_ts()}'), help='Output directory for CSV reports')
    parser.add_argument('--case-id', default=None, help='Optional case_id to export timeline for')
    parser.add_argument('--compare-a', default='pengembalian_bpk_detail', help='Table A for generic compare')
    parser.add_argument('--compare-b', default='pengembalian_bank_detail', help='Table B for generic compare')
    parser.add_argument('--keys', default='nip,periode,komponen', help='Comma-separated keys for generic compare')
    args = parser.parse_args()

    db_path = args.db
    outdir = ensure_outdir(args.outdir)
    print('Using DB:', db_path)
    print('Writing reports to:', outdir)

    conn = duckdb.connect(db_path)

    reports = []

    tasks = [
        ('per_case_sisa.csv', q_per_case_sisa),
        ('nominal_change_history_vs_dasar.csv', q_nominal_change_history_vs_dasar),
        ('duplicates_history_awal.csv', q_duplicates_history_awal),
        ('not_sent_to_bpk.csv', q_not_sent_to_bpk),
        ('bpk_not_sent_to_bank.csv', q_bpk_not_sent_to_bank),
        ('bank_result_summary.csv', q_bank_result_summary),
        ('bank_result_failures.csv', q_bank_result_failures),
        ('nip_mismatch.csv', q_nip_mismatch),
        ('totals_consistency.csv', q_totals_consistency),
        ('penyesuaian_list.csv', q_penyesuaian_list),
        ('audit_related.csv', q_audit_related),
    ]

    for fname, qfn in tasks:
        print('Running', fname)
        sql = qfn()
        df = run_query(conn, sql)
        if df is None:
            print(' -> skipped', fname)
            continue
        out = outdir / fname
        df.to_csv(out, index=False)
        reports.append(out)
        print(' -> wrote', out)

    # generic compare
    keys = [k.strip() for k in args.keys.split(',') if k.strip()]
    print('Running generic compare between', args.compare_a, 'and', args.compare_b, 'keys=', keys)
    sql_gen = q_generic_compare(args.compare_a, args.compare_b, keys)
    dfg = run_query(conn, sql_gen)
    if dfg is not None:
        outg = outdir / 'generic_compare_a_vs_b.csv'
        dfg.to_csv(outg, index=False)
        reports.append(outg)
        print(' -> wrote', outg)
    else:
        print(' -> skipped generic compare')

    # case timeline
    if args.case_id:
        print('Export timeline for case_id=', args.case_id)
        sqlt = q_timeline(args.case_id)
        dft = run_query(conn, sqlt)
        if dft is not None:
            outf = outdir / f'timeline_{args.case_id}.csv'
            dft.to_csv(outf, index=False)
            reports.append(outf)
            print(' -> wrote', outf)
        else:
            print(' -> skipped timeline')

    conn.close()

    print('\nReports generated:')
    for r in reports:
        print('-', r)
    print('\nDone.')


if __name__ == '__main__':
    main()
