Database audit (read-only findings)

Databases discovered (files present):

1) DuckDB
- backend/evkin.duckdb
- backend/data/EVKIN_MASTER.duckdb
- backend/hr.duckdb
- backups: backend/data/backup/EVKIN_MASTER_YYYY-MM-DD_*.duckdb

Notes:
- DUCKDB is used as the canonical master/workflow store for analytics and exports. The module backend/evkin_export_api.py ensures a master schema and creates placeholder tables on startup.
- Known workflow tables (from code - WORKFLOW_TABLES):
  - workflow_config
  - master_data
  - raw_import
  - hitung_harian
  - rekap_sdm
  - final_absensi
  - anomali (semifinal)
  - final_skp
  - final_kombinasi
  - final_combined_skp
- DuckDB is also accessed by backend/main.py (analytics endpoints) and many export/compute functions in evkin_export_api.py.
- For DuckDB schema details: read-only inspection of each table (PRAGMA table_info) recommended before any migration or schema change.

2) SQLite
- backend/evkin.db (+ evkin.db-shm, evkin.db-wal)
- Usage: appears used for lightweight local metadata and backward-compatibility in evkin_export_api.py (get_connection returns sqlite3 connection and code writes workflow_meta, jobs, workflow_flags in SQLite). Seed/demo routes and some job metadata are stored here.

3) pembulatan_jobs.db
- backend/pembulatan_jobs.db
- Usage: related to pembulatan backend/job tracking (pembulatan_backend.py).

4) Other / transient
- backend/exports/ contains generated .xlsx files (export results)
- assets/data contains sample CSVs used for import testing

Per-database notes to collect later (recommended next read-only steps):
- For DuckDB: list all tables and their columns (PRAGMA table_info) and capture sizes/row counts for large tables.
- For SQLite (evkin.db): inspect tables workflow_meta, jobs, workflow_flags and job entries.
- For pembulatan_jobs.db: inspect schema and how job records are used by pembulatan_backend.py.

No modifications made; these findings are from file presence and code references only.

DuckDB schema dump has been generated and saved to: [docs/DUCKDB_SCHEMA.md](</C:/Users/USER/Documents/EVKIN_ABSENSI_v1.5 update terbaru/EVKIN_ABSENSI_v1.5 diocode/docs/DUCKDB_SCHEMA.md>).

Refer to that file for per-table columns and current row counts (read-only snapshot).