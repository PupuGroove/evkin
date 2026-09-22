Import & Export audit (read-only)

Import endpoints / code discovered:

- backend/main.py
  - POST /load-csv (load_csv): Load CSV from a server-accessible path into DuckDB people table using DuckDB read_csv_auto or pandas fallback.

- backend/evkin_export_api.py
  - POST /api/workflow/sync (sync_workflow): Replace workflow tables in DuckDB with payload from browser (master_data, raw_import, hitung_harian, ...). Writes counts to SQLite workflow_meta as well.
  - POST /api/workflow/sync-table (sync_workflow_table): Sync a single workflow table into DuckDB (append or replace).
  - POST /api/master-sdm (upsert_master_sdm): Replace master_data in DuckDB.
  - GET  /api/import/template (api_import_template): Generates example templates for various import sources (raw_import, final_absensi, master_data, hitung_harian, rekap_sdm, semifinal/anomali, final_skp, config).

- Frontend assets (assets/js/import*.js, import-worker.js)
  - Client-side helpers to parse and prepare import payloads before syncing to backend via /api/workflow/sync or specific endpoints.

Export endpoints / code discovered:

- backend/main.py
  - GET /export/aggregates: CSV download for aggregates per-unit/per-jabatan/per-status.

- backend/evkin_export_api.py
  - POST /api/export/final: export final_absensi as XLSX (DuckDB canonical)
  - POST /api/export/workbook: export multiple sheets (raw_import, hitung_harian, rekap_sdm, final_absensi, final_skp, final_kombinasi, final_combined_skp)
  - POST /api/jobs/export & related job endpoints: background export job creation and management; results written to backend/exports/ and retrievable via download endpoint.
  - GET /api/import/template: provides templates for import (also used by users to prepare imports)

- Frontend assets (assets/js/export-backend.js, export.js, export-worker.js)
  - Client-side code that triggers export endpoints and handles download of generated files; uses xlsx library for client-side exports too.

Implementation notes (read-only):
- Server-side exports use pandas + xlsxwriter; large tables are split across multiple sheets if exceeding Excel row limits.
- Export background jobs are implemented using ProcessPoolExecutor and SQLite jobs table to track status; job cancellation, retry, and download endpoints are provided.
- Import flows assume the CSV/XLSX data will be provided by the browser or available on disk for backend load (e.g., /load-csv expects a server filesystem path).
- prepare_excel_frame() and related utilities sanitize values for Excel (limit cell text length, remove invalid XML chars).

Recommended read-only follow-ups:
- Inspect assets/js/import.js and import-worker.js to map frontend import flows to API calls.
- Inspect export job runner (run_export_job) and compute_harian_core to understand performance/memory characteristics for large datasets.

No changes made; this is an inventory and read-only assessment.