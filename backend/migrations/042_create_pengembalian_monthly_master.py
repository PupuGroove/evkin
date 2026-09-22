"""Canonical monthly master sourced from MASTER SEND BPK DAN PENYESUAIAN.

The migration is additive: source imports and rows are append-only, while the
current view selects the active import for each Master Pengembalian period.
"""
from pathlib import Path
import os
import duckdb

DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute("BEGIN")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_monthly_import (
            import_id TEXT PRIMARY KEY, periode_id TEXT NOT NULL,
            source_filename TEXT NOT NULL, source_file_hash TEXT NOT NULL,
            source_sheet TEXT, status TEXT NOT NULL DEFAULT 'PREVIEW',
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            total_rows BIGINT DEFAULT 0, valid_rows BIGINT DEFAULT 0,
            warning_rows BIGINT DEFAULT 0, invalid_rows BIGINT DEFAULT 0,
            duplicate_rows BIGINT DEFAULT 0, total_awal DECIMAL(20,2) DEFAULT 0,
            total_final DECIMAL(20,2) DEFAULT 0, metadata_json TEXT DEFAULT '{}',
            validation_json TEXT DEFAULT '{}', imported_by TEXT,
            imported_at TIMESTAMP DEFAULT now(), activated_at TIMESTAMP,
            superseded_at TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_monthly_source_row (
            source_row_id TEXT PRIMARY KEY, import_id TEXT NOT NULL,
            source_row_number BIGINT NOT NULL, business_key TEXT,
            raw_json TEXT NOT NULL, validation_status TEXT NOT NULL,
            validation_flags TEXT DEFAULT '[]', created_at TIMESTAMP DEFAULT now(),
            UNIQUE(import_id, source_row_number)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pengembalian_monthly_master (
            row_id TEXT PRIMARY KEY, import_id TEXT NOT NULL, periode_id TEXT NOT NULL,
            source_row_number BIGINT NOT NULL, business_key TEXT NOT NULL,
            penilai TEXT, nip TEXT NOT NULL, nama TEXT, jabatan TEXT, tahap TEXT,
            predikat_kinerja TEXT, tahun INTEGER NOT NULL, bulan INTEGER NOT NULL,
            bulan_nama TEXT, potongan_skp_persen DOUBLE,
            potongan_esdm_persen DOUBLE, potongan_eabsensi_persen DOUBLE,
            tukin DECIMAL(20,2), potongan_skp DECIMAL(20,2),
            potongan_kehadiran_esdm DECIMAL(20,2),
            potongan_kehadiran_eabsensi DECIMAL(20,2),
            tukin_dibayar_esdm DECIMAL(20,2), tukin_dibayar_eabsensi DECIMAL(20,2),
            final_kehadiran DECIMAL(20,2), final_pengembalian DECIMAL(20,2),
            potongan_kehadiran_awal DECIMAL(20,2), pengembalian_awal DECIMAL(20,2),
            tahun_sp2d_update INTEGER, kdasatker_update TEXT,
            tahun_sp2d_awal INTEGER, kdasatker_awal TEXT,
            status_send_bpk TEXT, status_tendik TEXT, zona_waktu TEXT,
            provinsi TEXT, kabupaten_kota TEXT, cuti TEXT,
            tanggal_mulai_cuti TEXT, tanggal_selesai_cuti TEXT,
            tendik_hitung_absen TEXT, tendik_persentase TEXT,
            absen_final_tendik TEXT, pengembalian_final_tendik TEXT,
            status_pengembalian_final TEXT, status_pengembalian_awal TEXT,
            cek_selisih TEXT, keterangan_penyesuaian TEXT, cek_bup TEXT,
            selisih_pengembalian DECIMAL(20,2), status_perubahan TEXT,
            validation_status TEXT NOT NULL, validation_flags TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT now(),
            UNIQUE(import_id, business_key)
        )""")
        conn.execute("""CREATE OR REPLACE VIEW vw_pengembalian_monthly_current AS
            SELECT m.* FROM pengembalian_monthly_master m
            JOIN pengembalian_monthly_import i ON i.import_id=m.import_id
            WHERE i.status='ACTIVE' AND i.is_active=TRUE
        """)
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_monthly_import_period_active ON pengembalian_monthly_import(periode_id,is_active,imported_at)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_import_hash ON pengembalian_monthly_import(source_file_hash)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_source_import ON pengembalian_monthly_source_row(import_id,source_row_number)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_master_period_nip ON pengembalian_monthly_master(periode_id,nip,tahun,bulan)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_master_import_key ON pengembalian_monthly_master(import_id,business_key)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_master_filters ON pengembalian_monthly_master(provinsi,zona_waktu,status_tendik,status_send_bpk)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_master_sp2d ON pengembalian_monthly_master(tahun_sp2d_update,nip)",
        ):
            conn.execute(sql)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
