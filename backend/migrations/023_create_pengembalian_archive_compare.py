"""Create append-only archive tables used by Master Pengembalian comparison.

The archive deliberately keeps the two source snapshots in separate tables.
Rows are never updated or upserted; an import is a new immutable snapshot.
"""
from pathlib import Path
import os
import duckdb


DB = os.environ.get("EVKIN_DUCKDB_PATH") or str(
    Path(__file__).resolve().parent.parent / "data" / "EVKIN_MASTER.duckdb"
)


ROW_COLUMNS = """
    row_id TEXT PRIMARY KEY,
    import_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_row INTEGER,
    nip TEXT,
    nama TEXT,
    tahun_sp2d INTEGER,
    nomor_sp2d TEXT,
    tahun INTEGER,
    bulan INTEGER,
    periode TEXT,
    batch TEXT,
    komponen TEXT,
    total_tukin DOUBLE,
    tukin_absen_30 DOUBLE,
    tukin_skp_70 DOUBLE,
    potongan_skp DOUBLE,
    esdm DOUBLE,
    e_absensi DOUBLE,
    tendik DOUBLE,
    total_potongan_absen DOUBLE,
    total_potongan_tukin DOUBLE,
    calculated_total_potongan_absen DOUBLE,
    calculated_total_potongan_tukin DOUBLE,
    daily_ref TEXT,
    monthly_ref TEXT,
    absence_ref TEXT,
    total_tukin_ref TEXT,
    source_record_id TEXT,
    source_file TEXT,
    source_sheet TEXT,
    validation_flags TEXT,
    tukin_validation TEXT,
    raw_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
"""


