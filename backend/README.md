HR DuckDB Analytics Service

This module exposes lightweight analytics endpoints over the same DuckDB workflow database (EVKIN_ABSENSI_DB).

Configuration
- EVKIN_DUCKDB_PATH (optional): path to the DuckDB database file. Defaults to backend/evkin.duckdb.

Run
- Run standalone (recommended for separate analytics service):
  uvicorn backend.main:app --host 0.0.0.0 --port 9000

- Run with a custom DuckDB path:
  EVKIN_DUCKDB_PATH=/path/to/evkin.duckdb uvicorn backend.main:app --host 0.0.0.0 --port 9000

Mounting
- The main API (backend/evkin_export_api.py) can optionally mount this analytics app under /analytics if available.

Provided endpoints
- GET /health
- GET /people?offset=0&limit=100&q=...  (if a 'people' table is loaded)
- POST /load-csv {"path": "/full/path/to/file.csv"}
- GET /workflow/flags?bulan=YYYY-MM   (read semifinal flags)
- GET /stats/counts?bulan=YYYY-MM    (row counts for main workflow tables)
- GET /stats/per-unit?bulan=YYYY-MM  (counts grouped by unit)

Notes
- CORS is permissive by default (allow_origins="*") to ease local integration. Lock this down in production.
- The service is intended as a read/analytics complement to the main export API which manages compute jobs and writes to the same DuckDB file.