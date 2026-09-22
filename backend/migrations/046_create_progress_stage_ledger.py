"""Extend Progress Pengembalian v2 with stage/NTPN ledger semantics."""
from pathlib import Path
import os
import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}


def _add(conn, table, column, definition):
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        for table in ("pengembalian_progress_staging", "pengembalian_progress_transaction"):
            for name, definition in (
                ("tahap", "INTEGER"),
                ("nomor_rekening", "TEXT"),
                ("nominal_diajukan", "DECIMAL(18,2) DEFAULT 0"),
                ("nominal_berhasil", "DECIMAL(18,2) DEFAULT 0"),
                ("ntpn", "TEXT"),
                ("keterangan", "TEXT"),
                ("source_sheet", "TEXT"),
            ):
                _add(conn, table, name, definition)
        for name, definition in (
            ("import_mode", "TEXT DEFAULT 'PROGRESS_STAGE_IMPORT'"),
            ("reverted_by_batch_id", "TEXT"),
            ("reverted_at", "TIMESTAMP"),
        ):
            _add(conn, "pengembalian_progress_import_batch", name, definition)
        # Preserve committed legacy progress. Its adapter stored stage/NTPN in
        # periode_debit/raw_data before dedicated ledger columns existed.
        conn.execute("""UPDATE pengembalian_progress_transaction SET
            tahap=COALESCE(tahap,
                TRY_CAST(regexp_extract(coalesce(periode_debit,''),'(?i)Tahap\\s*([0-9]+)',1) AS INTEGER),
                TRY_CAST(regexp_extract(coalesce(json_extract_string(raw_data,'$.Source Stage'),''),'TAHAP_([0-9]+)',1) AS INTEGER)),
            ntpn=COALESCE(ntpn,json_extract_string(raw_data,'$.NTPN')),
            nomor_rekening=COALESCE(nomor_rekening,json_extract_string(raw_data,'$.Nomor Rekening'),json_extract_string(raw_data,'$.NOMER REKENING')),
            nominal_diajukan=CASE WHEN coalesce(nominal_diajukan,0)=0 THEN coalesce(nominal_debit_total,0) ELSE nominal_diajukan END,
            nominal_berhasil=CASE WHEN status_debit IN ('BERHASIL','REVERSAL') AND coalesce(nominal_berhasil,0)=0
                THEN coalesce(nominal_debit_total,0) ELSE coalesce(nominal_berhasil,0) END,
            source_sheet=COALESCE(source_sheet,json_extract_string(raw_data,'$.Source Sheet'))
        """)
        conn.execute("""UPDATE pengembalian_progress_import_batch SET import_mode='LEGACY_PROGRESS_BACKFILL'
            WHERE json_extract_string(metadata_json,'$.source_format')='MASTER_PROGRESS_WIDE'
              AND coalesce(import_mode,'PROGRESS_STAGE_IMPORT')='PROGRESS_STAGE_IMPORT'""")
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_stage ON pengembalian_progress_transaction(tahap,tahun_sp2d,komponen_debit)",
            "CREATE INDEX IF NOT EXISTS idx_progress_tx_ntpn ON pengembalian_progress_transaction(ntpn)",
            "CREATE INDEX IF NOT EXISTS idx_progress_stage_stage ON pengembalian_progress_staging(import_batch_id,tahap)",
        ):
            conn.execute(sql)
        conn.execute("""CREATE OR REPLACE VIEW pengembalian_obligation_component AS
            SELECT obligation_id || ':TUKIN' obligation_component_id,periode_id periode_master_id,
                nip,tahun_sp2d,'TUKIN' komponen,final_tukin nominal_kewajiban,nama_sdm,provinsi
            FROM pengembalian_master_obligation
            UNION ALL
            SELECT obligation_id || ':UANG_MAKAN',periode_id,nip,tahun_sp2d,'UANG_MAKAN',
                final_uang_makan,nama_sdm,provinsi FROM pengembalian_master_obligation""")
        conn.execute("""CREATE OR REPLACE VIEW pengembalian_transaction_ledger AS
            SELECT transaction_id id,periode_id periode_master_id,nip,tahun_sp2d,
                komponen_debit komponen,tahap,nama_bank_normalized bank,nomor_rekening,
                nominal_diajukan,
                CASE WHEN status_debit IN ('BERHASIL','REVERSAL') AND coalesce(nominal_berhasil,0)=0
                     THEN nominal_debit_total ELSE coalesce(nominal_berhasil,0) END nominal_berhasil,
                status_debit status,ntpn,tanggal_debit tanggal_proses,keterangan_gagal alasan_gagal,
                keterangan,import_batch_id,source_filename source_file,source_sheet,
                source_row_number source_row,fingerprint transaction_fingerprint,created_at
            FROM pengembalian_progress_transaction""")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
