"""
Migration 019: create view vw_pengembalian_timeline
Non-destructive: CREATE OR REPLACE VIEW that unions timeline-relevant events into a chronological list per case_id.
"""
from pathlib import Path
import duckdb


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        sql = r"""
        CREATE OR REPLACE VIEW vw_pengembalian_timeline AS
        -- Unified timeline for a case_id, ordered by event_time
        SELECT case_id, event_time, event_order, event_label, amount, status, source_table, reference_id, details
        FROM (
            -- DATA AWAL (snapshot)
            SELECT
                case_id,
                imported_at AS event_time,
                100 AS event_order,
                'DATA AWAL' AS event_label,
                nominal_awal AS amount,
                NULL AS status,
                'pengembalian_history_awal' AS source_table,
                id AS reference_id,
                json('{"source":"history_awal"}') AS details
            FROM pengembalian_history_awal

            UNION ALL

            -- DASAR PERHITUNGAN (calculation result)
            SELECT
                case_id,
                calculated_at AS event_time,
                200 AS event_order,
                'DASAR PERHITUNGAN' AS event_label,
                nominal_seharusnya AS amount,
                NULL AS status,
                'pengembalian_dasar_perhitungan' AS source_table,
                id AS reference_id,
                json('{"source":"dasar_perhitungan"}') AS details
            FROM pengembalian_dasar_perhitungan

            UNION ALL

            -- PENYESUAIAN
            SELECT
                case_id,
                created_at AS event_time,
                300 AS event_order,
                'PENYESUAIAN (' || COALESCE(jenis_penyesuaian,'') || ')' AS event_label,
                selisih AS amount,
                NULL AS status,
                'pengembalian_penyesuaian' AS source_table,
                id AS reference_id,
                json('{"source":"penyesuaian"}') AS details
            FROM pengembalian_penyesuaian

            UNION ALL

            -- ADJUSTMENT (official after BPK/Bank)
            SELECT
                case_id,
                created_at AS event_time,
                350 AS event_order,
                'ADJUSTMENT (' || COALESCE(adjustment_type,'') || ')' AS event_label,
                adjustment_value AS amount,
                NULL AS status,
                'pengembalian_adjustment' AS source_table,
                id AS reference_id,
                json('{"source":"adjustment"}') AS details
            FROM pengembalian_adjustment

            UNION ALL

            -- SEND BPK (detail)
            SELECT
                case_id,
                created_at AS event_time,
                400 AS event_order,
                'SEND BPK' AS event_label,
                nominal_pengembalian AS amount,
                status AS status,
                'pengembalian_bpk_detail' AS source_table,
                id AS reference_id,
                json('{"source":"bpk_detail"}') AS details
            FROM pengembalian_bpk_detail

            UNION ALL

            -- SEND BANK (detail)
            SELECT
                case_id,
                created_at AS event_time,
                450 AS event_order,
                'SEND BANK' AS event_label,
                nominal_debet AS amount,
                status_send AS status,
                'pengembalian_bank_detail' AS source_table,
                id AS reference_id,
                json('{"source":"bank_detail"}') AS details
            FROM pengembalian_bank_detail

            UNION ALL

            -- RESULT BANK (success/failure)
            SELECT
                case_id,
                COALESCE(tanggal_result, tanggal_proses, created_at) AS event_time,
                500 AS event_order,
                CASE WHEN status_debet = 'BERHASIL' THEN 'BERHASIL' ELSE 'GAGAL' END AS event_label,
                COALESCE(nominal_berhasil, nominal_gagal, 0) AS amount,
                status_debet AS status,
                'pengembalian_bank_result' AS source_table,
                id AS reference_id,
                json('{"source":"bank_result"}') AS details
            FROM pengembalian_bank_result

            UNION ALL

            -- SEND KEUANGAN (detail)
            SELECT
                case_id,
                created_at AS event_time,
                600 AS event_order,
                'SEND KEUANGAN' AS event_label,
                nominal AS amount,
                status_pengembalian AS status,
                'pengembalian_keuangan_detail' AS source_table,
                id AS reference_id,
                json('{"source":"keuangan_detail"}') AS details
            FROM pengembalian_keuangan_detail

            UNION ALL

            -- History generic events (pengembalian_tukin_history)
            SELECT
                case_id,
                created_at AS event_time,
                700 AS event_order,
                event_type AS event_label,
                amount AS amount,
                NULL AS status,
                'pengembalian_tukin_history' AS source_table,
                id AS reference_id,
                json('{"source":"history"}') AS details
            FROM pengembalian_tukin_history
        ) events
        ORDER BY case_id, event_time, event_order, reference_id;
        """
        conn.execute(sql)
        conn.close()
        print('Migration 019 applied: view vw_pengembalian_timeline created or replaced')
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
