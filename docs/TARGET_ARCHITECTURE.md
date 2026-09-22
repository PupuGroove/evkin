TARGET ARCHITECTURE — EVKIN WORK TOOL

Dokumen ini adalah rancangan arsitektur target untuk EVKIN WORK TOOL berdasarkan hasil audit awal. Dokumen bersifat desain saja: TIDAK melakukan perubahan kode, database, migration, atau business logic.

Ringkasan tujuan
- Menyatukan fitur kerja (master pegawai, absensi, tukin, hitung BASE, pembulatan, rekonsiliasi, import/export, audit, backup, dashboard) dalam satu aplikasi lokal/offline.
- Backend (Python + FastAPI) menjadi pusat business logic; DuckDB menjadi single source-of-truth (SSOT) untuk data workflow.
- Frontend (static JS/HTML) hanya bertanggung jawab pada antarmuka, validasi ringan, dan panggilan API — perhitungan utama dilakukan di backend.

Arsitektur tinggi (diagram)

Frontend (browser static files)
  ↓ HTTPS/HTTP local
FastAPI API (backend) — entrypoints: evkin_export_api.py, main.py (analytics), pembulatan_backend.py (optional service)
  ↓
Service layer (domain services: absensi, tukin, pembulatan, rekonsiliasi, import/export, audit, backup)
  ↓
DuckDB (EVKIN_MASTER.duckdb) — canonical workflow store
  ↕
SQLite metadata stores (evkin.db, pembulatan_jobs.db) — lightweight job/state/flags for backward compatibility and UI

Prinsip operasional (yang harus dipatuhi)
- Backend adalah pusat business logic; jangan menduplikasi/reroute rumus ke frontend.
- DuckDB adalah SSOT — semua operasi bulk, analytics, dan exports membaca dari dan/atau menulis ke DuckDB.
- Import/Export dilakukan oleh backend (server-side). Frontend hanya mengirim file/payload atau trigger job.
- Jangan mengubah business logic yang ada tanpa validasi dan pengujian yang jelas.
- Aplikasi harus dapat berjalan offline (semua dependencies harus dapat diinstal lokal).
- Hentikan perubahan besar pada struktur proyek; adaptasikan struktur baru hanya bila kompatibel dan aman.

Target struktur direktori (direkomendasikan, tetapi adaptif terhadap struktur existing)

backend/
  ├── api/               # FastAPI routers (evkin_export_api, analytics, pembulatan)
  │     ├── export.py
  │     ├── analytics.py
  │     └── pembulatan.py
  ├── services/          # Business services (absensi, tukin, base, rekonsiliasi)
  │     ├── absensi.py
  │     ├── tukin.py
  │     ├── base.py
  │     └── pembulatan_service.py
  ├── db/                # DB helpers, connection management, migrations (metadata only)
  │     ├── duckdb.py
  │     └── sqlite.py
  ├── schemas/           # Pydantic models and shared schemas
  ├── utils/             # Utilities: excel, csv, serialization, validation
  ├── migrations/        # Migration scripts (ONLY for analysis; do not run/change DB now)
  └── main.py            # application bootstrap (or api/__init__ mounting)

assets/ (frontend)
  ├── js/
  ├── css/
  └── vendor/

docs/
  ├── ARCHITECTURE_AUDIT.md
  ├── DATABASE_AUDIT.md
  ├── API_AUDIT.md
  ├── BUSINESS_LOGIC_AUDIT.md
  └── TARGET_ARCHITECTURE.md  (this file)

Database architecture (DuckDB as SSOT)
- Store: backend/data/EVKIN_MASTER.duckdb
- Purpose: canonical workflow tables (master_data, raw_import, hitung_harian, rekap_sdm, final_absensi, final_skp, anomali, etc.)
- Access pattern:
  - Reads: analytics, export, dashboard, compute jobs (hitung_harian)
  - Writes: import flows (/api/workflow/sync, /api/workflow/sync-table), compute results (run_compute_harian_job), flags/metadata (workflow_flags)
- Metadata and job state: lightweight SQLite stores (evkin.db for exports/jobs/flags and pembulatan_jobs.db for rounding jobs)

