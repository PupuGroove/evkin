"""
Migration 016: create view vw_master_pengembalian_current
Non-destructive: CREATE OR REPLACE VIEW. View composes latest snapshot, latest calculation, BPK/Bank/Keuangan aggregates, and computes current position and sisa.

Notes:
- The view selects the latest history_awal row per case (most recent imported_at) and the latest dasar_perhitungan per case (most recent calculated_at).
- Total_Dikembalikan is computed from bank_result.nominal_berhasil + keuangan_detail.nominal (as realization). This can be adjusted if business defines other sources of realization.
- SISA = kewajiban_final - total_realisasi
- Status is derived (LUNAS if sisa <= 0 else TERTUNGGAK) but can be replaced with workflow status column if available.
"""
from pathlib import Path
import duckdb


def main():
    repo_root = Path(__file__).resolve().parent.parent
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    duck_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duck_path))
    try:
        sql = """
        CREATE OR REPLACE VIEW vw_master_pengembalian_current AS
        WITH latest_history AS (
            SELECT h.* FROM pengembalian_history_awal h
            JOIN (
                SELECT case_id, MAX(imported_at) AS ma FROM pengembalian_history_awal GROUP BY case_id
            ) m ON h.case_id = m.case_id AND h.imported_at = m.ma
        ), latest_dasar AS (
            SELECT d.* FROM pengembalian_dasar_perhitungan d
            JOIN (
                SELECT case_id, MAX(calculated_at) AS mc FROM pengembalian_dasar_perhitungan GROUP BY case_id
            ) md ON d.case_id = md.case_id AND d.calculated_at = md.mc
        ), agg_bpk AS (
            SELECT case_id, SUM(COALESCE(nominal_pengembalian,0)) AS send_bpk FROM pengembalian_bpk_detail GROUP BY case_id
        ), agg_bank_send AS (
            SELECT case_id, SUM(COALESCE(nominal_debet,0)) AS send_bank FROM pengembalian_bank_detail GROUP BY case_id
        ), agg_bank_result AS (
            SELECT case_id, SUM(COALESCE(nominal_berhasil,0)) AS berhasil_debet, SUM(COALESCE(nominal_gagal,0)) AS gagal_debet FROM pengembalian_bank_result GROUP BY case_id
        ), agg_keu AS (
            SELECT case_id, SUM(COALESCE(nominal,0)) AS send_keuangan FROM pengembalian_keuangan_detail GROUP BY case_id
        ), agg_history_realisasi AS (
            -- total realization inferred from bank results and keuangan sends; adjust if other realization sources exist
            SELECT
                COALESCE(br.case_id, k.case_id) AS case_id,
                COALESCE(br.berhasil_debet,0) + COALESCE(k.send_keuangan,0) AS total_realisasi
            FROM (
                SELECT case_id, SUM(COALESCE(nominal_berhasil,0)) AS berhasil_debet FROM pengembalian_bank_result GROUP BY case_id
            ) br
            FULL OUTER JOIN (
                SELECT case_id, SUM(COALESCE(nominal,0)) AS send_keuangan FROM pengembalian_keuangan_detail GROUP BY case_id
            ) k ON br.case_id = k.case_id
        )
        SELECT
            c.case_id,
            c.nip AS nip,
            COALESCE(lh.nama, '') AS nama,
            COALESCE(lh.periode, COALESCE(c.tahun || '-' || LPAD(c.bulan::VARCHAR,2,'0'), '')) AS periode,
            COALESCE(lh.komponen, COALESCE(ld.komponen, c.tipe_kewajiban)) AS komponen,

            -- Kewajiban Awal: latest snapshot nominal_awal
            COALESCE(lh.nominal_awal,0) AS kewajiban_awal,
            -- Kewajiban Setelah Penyesuaian / Final: prefer latest_dasar.nominal_seharusnya, fallback to nominal_awal
            COALESCE(ld.nominal_seharusnya, ld.nilai_dasar, lh.nominal_awal,0) AS kewajiban_final,

            COALESCE(bpk.send_bpk,0) AS send_bpk,
            COALESCE(bs.send_bank,0) AS send_bank,

            COALESCE(br.berhasil_debet,0) AS berhasil_didebet,
            COALESCE(br.gagal_debet,0) AS gagal_didebet,

            COALESCE(k.send_keuangan,0) AS send_keuangan,

            -- Total dikembalikan (realized) inferred from bank results + send keuangan
            COALESCE(hr.total_realisasi,0) AS total_dikembalikan,

            -- Sisa = kewajiban_final - total_dikembalikan
            (COALESCE(ld.nominal_seharusnya, ld.nilai_dasar, lh.nominal_awal,0) - COALESCE(hr.total_realisasi,0)) AS sisa_kewajiban,

            CASE WHEN (COALESCE(ld.nominal_seharusnya, ld.nilai_dasar, lh.nominal_awal,0) - COALESCE(hr.total_realisasi,0)) <= 0 THEN 'LUNAS' ELSE 'TERTUNGGAK' END AS status
        FROM pengembalian_tukin_case c
        LEFT JOIN latest_history lh ON c.case_id = lh.case_id
        LEFT JOIN latest_dasar ld ON c.case_id = ld.case_id
        LEFT JOIN agg_bpk bpk ON c.case_id = bpk.case_id
        LEFT JOIN agg_bank_send bs ON c.case_id = bs.case_id
        LEFT JOIN agg_bank_result br ON c.case_id = br.case_id
        LEFT JOIN agg_keu k ON c.case_id = k.case_id
        LEFT JOIN agg_history_realisasi hr ON c.case_id = hr.case_id
        ;
        """
        conn.execute(sql)
        conn.close()
        print('Migration 016 applied: view vw_master_pengembalian_current created or replaced')
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
