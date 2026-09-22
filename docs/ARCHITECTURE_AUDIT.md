Summary of project architecture (audit)

Project root: C:/Users/USER/Documents/EVKIN_ABSENSI_v1.5 update terbaru/EVKIN_ABSENSI_v1.5 diocode

Top-level components discovered (read-only scan):

- backend/ — Python FastAPI backend and related scripts
  - main.py (analytics endpoints)
  - evkin_export_api.py (export, workflow sync, compute harian, job manager)
  - pembulatan_backend.py (pembulatan/rounding service)
  - loader.py, migrations/, tests/, data/, exports/
  - databases: evkin.duckdb, evkin.db, pembulatan_jobs.db

- assets/ — frontend static assets
  - js/: app.js, export-backend.js, import.js, calc.js, pembulatan.js, audit.js, evkin-db.js, etc.
  - css/: style.css
  - data/: example CSVs (contoh_absensi.csv, contoh_pegawai.csv, ...)
  - vendor/: xlsx.full.min.js (client-side XLSX helper)

- root files
  - index.html (frontend entry)
  - README*.md, QUICK_SETUP.md, start_*.bat / .ps1 (startup scripts and docs)

- docs/ (this folder) — audit output (created by read-only audit)

Notes and observations:
- Backend is implemented as multiple FastAPI apps: evkin_export_api.py is the main export/service app and tries to mount backend.main (analytics) at /analytics if available.
- DuckDB is used as the canonical workflow/master data store (EVKIN_MASTER.duckdb in backend/data). SQLite (evkin.db) and a pembulatan_jobs.db are present for lightweight metadata and job state in some flows.
- Frontend assets are served as static files and make API calls to the backend export API (evkin_export_api) and analytics app (mounted under /analytics when present).
- Migration scripts exist under backend/migrations/ for importing/migrating legacy data (001_create_master_schema.py, 002_*, ...).

Constraints (as per audit instructions):
- This document is factual and based on a read-only scan. No code, database, or business logic was modified.
- Further detailed inspection of specific files (compute code, calc.js, pembulatan logic) should be done read-only when requested.