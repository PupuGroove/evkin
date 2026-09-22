API audit (read-only mapping)

This file lists discovered API endpoints, the file where they are defined, the handler function (when easily identifiable), and a short usage note. All information is from static read-only scan of source files.

Format: METHOD | ENDPOINT | FILE | FUNCTION | USAGE

--- backend/main.py (analytics)
GET  | /health                      | backend/main.py            | health()             | health check (returns duckdb path)
GET  | /people                      | backend/main.py            | list_people()        | paginated people list, optional search q
POST | /load-csv                    | backend/main.py            | load_csv()           | load CSV into DuckDB people table (path on disk)
GET  | /workflow/flags              | backend/main.py            | workflow_flags()     | read workflow_flags (filter by bulan optional)
GET  | /stats/counts                | backend/main.py            | stats_counts()       | row counts for main workflow tables
GET  | /stats/per-unit              | backend/main.py            | stats_per_unit()     | aggregated counts per unit
GET  | /stats/per-jabatan           | backend/main.py            | stats_per_jabatan()  | aggregated counts per jabatan
GET  | /stats/per-status            | backend/main.py            | stats_per_status()   | aggregated counts per status
GET  | /export/aggregates           | backend/main.py            | export_aggregates()  | download CSV aggregates (per-unit/per-jabatan/per-status)

--- backend/evkin_export_api.py (export, workflow, compute, jobs)
GET  | / (root)                     | backend/evkin_export_api.py | serve_frontend()     | serve index.html frontend
GET  | /api/health                  | backend/evkin_export_api.py | api_health()         | API health
GET  | /api/info                    | backend/evkin_export_api.py | api_info()           | service info
GET  | /api/ping                    | backend/evkin_export_api.py | api_ping()           | lightweight ping
GET  | /api/workflow/health         | backend/evkin_export_api.py | workflow_health()    | readiness of duckdb master schema
POST | /api/workflow/sync           | backend/evkin_export_api.py | sync_workflow()      | replace workflow tables in DuckDB with payload
GET  | /api/workflow/state          | backend/evkin_export_api.py | get_workflow_state() | export full workflow state from DuckDB (for hydration)
POST | /api/workflow/sync-table     | backend/evkin_export_api.py | sync_workflow_table()| sync a single workflow table into DuckDB (append/replace options)
POST | /api/workflow/mark-semifinal | backend/evkin_export_api.py | mark_semifinal()     | set semifinal verification flag (writes to sqlite + async duckdb)
GET  | /api/workflow/flags          | backend/evkin_export_api.py | get_workflow_flags() | read workflow flags (duckdb preferred, fallback sqlite)
GET  | /api/master-sdm              | backend/evkin_export_api.py | get_master_sdm()     | list master SDM with search/pagination/filter/sort
POST | /api/master-sdm              | backend/evkin_export_api.py | upsert_master_sdm()  | replace master_data table in DuckDB
POST | /api/master-sdm/upsert       | backend/evkin_export_api.py | upsert_master_sdm_row() | upsert single master SDM row
POST | /api/master-sdm/delete       | backend/evkin_export_api.py | delete_master_sdm()  | delete master SDM row(s)
GET  | /api/import/template         | backend/evkin_export_api.py | api_import_template()| download example import template (xlsx/csv)
POST | /api/export/final            | backend/evkin_export_api.py | export_final()       | export FINAL ABSENSI as XLSX (from DuckDB)
POST | /api/export/workbook         | backend/evkin_export_api.py | export_workbook()    | export selected sheets/tables into workbook (xlsx)
POST | /api/export/seed-demo        | backend/evkin_export_api.py | seed_demo_data()     | seed demo final_absensi into sqlite (for testing)
POST | /api/compute/harians         | backend/evkin_export_api.py | api_compute_harians()| start compute_harian job (background)
GET  | /api/compute/harians/result  | backend/evkin_export_api.py | api_compute_harians_result() | list compute job results

# Job endpoints (background export & job control)
POST | /api/jobs/export             | backend/evkin_export_api.py | create_export_job()  | create background export job (returns job id)
GET  | /api/jobs/{job_id}           | backend/evkin_export_api.py | api_get_job()        | retrieve job status
GET  | /api/jobs                    | backend/evkin_export_api.py | api_list_jobs()      | list recent jobs
GET  | /api/jobs/{job_id}/download  | backend/evkin_export_api.py | api_download_job_result() | download job output file
POST | /api/jobs/{job_id}/cancel    | backend/evkin_export_api.py | api_cancel_job()     | cancel a running job
POST | /api/jobs/{job_id}/retry     | backend/evkin_export_api.py | api_retry_job()      | retry a failed job

--- backend/pembulatan_backend.py (rounding service)
GET  | /health                      | backend/pembulatan_backend.py | health()            | health check for pembulatan service
POST | /api/pembulatan/process      | backend/pembulatan_backend.py | (handler)           | trigger pembulatan processing (jobs stored in pembulatan_jobs.db)
GET  | /api/pembulatan/jobs/{job_id}| backend/pembulatan_backend.py | (handler)           | retrieve pembulatan job status

Notes and caveats:
- Many endpoints enforce DuckDB as canonical source and will return 404/503 if table missing/unavailable.
- evkin_export_api.py also writes lightweight metadata to SQLite for backward compatibility (jobs table, workflow_meta, flags).
- Security: analytics endpoints in backend/main.py use an optional ANALYTICS_API_KEY env var; if not set the endpoints are open. The export API appears intended for local server use (CORS allow_origins=["*"]).
- This mapping is generated from static read-only scans; for full parameter details consult the specific function definitions in the source files.
