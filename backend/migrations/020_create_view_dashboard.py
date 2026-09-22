"""
Migration 020: create view vw_dashboard_master_pengembalian_case
This view exposes one row per case with key metrics derived from vw_master_pengembalian_current
so the dashboard can aggregate totals and apply filters efficiently.
Non-destructive: CREATE OR REPLACE VIEW.
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
        CREATE OR REPLACE VIEW vw_dashboard_master_pengembalian_case AS
        SELECT
            m.case_id,
            m.nip,
            m.nama,
            m.periode,
            m.komponen,

            -- amounts
            m.kewajiban_awal,
            m.kewajiban_final,
            m.send_bpk,
            m.send_bank,
            m.berhasil_didebet,
            m.gagal_debet,
            m.send_keuangan,
            m.total_dikembalikan,
            m.sisa_kewajiban,
            m.status,

            -- enrich with fields from latest history (provinsi, unit_kerja, tahun_sp2d)
            lh.provinsi,
            lh.unit_kerja,
            lh.tahun_sp2d,

            -- counts
            1 AS jumlah_sdm
        FROM vw_master_pengembalian_current m
        LEFT JOIN (
            SELECT case_id, provinsi, unit_kerja, tahun_sp2d FROM pengembalian_history_awal h
            JOIN (SELECT case_id, MAX(imported_at) AS ma FROM pengembalian_history_awal GROUP BY case_id) m2
            ON h.case_id = m2.case_id AND h.imported_at = m2.ma
        ) lh ON m.case_id = lh.case_id
        ;
        """
        conn.execute(sql)
        conn.close()
        print('Migration 020 applied: view vw_dashboard_master_pengembalian_case created or replaced')
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