def main(db_path=None):
    path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pengembalian_archive_import (
                import_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                filename TEXT,
                file_hash TEXT,
                metadata TEXT,
                imported_at TIMESTAMP DEFAULT now(),
                imported_by TEXT,
                row_count INTEGER DEFAULT 0,
                valid_count INTEGER DEFAULT 0,
                invalid_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'IMPORTED'
            )
            """
        )
        import_columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'pengembalian_archive_import'"
            ).fetchall()
        }
        for column, definition in (
            ("dataset_type", "TEXT"),
            ("send_bpk_status", "TEXT"),
            ("bpk_batch", "INTEGER"),
            ("tanggal_send_bpk", "TIMESTAMP"),
            ("source_file_name", "TEXT"),
            ("version", "TEXT"),
            ("archive_version", "TEXT"),
            ("periode_id", "TEXT"),
            ("is_active", "BOOLEAN DEFAULT TRUE"),
        ):
            if column not in import_columns:
                conn.execute(
                    f"ALTER TABLE pengembalian_archive_import ADD COLUMN {column} {definition}"
                )
        # Keep only the newest snapshot active for each source and period when
        # upgrading databases created before source activation existed.
        legacy_rows = conn.execute(
            """SELECT import_id, source_type, COALESCE(periode_id, ''), imported_at
               FROM pengembalian_archive_import
               WHERE status <> 'INACTIVE'
               ORDER BY source_type, COALESCE(periode_id, ''), imported_at DESC, import_id DESC"""
        ).fetchall()
        latest_by_source = set()
        for import_id, source_type, periode_id, _imported_at in legacy_rows:
            key = (source_type, periode_id)
            if key in latest_by_source:
                conn.execute(
                    "UPDATE pengembalian_archive_import SET is_active=FALSE, status='INACTIVE' WHERE import_id=?",
                    [import_id],
                )
            else:
                latest_by_source.add(key)
                conn.execute(
                    "UPDATE pengembalian_archive_import SET is_active=TRUE, status='ACTIVE' WHERE import_id=?",
                    [import_id],
                )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pengembalian_archive_data_awal (" + ROW_COLUMNS + ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pengembalian_archive_data_penyesuaian ("
            + ROW_COLUMNS
            + ")"
        )
        # Read-only aliases make the business source names discoverable while
        # retaining the archive-prefixed physical tables.
        for alias, physical in (
            ("data_awal", "pengembalian_archive_data_awal"),
            ("data_penyesuaian", "pengembalian_archive_data_penyesuaian"),
            ("pengembalian_data_awal", "pengembalian_archive_data_awal"),
            ("pengembalian_data_penyesuaian", "pengembalian_archive_data_penyesuaian"),
        ):
            try:
                conn.execute(f"CREATE VIEW IF NOT EXISTS {alias} AS SELECT * FROM {physical}")
            except Exception:
                pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pengembalian_archive_compare (
                compare_id TEXT PRIMARY KEY,
                source_a TEXT NOT NULL,
                source_b TEXT NOT NULL,
                filters TEXT,
                started_at TIMESTAMP DEFAULT now(),
                finished_at TIMESTAMP,
                total_a INTEGER DEFAULT 0,
                total_b INTEGER DEFAULT 0,
                unchanged_count INTEGER DEFAULT 0,
                changed_count INTEGER DEFAULT 0,
                new_count INTEGER DEFAULT 0,
                missing_count INTEGER DEFAULT 0,
                duplicate_count INTEGER DEFAULT 0,
                flags TEXT,
                created_by TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pengembalian_archive_compare_detail (
                detail_id TEXT PRIMARY KEY,
                compare_id TEXT NOT NULL,
                comparison_key TEXT NOT NULL,
                result_type TEXT NOT NULL,
                flags TEXT,
                changes TEXT,
                data_awal TEXT,
                data_penyesuaian TEXT,
                source_status TEXT,
                source_reference TEXT,
                source_type TEXT,
                identity TEXT,
                initial_values TEXT,
                adjusted_values TEXT,
                changed_fields TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pengembalian_archive_bpk_history (
                history_id TEXT PRIMARY KEY,
                row_id TEXT,
                comparison_key TEXT NOT NULL,
                nip TEXT NOT NULL,
                bpk_batch INTEGER NOT NULL,
                bpk_batch_label TEXT NOT NULL,
                tanggal_send_bpk TIMESTAMP DEFAULT now(),
                bpk_reference TEXT,
                source_dataset TEXT,
                source_version TEXT,
                archive_version TEXT,
                is_current BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            )
            """
        )
        # Indexes are intentionally non-unique: duplicate source keys must survive.
        for statement in (
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_awal_key ON pengembalian_archive_data_awal(nip, tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_penyesuaian_key ON pengembalian_archive_data_penyesuaian(nip, tahun_sp2d)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_import_source ON pengembalian_archive_import(source_type, imported_at)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_detail_compare ON pengembalian_archive_compare_detail(compare_id)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_bpk_key ON pengembalian_archive_bpk_history(comparison_key)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_bpk_batch ON pengembalian_archive_bpk_history(bpk_batch)",
            "CREATE INDEX IF NOT EXISTS idx_pengembalian_archive_bpk_nip ON pengembalian_archive_bpk_history(nip)",
        ):
            try:
                conn.execute(statement)
            except Exception:
                pass
        detail_columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'pengembalian_archive_compare_detail'"
            ).fetchall()
        }
        for column in ("source_status", "source_reference", "source_type",
                       "identity", "initial_values", "adjusted_values", "changed_fields"):
            if column not in detail_columns:
                conn.execute(
                    f"ALTER TABLE pengembalian_archive_compare_detail ADD COLUMN {column} TEXT"
                )
        for table in ("pengembalian_archive_data_awal", "pengembalian_archive_data_penyesuaian"):
            table_columns = {
                row[0] for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]
                ).fetchall()
            }
            if "tukin_validation" not in table_columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN tukin_validation TEXT")
            for column in ("calculated_total_potongan_absen", "calculated_total_potongan_tukin"):
                if column not in table_columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} DOUBLE")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
