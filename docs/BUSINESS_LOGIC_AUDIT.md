Business logic audit (read-only findings)

Files containing core business logic (identified by static scan):

- backend/evkin_export_api.py
  - compute_harian_core / compute_harian_duckdb / run_compute_harian_job: implement the main per-day/per-employee calculations (durasi, potongan, keterlambatan, pulang cepat, flags, holiday handling, flexi rules, tiers for penalties). This is the primary place for 'Hitung BASE' and daily attendance computation when run server-side.
  - prepare_database_frame / serialize_database_value: handle serialization for storing workflow fields in DuckDB/SQLite.
  - Various helper functions for time formatting, duration tiers, pct calculations, holiday handling.

- backend/pembulatan_backend.py
  - Rounding-specific backend and API endpoints (pembulatan process, job tracking in pembulatan_jobs.db). This module must be treated as implementing rounding business rules.

- assets/js/calc.js (frontend)
  - Contains client-side calculation helpers and may mirror or implement parts of the business logic in the browser (useful for offline/local operations). Needs comparison with server-side logic to ensure consistency.

- assets/js/pembulatan.js
  - Frontend logic for pembulatan flows and interaction with pembulatan backend API.

- backend/loader.py
  - Helper/loader utilities that may orchestrate data flows and trigger computations.

Constraints and cautions (per audit instructions):
- Do NOT change business logic or formulas during audit. The code must be read-only.
- Critical rules like pembulatan, tukin calculation, and potongan/tiers are implemented in server compute code (compute_harian_core) and must be validated by reading, not modified.

Recommended read-only next steps:
- Diff and compare assets/js/calc.js and compute_harian_core to confirm parity (if required), documenting any differences.
- Extract and document the exact formulas used for Tukin, pembulatan, and BASE from the compute_harian_core and pembulatan_backend.py into BUSINESS_LOGIC_AUDIT.md (read-only transcription).
- Run a schema dump (DuckDB PRAGMA table_info) to map columns referenced by compute code to exact column names and types.

No edits performed; this file records where the business logic lives and suggests safe inspection steps.