Import architecture
- Import responsibilities live in backend:
  - Endpoints: /api/import/template (provide templates), /api/workflow/sync (bulk sync from frontend), /load-csv (local CSV import for analytics app)
  - Flow:
    1. Frontend reads user file (client-side parsing) or uploads/send payload to backend.
    2. Backend validates minimal schema, prepares DataFrame, and writes into DuckDB using CREATE OR REPLACE TABLE or append strategies.
    3. Backend updates workflow_meta in SQLite for quick UI feedback.
- Validation: Prefer schema checks on backend (pydantic/schema) and light client-side validation for UX.

Export architecture
- Export responsibilities live in backend:
  - Endpoints: /api/export/final, /api/export/workbook, /api/jobs/export
  - Flow:
    1. User requests export from UI; backend may enqueue a background job (ProcessPoolExecutor) for heavy exports.
    2. Background worker reads from DuckDB, prepares sanitized DataFrames, writes xlsx via xlsxwriter or CSVs.
    3. Result saved to backend/exports/ with job metadata in SQLite; download served via /api/jobs/{id}/download.
- Large data: chunk reads in DuckDB to limit memory; split sheets when exceeding Excel row limits.

Business logic architecture
- Compute_harian_core and pembulatan logic remain server-side (evkin_export_api.py and pembulatan_backend.py respectively).
- Expose these as service functions in services/ and keep API routers thin (router -> service -> db).
- Ensure unit-testable pure functions for core formulas (no direct I/O in core functions) to enable future validation.

Audit architecture
- All important operations must be auditable. Design patterns:
  - Write audit_log table (DuckDB or SQLite depending on volume) capturing: who (if applicable), what, when, source (UI/file), checksum of payload, and diffs if possible.
  - For imports/exports/computes: record job id, start/finish timestamps, rows processed, errors, and output file link.

Backup architecture
- Periodic or on-demand backup of EVKIN_MASTER.duckdb to backend/data/backup/ with timestamped filenames.
- Backup endpoint in API (protected by requirement — local only) to trigger manual backup.
- Maintain retention policy (e.g., keep N latest backups) configurable in workflow_config.

Dependency between modules (high-level)
- Frontend → API routers (export, import, compute, pembulatan)
- API routers → Service layer (absensi, tukin, base, pembulatan)
- Services → db/duckdb helper for heavy transforms
- Services → utils for excel serialization and safe value handling
- Background jobs (compute/export) write job metadata into SQLite for UI consumption

Data workflow (example: Import → Compute → Export)
1. User uploads raw_import via frontend import flow → /api/workflow/sync-table or /api/workflow/sync
2. Backend writes raw_import to DuckDB; updates workflow_meta
3. User starts compute (hitung harian) via /api/compute/harians → background job reads raw_import, computes hitung_harian, writes results to hitung_harian and rekap_sdm/final_absensi
4. Backend marks workflow_flags (semifinal) and records audit log
5. User requests export final → backend creates export workbook reading final_absensi and returns file or creates background job

Security and operational notes
- Local/offline: by default services run without authentication; if deployed to networked environment consider adding API-key or local auth guard.
- Environment variables: EVKIN_DUCKDB_PATH, EVKIN_ANALYTICS_API_KEY (analytics app) — document their use in docs/QUICK_SETUP.md
- Concurrency: DuckDB supports multiple readers; be cautious with many concurrent writers. Prefer serialized writes or use job queue for write-heavy tasks.

Migration / refactor policy (temporary)
- Do not perform migrations or large refactors until full schema and business logic are mapped and covered by tests.
- Any structural changes must preserve existing endpoints compatibility or provide adapter routes.

Next steps (read-only/designed actions)
1. Consolidate this TARGET_ARCHITECTURE.md into docs and review with stakeholders.
2. Create small read-only tasks to extract detailed signatures and docstrings of compute_harian_core, pembulatan functions, and assets/js/calc.js for parity checks.
3. Add lightweight ADRs (architecture decision records) for choices: DuckDB SSOT, backend-centric compute, job model (SQLite + ProcessPoolExecutor).
4. Plan tests for critical business logic before any migration or change.

Constraints reminder
- NO code changes, NO DB writes, NO migrations, NO business logic edits during this design phase.

Dokumen ini selesai — STOP. Tunggu instruksi berikutnya.