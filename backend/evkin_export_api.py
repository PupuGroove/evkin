from __future__ import annotations

import importlib
import io
import json
import re
import sqlite3
import sys
import tempfile
import os
import shutil
from pathlib import Path
from typing import Any, Optional, List

import pandas as pd
import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uuid
import json
from datetime import datetime
import concurrent.futures
from backend.runtime_guard import claim_database, database_job, serialize_database_requests
from backend.final_integrity import final_manifest, assert_manifest, verify_final_xlsx
from backend.workflow_readiness import record_verification
from backend.security import ApiKeyMiddleware, CORS_HEADERS, CORS_METHODS, allowed_origins
from backend.schema_sync import create_table_from_relation, insert_relation_by_name
from backend.reset_service import RESET_PROFILES, ResetService

# Executor for background compute jobs
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='evkin-jobs')
# Keep futures to allow cancellation from the main process
_job_futures: dict = {}

APP_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = APP_ROOT / "assets"
INDEX_FILE = APP_ROOT / "index.html"

app = FastAPI(title="EVKIN Export API", version="1.1.0")
app.middleware('http')(serialize_database_requests)
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
)

@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path == "/index.html" or path.startswith("/assets/") or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Try to mount analytics app (backend.main) under /analytics if available
try:
    analytics_candidates = ['backend.main', 'main']
    analytics_mod = None
    for candidate in analytics_candidates:
        try:
            analytics_mod = importlib.import_module(candidate)
            break
        except ModuleNotFoundError:
            continue
    if analytics_mod and hasattr(analytics_mod, 'app'):
        app.mount('/analytics', analytics_mod.app)
        print('Mounted analytics app at /analytics')
except Exception as e:
    # Non-fatal if analytics module is absent; print to server logs
    print('Analytics app not mounted:', e)


def _resolve_self_module():
    for candidate in ('backend.evkin_export_api', 'evkin_export_api'):
        try:
            return importlib.import_module(candidate)
        except ModuleNotFoundError:
            continue
    return sys.modules.get(__name__)


# Backwards-compatibility safety: some deployments / reloads may import the module in a way
# that later route definitions (jobs/export) are not present in OpenAPI. Register proxy job
# routes only if they are not already registered. These proxies forward to the actual
# implementation (defined later in this module) at request time, avoiding circular import
# issues while ensuring the endpoints are present for the frontend.

def _route_exists(path: str, method: str | None = None) -> bool:
    for r in app.routes:
        p = getattr(r, 'path', None)
        m = getattr(r, 'methods', None)
        if p == path:
            if method is None:
                return True
            if m and method.upper() in m:
                return True
    return False

if not _route_exists('/api/jobs/export', 'POST'):
    @app.post('/api/jobs/export')
    def create_export_job_proxy(payload: dict) -> dict:
        mod = _resolve_self_module()
        return getattr(mod, 'create_export_job')(payload)

if not _route_exists('/api/jobs/{job_id}', 'GET'):
    @app.get('/api/jobs/{job_id}')
    def api_get_job_proxy(job_id: str):
        mod = _resolve_self_module()
        return getattr(mod, 'api_get_job')(job_id)

if not _route_exists('/api/jobs', 'GET'):
    @app.get('/api/jobs')
    def api_list_jobs_proxy(limit: int = Query(50, ge=1, le=1000)):
        mod = _resolve_self_module()
        return getattr(mod, 'api_list_jobs')(limit)

if not _route_exists('/api/jobs/{job_id}/download', 'GET'):
    @app.get('/api/jobs/{job_id}/download')
    def api_download_job_result_proxy(job_id: str):
        mod = _resolve_self_module()
        return getattr(mod, 'api_download_job_result')(job_id)

if not _route_exists('/api/jobs/{job_id}/cancel', 'POST'):
    @app.post('/api/jobs/{job_id}/cancel')
    def api_cancel_job_proxy(job_id: str):
        mod = _resolve_self_module()
        return getattr(mod, 'api_cancel_job')(job_id)

if not _route_exists('/api/jobs/{job_id}/retry', 'POST'):
    @app.post('/api/jobs/{job_id}/retry')
    def api_retry_job_proxy(job_id: str):
        mod = _resolve_self_module()
        return getattr(mod, 'api_retry_job')(job_id)

DB_PATH = str(Path(__file__).resolve().parent / "evkin.db")
# Use EVKIN_MASTER.duckdb in backend/data as the default master DB. Honor EVKIN_DUCKDB_PATH env var if set.
DUCKDB_PATH = os.environ.get('EVKIN_DUCKDB_PATH') or str(Path(__file__).resolve().parent / 'data' / 'EVKIN_MASTER.duckdb')  # primary workflow DB for heavy transforms

# Mount after DUCKDB_PATH is initialized because the legacy pengembalian
# module imports that setting while defining its compatibility helpers.
try:
    pengembalian_api = importlib.import_module("backend.pengembalian_api")
    app.include_router(pengembalian_api.router, prefix="/pengembalian")
except Exception as exc:
    print("Master Pengembalian API tidak terpasang:", exc)

# Modul pengelolaan Tukin tahunan memakai DuckDB yang sama dengan workflow
# absensi agar hasil final aktif dapat ditangkap tanpa ekspor/impor ulang.
try:
    tukin_annual = importlib.import_module("backend.tukin_annual")
    app.include_router(tukin_annual.create_router(lambda: DUCKDB_PATH))
except Exception as exc:
    print("API Pengelolaan Tukin Tahunan tidak terpasang:", exc)

# Satu Master SDM bersama untuk workflow absensi, SKP, dan final Tukin.
# Tabel master_data tetap diproyeksikan agar modul lama tidak perlu dirombak sekaligus.
try:
    shared_master = importlib.import_module("backend.shared_master")
    app.include_router(shared_master.create_router(lambda: DUCKDB_PATH))
except Exception as exc:
    shared_master = None
    print("API Master SDM Bersama tidak terpasang:", exc)

# Workflow khusus Penilaian SKP: preview, klasifikasi massal, review,
# persetujuan, dokumentasi, dan rekap tahunan.
try:
    skp_assessment = importlib.import_module("backend.skp_assessment")
    app.include_router(skp_assessment.create_router(lambda: DUCKDB_PATH))
except Exception as exc:
    print("API Penilaian SKP tidak terpasang:", exc)
EXCEL_CELL_TEXT_LIMIT = 32767
from backend.tukin_combined import create_router as create_combined_router
app.include_router(create_combined_router(lambda: DUCKDB_PATH))
from backend.final_tukin import create_router as create_final_tukin_router
app.include_router(create_final_tukin_router(lambda: DUCKDB_PATH))
from backend.application_reset import create_router as create_reset_router
app.include_router(create_reset_router(lambda: DUCKDB_PATH, lambda: DB_PATH))
from backend.module_reset import create_router as create_module_reset_router
app.include_router(create_module_reset_router(lambda: DUCKDB_PATH))
EXCEL_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
WORKFLOW_TABLES = {
    "config": "workflow_config",
    "master_data": "master_data",
    "raw_import": "raw_import",
    "processed_data": "workflow_records",
    "daily_data": "hitung_harian",
    "rekap_sdm": "rekap_sdm",
    "final_absensi": "final_absensi",
    "semifinal": "anomali",
    "final_skp": "final_skp",
    "final_kombinasi": "final_kombinasi",
    "final_combined_skp": "final_combined_skp",
}
# Derived workflow data only. Master SDM, workflow configuration, and imported
# source data are intentionally excluded from backend workflow reset.
RESETTABLE_WORKFLOW_TABLES = RESET_PROFILES['workflow_results'].tables

# Canonical SDM and archived Tukin are owned by their dedicated services.
# The legacy master_data projection is read-only to workflow clients.
WORKFLOW_WRITABLE = {key: table for key, table in WORKFLOW_TABLES.items() if key != 'master_data'}

# These fields are created conditionally by calc.js.  Normalizing them for
# every daily batch gives chunked sync one stable schema without inventing a
# business fallback: False/NULL are the same values used when the condition
# did not apply.
WORKFLOW_OPTIONAL_COLUMNS = {
    'daily_data': {'excused': False, '_lateMin': None, '_earlyMin': None},
}


def workflow_rows(source: str, value: Any) -> list:
    if source == 'config':
        if isinstance(value, list):
            if len(value) > 1:
                raise HTTPException(400, 'Konfigurasi workflow harus satu objek')
            value = value[0] if value else None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise HTTPException(400, 'JSON konfigurasi tidak valid') from exc
        if value is None:
            return []
        if not isinstance(value, dict):
            raise HTTPException(400, 'Konfigurasi workflow harus berupa objek')
        return [{key: item for key, item in value.items() if key != 'masterPegawai'}]
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise HTTPException(400, 'Data workflow harus berupa daftar objek')
    return value


def prepare_workflow_frame(source: str, rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column, default in WORKFLOW_OPTIONAL_COLUMNS.get(source, {}).items():
        if column not in frame.columns:
            frame[column] = default
    return prepare_database_frame(frame)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")
    return conn


def ensure_jobs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            type TEXT,
            status TEXT,
            payload TEXT,
            progress REAL,
            message TEXT,
            started_at TEXT,
            finished_at TEXT,
            result_table TEXT,
            row_count INTEGER
        )
        """
    )
    conn.commit()


# Ensure jobs table exists at startup
_conn_for_jobs_init = get_connection()
try:
    ensure_jobs_table(_conn_for_jobs_init)
finally:
    _conn_for_jobs_init.close()


def ensure_duckdb_master_schema() -> dict:
    """Create workflow schema without removing locks or moving a live WAL."""
    Path(DUCKDB_PATH).resolve().parent.mkdir(parents=True, exist_ok=True)
    dconn = duckdb.connect(DUCKDB_PATH)
    try:
        for table in WORKFLOW_TABLES.values():
            dconn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (_empty TEXT)')
        dconn.execute('CREATE TABLE IF NOT EXISTS workflow_flags (k TEXT PRIMARY KEY, verified INTEGER, updated_at TEXT)')
        dconn.execute('CREATE TABLE IF NOT EXISTS workflow_meta (table_name TEXT PRIMARY KEY, row_count INTEGER)')
        dconn.commit()
    finally:
        dconn.close()
    return {"status": "ok", "duckdb": DUCKDB_PATH, "tables": list(WORKFLOW_TABLES.values())}


@app.on_event("startup")
def startup_bootstrap() -> None:
    claim_database(DUCKDB_PATH)
    ensure_duckdb_master_schema()
    from backend.final_tukin import migrate as migrate_final_tukin
    migrate_final_tukin(DUCKDB_PATH)
    with get_connection() as conn:
        conn.execute("UPDATE jobs SET status='failed', message='Backend dimulai ulang. Jalankan kembali proses ini.' WHERE status IN ('queued','running')")


@app.on_event('shutdown')
def shutdown_jobs():
    _executor.shutdown(wait=True, cancel_futures=True)


def create_workflow_indexes(conn: sqlite3.Connection, table: str) -> None:
    columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if "bulan" in columns:
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_bulan" ON "{table}" ("bulan")')
    if "unit" in columns:
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_unit" ON "{table}" ("unit")')
    if "nip" in columns:
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_nip" ON "{table}" ("nip")')


def read_workflow_table(conn: sqlite3.Connection, table: str, bulan: str, unit: Optional[str], jabatan: Optional[str] = None) -> pd.DataFrame:
    """Backward-compatible read from SQLite for small workloads. Prefer DuckDB via read_workflow_table_global."""
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if not columns or columns == ["_empty"]:
        return pd.DataFrame()
    query = f'SELECT * FROM "{table}"'
    filters = []
    params = []
    if "bulan" in columns:
        filters.append('"bulan" = ?')
        params.append(bulan)
    if unit and "unit" in columns:
        filters.append('"unit" = ?')
        params.append(unit)
    if jabatan and "jabatan" in columns:
        filters.append('"jabatan" = ?')
        params.append(jabatan)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    return pd.read_sql_query(query, conn, params=params)


def read_workflow_table_global(table: str, bulan: str, unit: Optional[str], jabatan: Optional[str] = None) -> pd.DataFrame:
    """Try reading workflow table from DuckDB first, fall back to SQLite.
    Returns a pandas DataFrame.

    Optimized: apply bulan/unit filtering in DuckDB SQL so large tables are filtered server-side.
    """
    # Try DuckDB
    try:
        import duckdb as _d
        dconn = _d.connect(DUCKDB_PATH)
        try:
            # Build SQL with optional filters to let DuckDB do the heavy lifting
            where_clauses = []
            params = []
            # check if table has those columns via pragma; if not, skip filters
            try:
                cols = {r[1] for r in dconn.execute(f"PRAGMA table_info('{table}')").fetchall()}
            except Exception:
                cols = set()
            sql = f'SELECT * FROM "{table}"'
            if 'bulan' in cols and bulan:
                where_clauses.append('bulan = ?')
                params.append(bulan)
            if 'unit' in cols and unit:
                where_clauses.append('unit = ?')
                params.append(unit)
            if 'jabatan' in cols and jabatan:
                where_clauses.append('jabatan = ?')
                params.append(jabatan)
            if where_clauses:
                sql = sql + ' WHERE ' + ' AND '.join(where_clauses)
            df = dconn.execute(sql, params).fetchdf()
            return df
        finally:
            dconn.close()
    except Exception:
        # fallback to sqlite
        conn = get_connection()
        try:
            return read_workflow_table(conn, table, bulan, unit, jabatan)
        finally:
            conn.close()


def prepare_excel_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert workflow values to safe, bounded Excel cell values with a lightweight fast path."""
    if frame.empty:
        return frame
    result = frame.copy()
    result.columns = [safe_excel_value(column) for column in result.columns]
    for column in result.columns:
        series = result[column]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        result[column] = series.map(safe_excel_value)
    return result


def _write_workbook_stream(output: io.BytesIO, sheets: dict[str, pd.DataFrame]) -> None:
    """Write workbook to a BytesIO using a low-overhead xlsxwriter config for fast export."""
    with pd.ExcelWriter(output, engine='xlsxwriter', engine_kwargs={'options': {'in_memory': True}}) as writer:
        MAX_EXCEL_ROWS = 1048576

        def _write_df_split(df: pd.DataFrame, sheet_name: str) -> None:
            base = sheet_name[:28]
            if df.shape[0] <= MAX_EXCEL_ROWS:
                df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
                return
            total_rows = df.shape[0]
            parts = (total_rows + MAX_EXCEL_ROWS - 1) // MAX_EXCEL_ROWS
            for i in range(parts):
                start = i * MAX_EXCEL_ROWS
                end = min((i + 1) * MAX_EXCEL_ROWS, total_rows)
                part_name = f'{base}_{i + 1}'[:31]
                df.iloc[start:end].to_excel(writer, index=False, sheet_name=part_name)

        for sheet_name, df in sheets.items():
            if df is None or df.empty:
                continue
            _write_df_split(df, sheet_name)


def read_workflow_table_duckdb(table: str, bulan: str, unit: Optional[str] = None, jabatan: Optional[str] = None) -> pd.DataFrame:
    """Read a workflow table directly from DuckDB applying filters in SQL.
    If DuckDB is unavailable or the table does not exist, raise HTTPException(503).
    This enforces DuckDB as the canonical data source when backend is active.
    """
    try:
        import duckdb as _d
        dconn = _d.connect(DUCKDB_PATH)
        try:
            try:
                cols = {r[1] for r in dconn.execute(f"PRAGMA table_info('{table}')").fetchall()}
            except Exception:
                cols = set()
            if not cols:
                # Table missing in DuckDB
                raise HTTPException(status_code=404, detail=f"Table '{table}' not found in DuckDB")
            where_clauses = []
            params = []
            if 'bulan' in cols and bulan:
                where_clauses.append('bulan = ?')
                params.append(bulan)
            if 'unit' in cols and unit:
                where_clauses.append('unit = ?')
                params.append(unit)
            if 'jabatan' in cols and jabatan:
                where_clauses.append('jabatan = ?')
                params.append(jabatan)
            if where_clauses:
                sql = sql + ' WHERE ' + ' AND '.join(where_clauses)
            df = dconn.execute(sql, params).fetchdf()
            return df
        finally:
            dconn.close()
    except HTTPException:
        # propagate 404
        raise
    except Exception as e:
        # DuckDB unavailable / other I/O error
        raise HTTPException(status_code=503, detail=f'DuckDB error: {e}') from e


def safe_excel_value(value: Any) -> Any:
    """Handle arrays/objects, invalid XML characters, and Excel's cell limit."""
    if isinstance(value, (list, tuple, set, dict)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    elif isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = EXCEL_INVALID_XML_CHARS.sub("", value)
        return value[:EXCEL_CELL_TEXT_LIMIT]
    return value


def prepare_database_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Serialize nested browser values so SQLite can store every workflow field."""
    if frame.empty:
        return frame
    result = frame.copy()
    for column in result.columns:
        result[column] = result[column].map(serialize_database_value)
    return result


MASTER_SDM_COLUMNS = (
    "nip",
    "nama",
    "provinsi",
    "kabupatenKota",
    "kdAnakSatker",
    "jabatanOsdm",
    "statusTendik",
    "jabatan",
    "tukin",
)


def normalize_master_sdm_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize imported master SDM columns before writing to DuckDB."""
    if frame.empty:
        return pd.DataFrame(columns=MASTER_SDM_COLUMNS)
    aliases = {
        "kabupaten": "kabupatenKota",
        "kab_kota": "kabupatenKota",
        "kd_anaksatker": "kdAnakSatker",
        "kodeanaksatker": "kdAnakSatker",
        "jabatan_osdm": "jabatanOsdm",
        "status_tendik": "statusTendik",
        "tukinbruto": "tukin",
    }
    result = frame.copy()
    result.columns = [
        aliases.get(str(column).strip().lower(), str(column).strip())
        for column in result.columns
    ]
    for column in MASTER_SDM_COLUMNS:
        if column not in result.columns:
            result[column] = 0 if column == "tukin" else ""
    result = result[list(MASTER_SDM_COLUMNS)]
    result["nip"] = result["nip"].map(lambda value: str(value).strip() if pd.notna(value) else "")
    result = result[result["nip"] != ""].copy()
    result["tukin"] = pd.to_numeric(result["tukin"], errors="coerce").fillna(0)
    for column in MASTER_SDM_COLUMNS:
        if column != "tukin":
            result[column] = result[column].map(
                lambda value: str(value).strip() if pd.notna(value) else ""
            )
    return result.drop_duplicates(subset=["nip"], keep="last")


def serialize_database_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "evkin-export-api"}


@app.get("/api/health")
def api_health() -> dict:
    return health()


@app.get("/api/info")
def api_info() -> dict:
    return {
        "status": "ok",
        "service": "evkin-export-api",
        "frontend_served": INDEX_FILE.is_file(),
        "app_root": str(APP_ROOT),
    }


@app.get('/api/ping')
def api_ping() -> dict:
    """Lightweight endpoint to confirm connectivity from browser/clients.
    Returns status ok and server timestamp. Useful for quick network checks
    from the UI without exercising heavier endpoints.
    """
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "service": "evkin-export-api"}


@app.get("/")
@app.get("/index.html")
def serve_frontend() -> FileResponse:
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(INDEX_FILE, media_type="text/html; charset=utf-8")


@app.get("/api/workflow/health")
def workflow_health() -> dict:
    """Minimal readiness check for the master workflow database."""
    info = ensure_duckdb_master_schema()
    return {"status": "ok", "ready": True, **info}


@app.post("/api/workflow/sync")
def sync_workflow(payload: dict[str, Any]) -> dict:
    """Replace backend workflow tables with the browser's current workflow data.
    Store workflow tables in DuckDB (EVKIN_ABSENSI_DB) for efficient analytics.
    """
    invalid = set(payload) - set(WORKFLOW_WRITABLE)
    if invalid:
        raise HTTPException(400, 'Sumber bukan milik workflow: ' + ', '.join(sorted(invalid)))
    prepared = {source: workflow_rows(source, value) for source, value in payload.items()}
    ensure_duckdb_master_schema()
    table_map = {source: WORKFLOW_WRITABLE[source] for source in payload}
    counts = {}
    # write to DuckDB
    import duckdb as _duckdb
    dconn = _duckdb.connect(DUCKDB_PATH)
    try:
        dconn.execute('BEGIN TRANSACTION')
        for source, table in table_map.items():
            rows = prepared[source]
            # drop existing
            try:
                dconn.execute(f'DROP TABLE IF EXISTS "{table}"')
            except Exception:
                pass
            if rows:
                frame = prepare_workflow_frame(source, rows)
                # register and create/replace
                dconn.register('tmp_frame', frame)
                create_table_from_relation(dconn, table, 'tmp_frame')
                try:
                    dconn.unregister('tmp_frame')
                except Exception:
                    pass
            else:
                # create empty placeholder
                dconn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (_empty TEXT)')
            counts[source] = len(rows)
        dconn.commit()
    except Exception:
        dconn.rollback()
        raise
    finally:
        dconn.close()

    # Keep SQLite in sync for backward compatibility (lightweight copy of counts only)
    conn = get_connection()
    try:
        for source, table in table_map.items():
            # create a simple metadata table in SQLite to record presence
            conn.execute('CREATE TABLE IF NOT EXISTS workflow_meta (table_name TEXT PRIMARY KEY, row_count INTEGER)')
            conn.execute('REPLACE INTO workflow_meta (table_name, row_count) VALUES (?, ?)', (table, counts.get(source, 0)))
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "counts": counts}


@app.get("/api/workflow/state")
def get_workflow_state() -> dict:
    """Return the current workflow state from DuckDB so the browser can hydrate from the master database."""
    ensure_duckdb_master_schema()
    import duckdb as _duckdb
    dconn = _duckdb.connect(DUCKDB_PATH)
    payload: dict[str, Any] = {}
    try:
        for source, table in WORKFLOW_TABLES.items():
            if source == 'master_data':
                continue
            try:
                df = dconn.execute(f'SELECT * FROM "{table}"').fetchdf()
            except Exception:
                df = pd.DataFrame()
            if df.empty or set(df.columns) == {'_empty'}:
                rows = []
            else:
                rows = df.to_dict(orient='records')
                structured_fields = ({'jamDasar', 'flexi', 'holidays', 'jabatanMaster', 'keterlambatanTiers',
                                      'pulangCepatTiers', 'jenisNoPotongan', 'leavePeriods', '_workflow'}
                                     if source == 'config' else {'flags', 'issues', 'tanggal', 'tanggalMasukObj', 'tanggalPulangObj'})
                for row in rows:
                    for field in structured_fields:
                        value = row.get(field)
                        if isinstance(value, str) and value[:1] in ('[', '{'):
                            try:
                                row[field] = json.loads(value)
                            except ValueError:
                                pass
            if source == 'config':
                if not rows:
                    payload[source] = None
                else:
                    payload[source] = {key: value for key, value in rows[0].items() if key != 'masterPegawai'}
            else:
                payload[source] = rows
    finally:
        dconn.close()
    return {"status": "ok", "data": payload}


@app.get("/api/master-sdm")
def get_master_sdm(q: Optional[str] = Query(None, description='Query string to search NIP/Nama/Jabatan'), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=1000), jabatan: Optional[str] = Query(None), unit: Optional[str] = Query(None), sort: Optional[str] = Query(None, description='Sort column, e.g. nip or nama')) -> dict:
    """Read the SDM master list with optional pagination and filtering.
    - q: fulltext-like search against nip, nama, jabatan
    - page, per_page: pagination
    - jabatan, unit: exact filters
    - sort: column name to sort by (safe list applied)

    Returns rows, total count, page metadata.
    """
    ensure_duckdb_master_schema()

    # The shared SDM tables are the source of truth.  The legacy ``master_data``
    # table is only a compatibility projection and may legitimately be empty
    # after a browser workflow sync.  Final must therefore never depend on that
    # projection for its Tukin lookup.
    if shared_master is not None:
        canonical = shared_master.SharedMasterService(DUCKDB_PATH).list(
            q=q or "", page=page, per_page=per_page, active=True,
            jabatan=jabatan or "", unit=unit or "", sort=sort or ""
        )
        rows = []
        for source in canonical.get("rows", []):
            row = dict(source)
            row.update({
                "kabupatenKota": source.get("kabupaten_kota", ""),
                "kdAnakSatker": source.get("kd_anak_satker", ""),
                "jabatanOsdm": source.get("jabatan_osdm", ""),
                "statusTendik": source.get("status_tendik", ""),
                "jenisSdm": source.get("jenis_sdm", ""),
                "statusKepegawaian": source.get("employment_status", ""),
                "kelasJabatan": source.get("kelas_jabatan"),
                "wilayah3T": source.get("wilayah_3t", False),
                "berhakTukin": source.get("eligible", True),
                "tukin": source.get("tukin_gross", 0),
                "bank": source.get("bank_name", ""),
                "noRekening": source.get("account_number", ""),
                "namaPemilikRekening": source.get("account_holder", ""),
            })
            rows.append(row)
        return {
            "status": "ok", "rows": rows, "count": canonical.get("total", 0),
            "page": canonical.get("page", page), "per_page": canonical.get("per_page", per_page),
            "total_pages": canonical.get("pages", 0), "source": "shared-master",
        }

    raise HTTPException(503, 'Layanan Master SDM kanonis tidak tersedia')


@app.post("/api/master-sdm")
def upsert_master_sdm(payload: dict[str, Any]) -> dict:
    """Compatibility import; canonical history is always written first."""
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if rows is None and isinstance(payload, list):
        rows = payload
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="Payload harus berupa list rows")
    if not rows:
        raise HTTPException(status_code=400, detail="Daftar kosong tidak boleh digunakan untuk reset. Gunakan reset administratif Master SDM")
    if shared_master is None:
        raise HTTPException(status_code=503, detail="Layanan Master SDM kanonis tidak tersedia")
    try:
        result = shared_master.SharedMasterService(DUCKDB_PATH).ingest_rows(
            rows, datetime.now().date(), "LEGACY_MASTER_IMPORT", "OPERATOR_KOMPATIBILITAS", confirmed=True
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Master SDM gagal diperbarui: {exc}") from exc
    return {"status": "ok", "count": result["committed"], "rows": rows}


@app.post("/api/master-sdm/upsert")
def upsert_master_sdm_row(payload: dict[str, Any]) -> dict:
    """Upsert one or more master SDM rows by NIP.
    Accepts payload: { rows: [...] } or a single row dict or a list of rows.
    New rows override existing rows with the same 'nip'.
    """
    ensure_duckdb_master_schema()
    # Normalize payload to list of rows
    rows = None
    if isinstance(payload, dict) and 'rows' in payload:
        rows = payload.get('rows')
    elif isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        # single row object
        rows = [payload]

    if rows is None:
        rows = []

    # Accept a single row dict as well
    if isinstance(rows, dict):
        rows = [rows]

    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail='Payload harus berupa list rows atau objek row')

    # Basic validation: each row must have 'nip'
    for r in rows:
        if not isinstance(r, dict) or not r.get('nip'):
            raise HTTPException(status_code=400, detail="Setiap baris harus berupa objek dengan kunci 'nip'")

    if shared_master is None:
        raise HTTPException(status_code=503, detail="Layanan Master SDM kanonis tidak tersedia")
    try:
        shared_master.SharedMasterService(DUCKDB_PATH).ingest_rows(
            rows, datetime.now().date(), "LEGACY_MASTER_UPSERT", "OPERATOR_KOMPATIBILITAS", confirmed=True
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Master SDM gagal diperbarui: {exc}") from exc

    return {"status": "ok", "upserted": len(rows)}


@app.post("/api/master-sdm/delete")
def delete_master_sdm(payload: dict[str, Any]) -> dict:
    """Delete master SDM rows by NIP(s).
    Payload: { nips: ["nip1", "nip2"] } or list of nips.
    """
    ensure_duckdb_master_schema()
    nips = None
    if isinstance(payload, dict) and 'nips' in payload:
        nips = payload.get('nips')
    elif isinstance(payload, list):
        nips = payload
    elif isinstance(payload, dict) and payload.get('nip'):
        nips = [payload.get('nip')]

    if not nips:
        raise HTTPException(status_code=400, detail='Payload harus berisi daftar nips untuk dihapus')

    if isinstance(nips, str):
        nips = [nips]
    nips = [str(x) for x in nips]

    # Compatibility endpoint: in the canonical master this is a soft delete.
    # Historical payments and period snapshots therefore remain traceable.
    deactivated = 0
    if shared_master is not None:
        master_service = shared_master.SharedMasterService(DUCKDB_PATH)
        master_service.list(page=1, per_page=1)  # initializes/backfills legacy data once
        for nip in nips:
            try:
                master_service.set_active(nip, False, "Dinonaktifkan dari modul Master SDM", "OPERATOR_KOMPATIBILITAS")
                deactivated += 1
            except KeyError:
                pass

    return {"status": "ok", "deleted": 0, "deactivated": deactivated, "recoverable": True}


@app.get("/api/workflow/reset/preview")
@app.get("/api/workflow/reset-backend/preview")
def preview_legacy_workflow_reset() -> dict:
    """Legacy-path preview backed by the canonical workflow-results profile."""
    try:
        return ResetService(DUCKDB_PATH).preview('workflow_results')
    except (ValueError, OSError, duckdb.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/reset")
def reset_workflow(payload: dict[str, Any] | None = None) -> dict:
    """Legacy adapter: reset derived workflow data through ResetService."""
    try:
        return ResetService(DUCKDB_PATH).execute(
            'workflow_results', payload or {}, source='LEGACY_WORKFLOW_RESET_API'
        )
    except (ValueError, OSError, duckdb.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/reset-backend")
def reset_backend_workflow(payload: dict[str, Any] | None = None) -> dict:
    """Named endpoint for the UI's explicit backend workflow reset action."""
    return reset_workflow(payload)


@app.post("/api/workflow/delete-absensi")
def delete_absensi_workflow(payload: dict[str, Any]) -> dict:
    """Legacy phrase adapter for the canonical full-workflow reset profile."""
    if payload.get('confirmation') != 'HAPUS ABSENSI':
        raise HTTPException(status_code=400, detail='Konfirmasi HAPUS ABSENSI diperlukan.')
    service = ResetService(DUCKDB_PATH)
    plan = service.preview('workflow')
    try:
        return service.execute('workflow', {
            'preview_token': plan['preview_token'],
            'confirmation': plan['confirmation'],
            'actor': 'LEGACY_WORKFLOW_API',
            'reason': 'Compatibility reset HAPUS ABSENSI',
        }, source='LEGACY_DELETE_ABSENSI_API')
    except (ValueError, OSError, duckdb.Error) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflow/sync-table")
def sync_workflow_table(payload: dict[str, Any]) -> dict:
    """Store one workflow table batch to keep large sync requests bounded.
    Writes directly into DuckDB for large imports (import_batches integration).
    """
    source = str(payload.get("source") or "")
    table = WORKFLOW_WRITABLE.get(source)
    if not table:
        raise HTTPException(status_code=400, detail=f"Workflow table tidak dikenal: {source}")
    rows = workflow_rows(source, payload.get("rows"))
    ensure_duckdb_master_schema()
    replace = bool(payload.get("replace", False))
    frame = prepare_workflow_frame(source, rows) if rows else None

    import duckdb as _duckdb
    dconn = _duckdb.connect(DUCKDB_PATH)
    try:
        dconn.execute('BEGIN TRANSACTION')
        if replace:
            dconn.execute(f'DROP TABLE IF EXISTS "{table}"')
        if rows:
            dconn.register('tmp_frame', frame)
            if replace:
                create_table_from_relation(dconn, table, 'tmp_frame')
            else:
                exists = dconn.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='main' AND table_name=?", [table]
                ).fetchone()[0]
                if exists:
                    insert_relation_by_name(dconn, table, 'tmp_frame')
                else:
                    create_table_from_relation(dconn, table, 'tmp_frame')
            try:
                dconn.unregister('tmp_frame')
            except Exception:
                pass
        elif replace:
            dconn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (_empty TEXT)')
        cnt = dconn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        dconn.commit()
    except Exception:
        dconn.rollback()
        raise
    finally:
        dconn.close()

    # Update sqlite meta
    conn = get_connection()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS workflow_meta (table_name TEXT PRIMARY KEY, row_count INTEGER)')
        # Count was captured in the same transaction as the write.
        conn.execute('REPLACE INTO workflow_meta (table_name, row_count) VALUES (?, ?)', (table, cnt))
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "source": source, "rows": len(rows), "replace": replace}


@app.post("/api/workflow/mark-semifinal")
def mark_semifinal(payload: dict[str, Any]):
    """Lightweight endpoint to record semifinal verification for a month.
    Stores a small flag in SQLite so the frontend can mark progress without re-uploading large workflow tables.
    Also writes the same flag into DuckDB workflow store so all workflow metadata is co-located.
    """
    bulan = str(payload.get('bulan') or '')
    verified = bool(payload.get('verified'))
    key = f'semifinal:{bulan}'

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", bulan):
        raise HTTPException(400, "Periode harus berformat YYYY-MM.")
    if verified:
        try:
            result = record_verification(DUCKDB_PATH, bulan)
        except ValueError as exc:
            raise HTTPException(409, {"code": "WORKFLOW_NOT_READY", "message": str(exc),
                                      "blocking_reasons": [str(exc)]}) from exc
        except Exception as exc:
            raise HTTPException(503, "Gagal menyimpan status semifinal ke DuckDB.") from exc
    else:
        import duckdb as _d_local
        with _d_local.connect(DUCKDB_PATH) as dconn_local:
            dconn_local.execute('CREATE TABLE IF NOT EXISTS workflow_flags (k TEXT PRIMARY KEY, verified INTEGER, updated_at TEXT)')
            dconn_local.execute(
                "INSERT OR REPLACE INTO workflow_flags (k, verified, updated_at) VALUES (?, 0, ?)",
                [key, datetime.utcnow().isoformat()],
            )
        result = {"status": "ok", "bulan": bulan, "verified": False}

    # Keep the legacy SQLite flag as a compatibility projection only after the
    # canonical DuckDB transaction has committed.
    conn = get_connection()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS workflow_flags (k TEXT PRIMARY KEY, v TEXT, updated_at TEXT)')
        conn.execute('REPLACE INTO workflow_flags (k, v, updated_at) VALUES (?, ?, ?)',
                     (key, '1' if verified else '0', datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()

    return {**result, "bulan": bulan, "verified": verified}


@app.get("/api/workflow/flags")
def get_workflow_flags(bulan: Optional[str] = Query(None, description="Bulan filter e.g. 2026-08")):
    """Return workflow flag rows (from DuckDB where possible, fallback to SQLite).
    If 'bulan' is provided, only return flags that end with ':{bulan}' (e.g., 'semifinal:2026-08').
    """
    try:
        import duckdb as _d
        dconn = _d.connect(DUCKDB_PATH)
        try:
            try:
                df = dconn.execute("SELECT k, verified, updated_at FROM workflow_flags").fetchdf()
            except Exception:
                # Table may not exist
                return {"status": "ok", "flags": {}}
            if df.empty:
                return {"status": "ok", "flags": {}}
            if bulan:
                suffix = ':' + bulan
                # pandas str accessor is available on object dtype
                try:
                    df = df[df['k'].str.endswith(suffix)]
                except Exception:
                    # if for some reason df['k'] is not string-typed, coerce
                    df['k'] = df['k'].astype(str)
                    df = df[df['k'].str.endswith(suffix)]
            flags = {}
            for _, row in df.iterrows():
                flags[row['k']] = {"verified": bool(int(row['verified'])), "updated_at": row['updated_at']}
            return {"status": "ok", "flags": flags}
        finally:
            dconn.close()
    except Exception:
        # fallback to sqlite
        conn = get_connection()
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS workflow_flags (k TEXT PRIMARY KEY, v TEXT, updated_at TEXT)')
            if bulan:
                key = f'semifinal:{bulan}'
                rows = conn.execute('SELECT k, v, updated_at FROM workflow_flags WHERE k = ?', (key,)).fetchall()
            else:
                rows = conn.execute('SELECT k, v, updated_at FROM workflow_flags').fetchall()
            flags = {}
            for r in rows:
                flags[r['k']] = {"verified": (r['v'] == '1'), "updated_at": r['updated_at']}
            return {"status": "ok", "flags": flags}
        finally:
            conn.close()


@app.post("/api/export/final")
def export_final(
    bulan: str = Query(..., description="Bulan yang akan diekspor, contoh: 2026-08"),
    unit: Optional[str] = Query(None),
    jabatan: Optional[str] = Query(None, description="Filter berdasarkan jabatan (optional)"),
    smart_mode: bool = Query(False),
):
    try:
        # Enforce reading from DuckDB workflow store (backend is canonical source when active)
        df = read_workflow_table_duckdb("final_absensi", bulan, unit, jabatan)
        if df is None or df.empty:
            # If table is missing or empty in DuckDB, report not found
            raise HTTPException(status_code=404, detail=f"Tidak ada data final untuk bulan {bulan} di backend DuckDB")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            prepare_excel_frame(df).to_excel(writer, index=False, sheet_name="FINAL ABSENSI")

        output.seek(0)
        filename = f"EVKIN_FINAL_{bulan}_{'SMART' if smart_mode else 'FULL'}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - minimal service guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/export/workbook")
def export_workbook(
    bulan: str = Query(...),
    unit: Optional[str] = Query(None),
    jabatan: Optional[str] = Query(None, description="Filter berdasarkan jabatan (optional)"),
    sheet_names: Optional[str] = Query(None, description="Daftar sheet yang dipilih, dipisah koma"),
):
    try:
        selected = []
        if sheet_names:
            selected = [s.strip() for s in sheet_names.split(",") if s.strip()]

        tables = {
            "DATA SUMBER": "raw_import",
            "HITUNG HARIAN": "hitung_harian",
            "REKAP SDM": "rekap_sdm",
            "FINAL ABSENSI": "final_absensi",
            "FINAL + SKP": "final_skp",
            "FINAL KOMBINASI": "final_kombinasi",
            "FINAL + SKP KOMBINASI": "final_combined_skp",
        }

        sheets = {}
        for name, table in tables.items():
            if selected and name not in selected:
                continue
            # Enforce DuckDB as canonical source for export when backend is active
            df_table = read_workflow_table_duckdb(table, bulan, unit, jabatan)
            sheets[name] = prepare_excel_frame(df_table)

        sheets = {name: frame for name, frame in sheets.items() if not frame.empty}
        if not sheets:
            raise HTTPException(status_code=404, detail=f"Tidak ada data pada backend DuckDB untuk bulan {bulan}")

        output = io.BytesIO()
        _write_workbook_stream(output, sheets)
        output.seek(0)
        filename = f"EVKIN_EXPORT_{bulan}.xlsx"

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - minimal service guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get('/api/import/template')
def api_import_template(source: str = Query(..., description='Sumber import (contoh: raw_import, final_absensi, master_data)'), format: str = Query('xlsx', description='xlsx or csv')):
    """Generate and return an example import template for the requested workflow source.
    Returns an XLSX (default) or CSV file the user can download to prepare imports.
    """
    try:
        def _template_for(source_key: str) -> Optional[pd.DataFrame]:
            s = (source_key or '').strip()
            if s == 'raw_import':
                cols = ['nip', 'nama', 'jabatan', 'unit', 'tanggal', 'zona', 'masukMin', 'pulangMin', 'masukNormMin', 'pulangNormMin', 'masukNormMinAdd', 'pulangNormMinAdd', 'jenis']
                example = ['10001', 'Pegawai A', 'Guru', 'SDM', '2026-08-01', 'WITA', '450', '1020', '', '', '', '', '']
                return pd.DataFrame([example], columns=cols)
            if s == 'final_absensi':
                cols = ['nip', 'nama', 'jabatan', 'bulan', 'unit', 'tukin', 'komponen', 'potPct', 'nominal', 'finalDibayar']
                example = ['10001', 'Pegawai A', 'Guru', '2026-08', 'SDM', 2500000, 750000, 2.5, 30000, 2455000]
                return pd.DataFrame([example], columns=cols)
            if s == 'master_data':
                cols = ['nip', 'nama', 'jabatan', 'unit', 'email', 'telp']
                example = ['10001', 'Pegawai A', 'Guru', 'SDM', 'a@example.com', '08123456789']
                return pd.DataFrame([example], columns=cols)
            if s in ('daily_data', 'hitung_harian'):
                cols = ['nip', 'nama', 'jabatan', 'bulan', 'tanggal', 'zona', 'jamMasuk', 'jamPulang', 'durasi', 'jamNormalisasi', 'jamMasukAsli', 'jamPulangAsli', 'durasiMin', 'metode', 'jenis']
                example = ['10001', 'Pegawai A', 'Guru', '2026-08', '2026-08-01', 'WIB', '07:35', '16:05', '8h 30m', '', '07:35', '16:05', 510, 'reguler', '']
                return pd.DataFrame([example], columns=cols)
            if s == 'rekap_sdm':
                cols = ['nip', 'nama', 'jabatan', 'bulan', 'unit', 'totalHarian', 'totalPotongan', 'finalDibayar']
                example = ['10001', 'Pegawai A', 'Guru', '2026-08', 'SDM', 20, 30000, 2455000]
                return pd.DataFrame([example], columns=cols)
            if s == 'semifinal' or s == 'anomali':
                cols = ['nip', 'tanggal', 'zona', 'issue', 'notes']
                example = ['10001', '2026-08-01', 'WITA', 'Missing clock-out', 'Periksa manual']
                return pd.DataFrame([example], columns=cols)
            if s in ('final_skp', 'final_kombinasi', 'final_combined_skp'):
                cols = ['nip', 'nama', 'jabatan', 'bulan', 'skpScore', 'finalValue']
                example = ['10001', 'Pegawai A', 'Guru', '2026-08', 85.5, 2455000]
                return pd.DataFrame([example], columns=cols)
            if s == 'config' or s == 'workflow_config':
                cols = ['k', 'v']
                example = ['jamDasar', '{"senKam": {"masuk": "07:30", "pulang": "16:00"}, "jumat": {"masuk": "07:30","pulang": "16:30"}}']
                return pd.DataFrame([example], columns=cols)
            # unknown source
            return None

        df = _template_for(source)
        if df is None:
            raise HTTPException(status_code=404, detail=f"Unknown import source: {source}")

        if (format or '').lower() == 'csv':
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            buf.seek(0)
            data = buf.getvalue().encode('utf-8')
            return StreamingResponse(io.BytesIO(data), media_type='text/csv', headers={"Content-Disposition": f'attachment; filename="TEMPLATE_{source}.csv"'})

        # default: xlsx
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            prepare_excel_frame(df).to_excel(writer, index=False, sheet_name='TEMPLATE')
        out.seek(0)
        return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="TEMPLATE_{source}.xlsx"'})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/export/seed-demo")
def seed_demo_data() -> dict:
    conn = get_connection()
    conn.execute("DROP TABLE IF EXISTS final_absensi")
    conn.execute(
        """
        CREATE TABLE final_absensi (
            nip TEXT,
            nama TEXT,
            jabatan TEXT,
            bulan TEXT,
            unit TEXT,
            tukin REAL,
            komponen REAL,
            potPct REAL,
            nominal REAL,
            finalDibayar REAL
        )
        """
    )

    demo_rows = [
        ("10001", "Pegawai A", "Guru", "2026-08", "SDM", 2500000, 750000, 2.5, 30000, 2455000),
        ("10002", "Pegawai B", "Guru", "2026-08", "SDM", 2600000, 780000, 1.8, 22000, 2578000),
        ("10003", "Pegawai C", "TU", "2026-08", "SDM", 2400000, 720000, 3.4, 41000, 2359000),
    ]
    conn.executemany(
        "INSERT INTO final_absensi (nip, nama, jabatan, bulan, unit, tukin, komponen, potPct, nominal, finalDibayar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        demo_rows,
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Demo data seeded"}


# ------------------ Background compute jobs (hitung harian) ------------------
# Background export job implementation (background file generation for Excel/CSV)
import tempfile
import os

EXPORT_DIR = str(Path(__file__).resolve().parent / 'exports')
os.makedirs(EXPORT_DIR, exist_ok=True)


@database_job
def run_export_job(job_id: str, bulan: str, unit: Optional[str], sheet_names: list, fmt: str = 'xlsx', jabatan: Optional[str] = None, expected_final: Optional[dict] = None) -> str:
    """Background worker to generate export file. Returns path to result file.
    Writes progress updates to jobs table. Supports 'xlsx' and 'csv' formats (csv -> zip of per-sheet csvs).
    """
    conn = get_connection()
    temp_path = None
    verified_final = None
    try:
        _update_job(job_id, status='running', started_at=_now_iso(), progress=0.01, message='Starting export')
        try:
            if fmt not in ('xlsx', 'csv'):
                fmt = 'xlsx'
            # Build sheet -> table mapping same as export_workbook
            tables = {
                'DATA SUMBER': 'raw_import',
                'HITUNG HARIAN': 'hitung_harian',
                'REKAP SDM': 'rekap_sdm',
                'FINAL ABSENSI': 'final_absensi',
                'FINAL + SKP': 'final_skp',
                'FINAL KOMBINASI': 'final_kombinasi',
                'FINAL + SKP KOMBINASI': 'final_combined_skp',
            }
            selected = sheet_names or list(tables.keys())
            total_sheets = len(selected)
            written_sheets = 0

            # Prepare file paths
            result_path = None
            if fmt == 'xlsx':
                result_path = os.path.join(EXPORT_DIR, f'{job_id}.xlsx')
                temp_path = os.path.join(EXPORT_DIR, f'{job_id}.tmp.xlsx')
                # pandas emits cells column-by-column. XlsxWriter's
                # constant_memory mode flushes earlier rows, silently dropping
                # later columns. Use normal mode and keep disk-backed output.
                with pd.ExcelWriter(
                    temp_path,
                    engine='xlsxwriter',
                    engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}},
                ) as writer:
                    for name in selected:
                        tbl = tables.get(name)
                        if not tbl:
                            written_sheets += 1
                            _update_job(
                                job_id,
                                progress=0.05 + 0.9 * (written_sheets / max(1, total_sheets)),
                                message=f'Skip sheet {name}',
                            )
                            continue
                        _update_job(
                            job_id,
                            progress=0.05 + 0.9 * (written_sheets / max(1, total_sheets)),
                            message=f'Preparing sheet {name}',
                        )
                        try:
                            df = read_workflow_table_duckdb(tbl, bulan, unit, jabatan)
                        except HTTPException as he:
                            if he.status_code != 404:
                                raise
                            df = pd.DataFrame()
                        if name == 'FINAL ABSENSI':
                            verified_final = final_manifest(df.to_dict('records'))
                            if expected_final is not None:
                                assert_manifest(verified_final, expected_final)
                            if not verified_final['row_count']:
                                raise ValueError('Final Absensi kosong untuk periode yang dipilih')
                        if df is None or df.empty:
                            # write empty sheet placeholder
                            pd.DataFrame([['-']]).to_excel(writer, index=False, header=[name[:30]], sheet_name=name[:31])
                        else:
                            prepare_excel_frame(df).to_excel(writer, index=False, sheet_name=(name[:31]))
                        written_sheets += 1
                        _update_job(
                            job_id,
                            progress=0.05 + 0.9 * (written_sheets / max(1, total_sheets)),
                            message=f'Sheet {name} selesai ({written_sheets}/{total_sheets})',
                        )
                if verified_final is not None:
                    _update_job(job_id, progress=.96, message='Memeriksa jumlah baris, NIP dan total nominal dalam Excel...')
                    verify_final_xlsx(temp_path, verified_final)
                # Only publish the file after validation succeeds.
                os.replace(temp_path, result_path)
                if verified_final is not None:
                    Path(result_path + '.validation.json').write_text(json.dumps(verified_final), encoding='utf-8')
            else:
                # CSV: create zip of CSV files per sheet
                import zipfile
                result_path = os.path.join(EXPORT_DIR, f'{job_id}.zip')
                temp_path = os.path.join(EXPORT_DIR, f'{job_id}.tmp.zip')
                with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    for name in selected:
                        tbl = tables.get(name)
                        _update_job(job_id, progress=0.01 + 0.8 * (written_sheets / max(1, total_sheets)), message=f'Preparing CSV {name}')
                        try:
                            df = read_workflow_table_duckdb(tbl, bulan, unit, jabatan)
                        except HTTPException as exc:
                            if exc.status_code != 404:
                                raise
                            df = pd.DataFrame()
                        if name == 'FINAL ABSENSI':
                            verified_final = final_manifest(df.to_dict('records'))
                            if expected_final is not None:
                                assert_manifest(verified_final, expected_final)
                            if not verified_final['row_count']:
                                raise ValueError('Final Absensi kosong untuk periode yang dipilih')
                        csv_name = f"{name.replace(' ', '_')}.csv"
                        if df is None or df.empty:
                            # write placeholder
                            data = "-\n"
                            zf.writestr(csv_name, data)
                        else:
                            # stream df to csv bytes
                            csv_buf = df.to_csv(index=False).encode('utf-8')
                            if name == 'FINAL ABSENSI':
                                import io
                                reread = pd.read_csv(io.BytesIO(csv_buf), dtype=str, keep_default_na=False)
                                assert_manifest(final_manifest(reread.to_dict('records')), verified_final)
                            zf.writestr(csv_name, csv_buf)
                        written_sheets += 1
                os.replace(temp_path, result_path)
            # finalize
            message = ('Validasi lulus: ' + str(verified_final['row_count']) + ' baris Final; bruto ' + verified_final['gross'] + ', potongan ' + verified_final['deduction'] + ', dibayar ' + verified_final['paid']) if verified_final else 'Export complete'
            _update_job(job_id, status='finished', finished_at=_now_iso(), progress=1.0, message=message, result_table=result_path)
            return result_path
        except Exception as e:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            _update_job(job_id, status='failed', finished_at=_now_iso(), message=f'Export failed: {e}', progress=0.0)
            raise
    finally:
        conn.close()

def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _update_job(job_id: str, **fields) -> None:
    conn = get_connection()
    try:
        sets = ', '.join([f'"{k}" = ?' for k in fields.keys()])
        params = list(fields.values()) + [job_id]
        conn.execute(f'UPDATE jobs SET {sets} WHERE id = ?', params)
        conn.commit()
    finally:
        conn.close()




def compute_harian_core(bulan: str, time_mode: str = 'original', unit: Optional[str] = None, job_id: Optional[str] = None) -> int:
    """
    Compute hitung_harian for given bulan and write to 'hitung_harian' table.
    This implementation ports the rules from calc.js and processes data in chunks,
    updating job progress to the jobs table and checking for cancellation.
    Returns number of rows written.
    """
    conn = get_connection()
    try:
        # Load configuration (workflow_config) if present
        cfg_row = None
        try:
            cur = conn.execute('SELECT * FROM workflow_config LIMIT 1')
            cfg_row = cur.fetchone()
        except Exception:
            cfg_row = None

        # Fallback defaults (mirror state.defaultConfig in frontend)
        default_cfg = {
            'holidays': [],
            'jabatanMaster': [],
            'masterPegawai': [],
            'jenisNoPotongan': [],
            'leavePeriods': [],
            'jamDasar': {'senKam': {'masuk': '07:30', 'pulang': '16:00'}, 'jumat': {'masuk': '07:30', 'pulang': '16:30'}},
            'flexi': {'enabled': True, 'masukStart': '07:31', 'masukEnd': '08:00', 'kompensasiSenKam': '16:30', 'kompensasiJumat': '17:00'},
            'keterlambatanTiers': [{'max': 30, 'pct': 0.5}, {'max': 60, 'pct': 1}, {'max': 90, 'pct': 1.5}, {'max': 120, 'pct': 2}, {'max': 9999, 'pct': 3}],
            'pulangCepatTiers': [{'max': 30, 'pct': 0.5}, {'max': 60, 'pct': 1}, {'max': 90, 'pct': 1.5}, {'max': 120, 'pct': 2}, {'max': 9999, 'pct': 3}],
            'minDurasiJam': 7.5,
            'potonganTidakLengkap': 3,
        }

        cfg = {}
        if cfg_row:
            # convert sqlite3.Row to dict and attempt to parse JSON fields
            rowd = dict(cfg_row)
            for k, v in rowd.items():
                if v is None:
                    continue
                if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                    try:
                        cfg[k] = json.loads(v)
                    except Exception:
                        cfg[k] = v
                else:
                    cfg[k] = v
        # merge defaults
        for k, v in default_cfg.items():
            if k not in cfg:
                cfg[k] = v

        # Normalize some cfg keys
        if isinstance(cfg.get('holidays'), list):
            holiday_set = {h.get('d') for h in cfg.get('holidays', []) if isinstance(h, dict) and h.get('d')}
            holiday_name = {h.get('d'): h.get('n') for h in cfg.get('holidays', []) if isinstance(h, dict)}
        else:
            holiday_set = set()
            holiday_name = {}

        jab_method = {}
        for j in cfg.get('jabatanMaster') or []:
            name = (j.get('nama') if isinstance(j, dict) else None) or j
            metode = (j.get('metode') if isinstance(j, dict) else None) or 'reguler'
            if name:
                jab_method[str(name).strip().lower()] = metode

        peg_by_nip = {}
        if shared_master is None:
            raise RuntimeError('Layanan Master SDM kanonis tidak tersedia')
        master_rows = shared_master.SharedMasterService(DUCKDB_PATH).list(per_page=1000000, active=True)['rows']
        for p in master_rows:
            if isinstance(p, dict) and 'nip' in p:
                peg_by_nip[str(p['nip']).strip()] = p

        jenis_no = set([s.strip().lower() for s in (cfg.get('jenisNoPotongan') or []) if isinstance(s, str)])

        leave_periods = []
        for lp in cfg.get('leavePeriods') or []:
            if isinstance(lp, dict) and lp.get('nip') and lp.get('mulai') and lp.get('selesai'):
                leave_periods.append({'nip': str(lp.get('nip')).strip(), 'mulai': lp.get('mulai'), 'selesai': lp.get('selesai'), 'jenis': lp.get('jenis', '')})

        # Load raw_import filtered by bulan and unit
        # Prefer DuckDB for large imports
        try:
            import duckdb as _d
            dconn = _d.connect(DUCKDB_PATH)
            try:
                df_all = dconn.execute('SELECT * FROM "raw_import"').fetchdf()
            finally:
                dconn.close()
        except Exception:
            try:
                df_all = pd.read_sql_query('SELECT * FROM raw_import', conn)
            except Exception:
                return 0
        if df_all is None or (hasattr(df_all, 'empty') and df_all.empty):
            return 0

        # Normalize column names
        col_map = {c: c.strip().lower().replace(' ', '').replace('_', '') for c in df_all.columns}
        df_all.rename(columns=col_map, inplace=True)

        # Helper pick
        def pick(cols):
            for c in cols:
                if c in df_all.columns:
                    return c
            return None

        col_nip = pick(['nip', 'n'])
        col_nama = pick(['nama', 'name'])
        col_tanggal = pick(['tanggal', 'tgl', 'date'])
        col_jam_masuk = pick(['jammansuk', 'jammasuk', 'masuk', 'jammasuk'])
        col_jam_pulang = pick(['jampulang', 'pulang', 'jampulang'])
        col_zona = pick(['zona', 'zone'])
        col_jenis = pick(['jenis', 'keterangan'])

        df_all[col_tanggal] = pd.to_datetime(df_all[col_tanggal], dayfirst=True, errors='coerce')
        df_all['bulan'] = df_all[col_tanggal].dt.strftime('%Y-%m')
        df = df_all[df_all['bulan'] == bulan].copy()
        if unit and 'unit' in df.columns:
            df = df[df['unit'] == unit].copy()
        if df.empty:
            return 0

        import numpy as np
        # parse times
        def parse_time_series(s):
            return pd.to_datetime(s.astype(str), format='%H:%M', errors='coerce')

        if col_jam_masuk in df.columns:
            tms = parse_time_series(df[col_jam_masuk])
            df['masukMin'] = tms.dt.hour * 60 + tms.dt.minute
        else:
            df['masukMin'] = np.nan
        if col_jam_pulang in df.columns:
            tps = parse_time_series(df[col_jam_pulang])
            df['pulangMin'] = tps.dt.hour * 60 + tps.dt.minute
        else:
            df['pulangMin'] = np.nan

        df['zona'] = df[col_zona] if (col_zona and col_zona in df.columns) else 'WIB'
        df['zona'] = df['zona'].fillna('WIB').astype(str).str.upper()

        zone_offset = {'WIB': 0, 'WITA': -60, 'WIT': -120}
        zone_offset_add = {'WIB': 0, 'WITA': 60, 'WIT': 120}
        df['masukNormMin'] = df['masukMin'] + df['zona'].map(lambda z: zone_offset.get(z, 0))
        df['pulangNormMin'] = df['pulangMin'] + df['zona'].map(lambda z: zone_offset.get(z, 0))
        df['masukNormMinAdd'] = df['masukMin'] + df['zona'].map(lambda z: zone_offset_add.get(z, 0))
        df['pulangNormMinAdd'] = df['pulangMin'] + df['zona'].map(lambda z: zone_offset_add.get(z, 0))

        # Prepare output table: create and remove existing bulan rows
        conn.execute('CREATE TABLE IF NOT EXISTS hitung_harian (nip TEXT, nama TEXT, jabatan TEXT, bulan TEXT, tanggal TEXT, zona TEXT, jamMasuk TEXT, jamPulang TEXT, durasi TEXT, jamNormalisasi TEXT, jamMasukAsli TEXT, jamPulangAsli TEXT, durasiMin REAL, metode TEXT, jenis TEXT, statusHariLibur TEXT, statusCuti TEXT, statusDuplikasi TEXT, statusLengkap TEXT, potKeterlambatan REAL, potPulangCepat REAL, potDurasi REAL, potTidakLengkap REAL, totalHarian REAL, flags TEXT)')
        try:
            if unit and 'unit' in df.columns:
                conn.execute('DELETE FROM hitung_harian WHERE bulan = ? AND unit = ?', (bulan, unit))
            else:
                conn.execute('DELETE FROM hitung_harian WHERE bulan = ?', (bulan,))
            conn.commit()
        except Exception:
            pass

        total = len(df)
        if total == 0:
            return 0

        chunk_size = 5000
        processed = 0
        rows_written = 0

        # utility functions
        def parse_time_to_min(s):
            try:
                return int(s.hour) * 60 + int(s.minute)
            except Exception:
                return None

        def fmt_time_min(m):
            if pd.isna(m) or m is None:
                return ''
            try:
                m = int(m)
                h = (m // 60) % 24
                mm = m % 60
                return f"{h:02d}:{mm:02d}"
            except Exception:
                return ''

        def fmt_dur_min(m):
            if pd.isna(m) or m is None:
                return ''
            try:
                m = int(m)
                h = m // 60
                mm = m % 60
                return f"{h}h {mm}m"
            except Exception:
                return ''

        def tier_pct(tiers, minutes):
            if minutes is None or pd.isna(minutes):
                return 0
            for t in tiers:
                if minutes <= t.get('max', 0):
                    return t.get('pct', 0)
            return tiers[-1].get('pct', 0) if tiers else 0

        def durasi_tier_pct(hours, minDurasi):
            if hours >= minDurasi:
                return 0
            if hours >= minDurasi - 0.5:
                return 0.5
            if hours >= minDurasi - 1.0:
                return 1
            if hours >= minDurasi - 1.5:
                return 1.5
            if hours >= minDurasi - 2.0:
                return 2
            return 3

        # process in chunks
        for start in range(0, total, chunk_size):
            end = min(start + chunk_size, total)
            chunk = df.iloc[start:end].copy()

            # check cancellation signal from jobs table
            if job_id:
                jr = conn.execute('SELECT status FROM jobs WHERE id = ?', (job_id,)).fetchone()
                if jr and jr['status'] == 'cancelled':
                    _update_job(job_id, status='cancelled', finished_at=_now_iso(), message='Cancelled by user', progress=processed / total if total else 0.0)
                    return rows_written

            # select useMasuk/usePulang
            if time_mode == 'original':
                chunk['useMasuk'] = chunk['masukMin']
                chunk['usePulang'] = chunk['pulangMin']
            elif time_mode == 'wib':
                chunk['useMasuk'] = chunk['masukNormMin']
                chunk['usePulang'] = chunk['pulangNormMin']
            elif time_mode == 'wib-add':
                chunk['useMasuk'] = chunk['masukNormMinAdd']
                chunk['usePulang'] = chunk['pulangNormMinAdd']
            else:
                chunk['useMasuk'] = chunk['masukMin']
                chunk['usePulang'] = chunk['pulangMin']

            chunk['durasiMin'] = chunk['usePulang'] - chunk['useMasuk']

            # holiday/ weekend
            chunk['isHoliday'] = chunk[col_tanggal].dt.strftime('%Y-%m-%d').isin(holiday_set) | chunk[col_tanggal].dt.weekday.isin([5, 6])
            chunk['holidayLabel'] = chunk[col_tanggal].dt.strftime('%Y-%m-%d').map(lambda d: holiday_name.get(d, 'Akhir Pekan') if d in holiday_name or d in holiday_set else '')

            # jabatan & metode
            def resolve_jabatan_row(r):
                nip = str(r.get(col_nip) or '').strip()
                peg = peg_by_nip.get(nip)
                if peg and peg.get('jabatan'):
                    return str(peg.get('jabatan')).strip()
                j = r.get('jabatan') or r.get('jabatan')
                if j:
                    return str(j).strip()
                return 'Belum Ditentukan'

            chunk['jabatan_resolved'] = chunk.apply(resolve_jabatan_row, axis=1)
            chunk['metode'] = chunk['jabatan_resolved'].map(lambda j: 'durasi' if jab_method.get(str(j).strip().lower()) == 'durasi' else 'reguler')

            # leave periods (per-nip mask)
            chunk['statusCuti'] = ''
            for lp in leave_periods:
                mask = (chunk[col_nip].astype(str).str.strip() == lp['nip']) & (chunk[col_tanggal].dt.strftime('%Y-%m-%d') >= lp['mulai']) & (chunk[col_tanggal].dt.strftime('%Y-%m-%d') <= lp['selesai'])
                chunk.loc[mask, 'statusCuti'] = lp.get('jenis', '')

            # jenisNoPotongan
            chunk['jenis_norm'] = chunk[col_jenis].astype(str).fillna('').str.strip().str.lower()
            chunk['excused'] = chunk['jenis_norm'].isin(jenis_no)
            chunk.loc[chunk['excused'], 'statusCuti'] = chunk.loc[chunk['excused'], col_jenis]

            # completeness
            chunk['statusLengkap'] = chunk.apply(lambda r: 'Tidak Lengkap' if (pd.isna(r['useMasuk']) or pd.isna(r['usePulang'])) else 'Lengkap', axis=1)
            chunk['potTidakLengkap'] = chunk['statusLengkap'].map(lambda s: cfg.get('potonganTidakLengkap', 3) if s == 'Tidak Lengkap' else 0)

            # initialize penalties
            chunk['potKeterlambatan'] = 0.0
            chunk['potPulangCepat'] = 0.0
            chunk['potDurasi'] = 0.0
            chunk['flags'] = ''

            # apply metode specific rules
            for idx, r in chunk.iterrows():
                if r.get('statusCuti'):
                    chunk.at[idx, 'flags'] += 'PERIODE CUTI/SAKIT; '
                    chunk.at[idx, 'totalHarian'] = 0.0
                    continue
                if r.get('excused'):
                    chunk.at[idx, 'flags'] += 'JENIS BEBAS POTONGAN; '
                    chunk.at[idx, 'totalHarian'] = 0.0
                    continue
                if r['metode'] == 'durasi':
                    dur_hours = (r.get('durasiMin') or 0) / 60.0
                    pct = durasi_tier_pct(dur_hours, cfg.get('minDurasiJam', 7.5))
                    chunk.at[idx, 'potDurasi'] = pct
                else:
                    # reguler
                    if not r.get('isHoliday'):
                        dow = r[col_tanggal].weekday()
                        is_jumat = (dow == 4)
                        jd = cfg.get('jamDasar', {}).get('jumat' if is_jumat else 'senKam', {})
                        masuk_std = int(jd.get('masuk', '07:30').split(':')[0]) * 60 + int(jd.get('masuk', '07:30').split(':')[1])
                        pulang_std = int(jd.get('pulang', '16:00').split(':')[0]) * 60 + int(jd.get('pulang', '16:00').split(':')[1])

                        lateMin = max(0, (r.get('useMasuk') or 0) - masuk_std)
                        earlyMin = max(0, pulang_std - (r.get('usePulang') or 0))

                        # FLEXI
                        fx = cfg.get('flexi', {}) or {}
                        if fx.get('enabled'):
                            fStart = int(fx.get('masukStart', '07:31').split(':')[0]) * 60 + int(fx.get('masukStart', '07:31').split(':')[1])
                            fEnd = int(fx.get('masukEnd', '08:00').split(':')[0]) * 60 + int(fx.get('masukEnd', '08:00').split(':')[1])
                            komp = int(fx.get('kompensasiJumat' if is_jumat else 'kompensasiSenKam', '16:30').split(':')[0]) * 60 + int(fx.get('kompensasiJumat' if is_jumat else 'kompensasiSenKam', '16:30').split(':')[1])
                            if (r.get('useMasuk') or 0) >= fStart and (r.get('useMasuk') or 0) <= fEnd and (r.get('usePulang') or 0) > komp:
                                lateMin = 0
                                earlyMin = 0
                                chunk.at[idx, 'flags'] += 'FLEXI TIME (kompensasi); '

                        if lateMin > 0:
                            chunk.at[idx, 'potKeterlambatan'] = tier_pct(cfg.get('keterlambatanTiers', []), lateMin)
                        if earlyMin > 0:
                            chunk.at[idx, 'potPulangCepat'] = tier_pct(cfg.get('pulangCepatTiers', []), earlyMin)
                        chunk.at[idx, '_lateMin'] = lateMin
                        chunk.at[idx, '_earlyMin'] = earlyMin
                    else:
                        chunk.at[idx, 'flags'] += 'HARI LIBUR - TANPA POTONGAN REGULER; '

                # compute total
                total_pct = (chunk.at[idx, 'potKeterlambatan'] or 0) + (chunk.at[idx, 'potPulangCepat'] or 0) + (chunk.at[idx, 'potDurasi'] or 0) + (chunk.at[idx, 'potTidakLengkap'] or 0)
                chunk.at[idx, 'totalHarian'] = round(float(total_pct), 2)

            # format output columns
            chunk_out = pd.DataFrame()
            chunk_out['nip'] = chunk[col_nip] if col_nip in chunk.columns else ''
            chunk_out['nama'] = chunk[col_nama] if col_nama in chunk.columns else ''
            chunk_out['jabatan'] = chunk['jabatan_resolved']
            chunk_out['bulan'] = chunk['bulan']
            chunk_out['tanggal'] = chunk[col_tanggal].dt.strftime('%Y-%m-%d')
            chunk_out['zona'] = chunk['zona']
            chunk_out['jamMasuk'] = chunk['useMasuk'].map(fmt_time_min)
            chunk_out['jamPulang'] = chunk['usePulang'].map(fmt_time_min)
            chunk_out['durasi'] = chunk['durasiMin'].map(fmt_dur_min)
            def jam_norm_row(r):
                if time_mode == 'original':
                    return 'Original'
                if r.get('zona', 'WIB') == 'WIB':
                    return ''
                if time_mode == 'wib':
                    return f"{fmt_time_min(r.get('masukNormMin'))} - {fmt_time_min(r.get('pulangNormMin'))}"
                if time_mode == 'wib-add':
                    return f"{fmt_time_min(r.get('masukNormMinAdd'))} - {fmt_time_min(r.get('pulangNormMinAdd'))}"
                return ''
            chunk_out['jamNormalisasi'] = chunk.apply(jam_norm_row, axis=1)
            chunk_out['jamMasukAsli'] = chunk['masukMin'].map(fmt_time_min)
            chunk_out['jamPulangAsli'] = chunk['pulangMin'].map(fmt_time_min)
            chunk_out['durasiMin'] = chunk['durasiMin']
            chunk_out['metode'] = chunk['metode']
            chunk_out['jenis'] = chunk[col_jenis] if col_jenis in chunk.columns else ''
            chunk_out['statusHariLibur'] = chunk['isHoliday'].map(lambda v: 'Ya' if v else 'Tidak')
            chunk_out['statusCuti'] = chunk['statusCuti']
            chunk_out['statusDuplikasi'] = False
            chunk_out['statusLengkap'] = chunk['statusLengkap']
            chunk_out['potKeterlambatan'] = chunk['potKeterlambatan']
            chunk_out['potPulangCepat'] = chunk['potPulangCepat']
            chunk_out['potDurasi'] = chunk['potDurasi']
            chunk_out['potTidakLengkap'] = chunk['potTidakLengkap']
            chunk_out['totalHarian'] = chunk['totalHarian']
            chunk_out['flags'] = chunk['flags']

            # append to DB
            try:
                chunk_out.to_sql('hitung_harian', conn, if_exists='append', index=False)
            except Exception:
                pass

            written = len(chunk_out)
            processed += (end - start)
            rows_written += written
            # update progress
            if job_id:
                _update_job(job_id, progress=min(1.0, processed / total), message=f'Processed {processed} / {total}')

        return int(rows_written)
    finally:
        conn.close()


def compute_harian_duckdb(job_id: str, bulan: str, time_mode: str, unit: Optional[str], chunk_size: int = 50000) -> int:
    """
    Compute hitung_harian using DuckDB SQL in chunks and write results to DuckDB.
    Returns number of rows written.
    """
    import duckdb as _d
    dconn = _d.connect(DUCKDB_PATH)
    sqlite_conn = get_connection()
    try:
        # load config from DuckDB if available, else fallback to workflow_config in sqlite
        cfg = {}
        try:
            cfg_df = dconn.execute('SELECT * FROM "workflow_config"').fetchdf()
            if not cfg_df.empty:
                # workflow_config likely has JSON columns; take first row and parse fields that are JSON strings
                row = cfg_df.iloc[0].to_dict()
                for k, v in row.items():
                    if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                        try:
                            cfg[k] = json.loads(v)
                        except Exception:
                            cfg[k] = v
                    else:
                        cfg[k] = v
        except Exception:
            # fallback to sqlite
            try:
                cur = sqlite_conn.execute('SELECT * FROM workflow_config LIMIT 1')
                r = cur.fetchone()
                if r:
                    rowd = dict(r)
                    for k, v in rowd.items():
                        if v is None:
                            continue
                        if isinstance(v, str) and (v.startswith('{') or v.startswith('[')):
                            try:
                                cfg[k] = json.loads(v)
                            except Exception:
                                cfg[k] = v
                        else:
                            cfg[k] = v
            except Exception:
                cfg = {}

        # apply defaults
        default_cfg = {
            'holidays': [],
            'jabatanMaster': [],
            'masterPegawai': [],
            'jenisNoPotongan': [],
            'leavePeriods': [],
            'jamDasar': {'senKam': {'masuk': '07:30', 'pulang': '16:00'}, 'jumat': {'masuk': '07:30', 'pulang': '16:30'}},
            'flexi': {'enabled': True, 'masukStart': '07:31', 'masukEnd': '08:00', 'kompensasiSenKam': '16:30', 'kompensasiJumat': '17:00'},
            'keterlambatanTiers': [{'max': 30, 'pct': 0.5}, {'max': 60, 'pct': 1}, {'max': 90, 'pct': 1.5}, {'max': 120, 'pct': 2}, {'max': 9999, 'pct': 3}],
            'pulangCepatTiers': [{'max': 30, 'pct': 0.5}, {'max': 60, 'pct': 1}, {'max': 90, 'pct': 1.5}, {'max': 120, 'pct': 2}, {'max': 9999, 'pct': 3}],
            'minDurasiJam': 7.5,
            'potonganTidakLengkap': 3,
        }
        for k, v in default_cfg.items():
            if k not in cfg:
                cfg[k] = v

        # helpers for SQL generation
        def build_tier_case(col_name, tiers):
            # returns SQL fragment: CASE WHEN col <= max1 THEN pct1 WHEN col <= max2 THEN pct2 ELSE pctN END
            if not tiers:
                return '0'
            parts = []
            for t in tiers:
                parts.append((t.get('max', 0), t.get('pct', 0)))
            case_sql = 'CASE'
            for mx, pct in parts:
                case_sql += f" WHEN {col_name} <= {mx} THEN {pct}"
            case_sql += f" ELSE {parts[-1][1]} END"
            return case_sql

        # prepare leave periods as temporary table if present
        leave_periods = cfg.get('leavePeriods') or []
        if leave_periods:
            vals = []
            for lp in leave_periods:
                nip = str(lp.get('nip', '')).replace("'", "''")
                mulai = str(lp.get('mulai', '')).replace("'", "''")
                selesai = str(lp.get('selesai', '')).replace("'", "''")
                jenis = str(lp.get('jenis', '')).replace("'", "''")
                vals.append(f"('{nip}','{mulai}','{selesai}','{jenis}')")
            vals_sql = ','.join(vals)
            dconn.execute(f"CREATE TEMPORARY TABLE _leave AS SELECT * FROM (VALUES {vals_sql}) AS v(nip, mulai, selesai, jenis)")
        else:
            dconn.execute("CREATE TEMPORARY TABLE _leave AS SELECT * FROM (VALUES ('','','','')) AS v(nip, mulai, selesai, jenis) WHERE FALSE")

        # build tiers SQL
        late_case = build_tier_case('lateMin', cfg.get('keterlambatanTiers', []))
        early_case = build_tier_case('earlyMin', cfg.get('pulangCepatTiers', []))

        # build durasi CASE based on minDurasi
        minDur = float(cfg.get('minDurasiJam', 7.5))
        # emulate durasi_tier_pct JS function
        durasi_case = f"CASE WHEN hours >= {minDur} THEN 0 WHEN hours >= {minDur - 0.5} THEN 0.5 WHEN hours >= {minDur - 1.0} THEN 1 WHEN hours >= {minDur - 1.5} THEN 1.5 WHEN hours >= {minDur - 2.0} THEN 2 ELSE 3 END"

        # parse jamDasar and flexi constants
        jd_senkam_masuk = cfg.get('jamDasar', {}).get('senKam', {}).get('masuk', '07:30')
        jd_senkam_pulang = cfg.get('jamDasar', {}).get('senKam', {}).get('pulang', '16:00')
        jd_jumat_masuk = cfg.get('jamDasar', {}).get('jumat', {}).get('masuk', '07:30')
        jd_jumat_pulang = cfg.get('jamDasar', {}).get('jumat', {}).get('pulang', '16:30')

        def time_to_min(t):
            h, m = str(t).split(':')
            return int(h) * 60 + int(m)
        sen_masuk_min = time_to_min(jd_senkam_masuk)
        sen_pulang_min = time_to_min(jd_senkam_pulang)
        jum_masuk_min = time_to_min(jd_jumat_masuk)
        jum_pulang_min = time_to_min(jd_jumat_pulang)

        fx = cfg.get('flexi', {}) or {}
        fx_enabled = bool(fx.get('enabled'))
        fx_masuk_start = time_to_min(fx.get('masukStart', '07:31'))
        fx_masuk_end = time_to_min(fx.get('masukEnd', '08:00'))
        fx_kompensasi_sen = time_to_min(fx.get('kompensasiSenKam', '16:30'))
        fx_kompensasi_jum = time_to_min(fx.get('kompensasiJumat', '17:00'))

        # ensure hitung_harian table exists empty for appending
        dconn.execute('''CREATE TABLE IF NOT EXISTS hitung_harian (
            nip TEXT, nama TEXT, jabatan TEXT, bulan TEXT, tanggal DATE, zona TEXT,
            jamMasuk TEXT, jamPulang TEXT, durasi TEXT, jamNormalisasi TEXT,
            jamMasukAsli TEXT, jamPulangAsli TEXT, durasiMin DOUBLE, metode TEXT,
            jenis TEXT, statusHariLibur TEXT, statusCuti TEXT,
            statusDuplikasi BOOLEAN, statusLengkap TEXT,
            potKeterlambatan DOUBLE, potPulangCepat DOUBLE, potDurasi DOUBLE,
            potTidakLengkap DOUBLE, totalHarian DOUBLE, flags TEXT
        )''')

        # compute total rows to process
        count_q = f"SELECT COUNT(*) AS c FROM raw_import WHERE substr(tanggal,1,7) = '{bulan}'"
        if unit and unit != '' and 'unit' in dconn.execute("SELECT * FROM raw_import LIMIT 1").columns:
            count_q = f"SELECT COUNT(*) AS c FROM raw_import WHERE substr(tanggal,1,7) = '{bulan}' AND unit = '{unit}'"
        total = dconn.execute(count_q).fetchone()[0]
        if total == 0:
            return 0

        rows_written = 0
        processed = 0
        offset = 0
        while offset < total:
            limit = min(chunk_size, total - offset)
            # build SQL selecting transformed fields
            # choose useMasuk/usePulang depending on time_mode
            if time_mode == 'original':
                use_masuk_expr = 'masukMin'
                use_pulang_expr = 'pulangMin'
            elif time_mode == 'wib':
                use_masuk_expr = 'masukNormMin'
                use_pulang_expr = 'pulangNormMin'
            elif time_mode == 'wib-add':
                use_masuk_expr = 'masukNormMinAdd'
                use_pulang_expr = 'pulangNormMinAdd'
            else:
                use_masuk_expr = 'masukMin'
                use_pulang_expr = 'pulangMin'

            # Query to compute chunk
            sql = f"""INSERT INTO hitung_harian (
                      nip, nama, jabatan, bulan, tanggal, zona, jamMasuk, jamPulang,
                      durasi, jamNormalisasi, jamMasukAsli, jamPulangAsli, durasiMin,
                      metode, jenis, statusHariLibur, statusCuti, statusDuplikasi,
                      statusLengkap, potTidakLengkap, potKeterlambatan,
                      potPulangCepat, potDurasi, totalHarian, flags
                  ) """ \
                  f"SELECT nip, nama, COALESCE(jabatan, '') AS jabatan, substr(tanggal,1,7) AS bulan, tanggal::DATE AS tanggal, zona, " \
                  f"printf('%02d:%02d', CAST(({use_masuk_expr} / 60) AS INTEGER), CAST(({use_masuk_expr} % 60) AS INTEGER)) AS jamMasuk, " \
                  f"printf('%02d:%02d', CAST(({use_pulang_expr} / 60) AS INTEGER), CAST(({use_pulang_expr} % 60) AS INTEGER)) AS jamPulang, " \
                  f"printf('%dh %dm', CAST((({use_pulang_expr} - {use_masuk_expr}) / 60) AS INTEGER), CAST((({use_pulang_expr} - {use_masuk_expr}) % 60) AS INTEGER)) AS durasi, " \
                  f"CASE WHEN '{time_mode}' = 'original' THEN 'Original' WHEN zona = 'WIB' THEN '' WHEN '{time_mode}' = 'wib' THEN printf('%02d:%02d', CAST((masukNormMin/60) AS INTEGER), CAST((masukNormMin%60) AS INTEGER)) || ' - ' || printf('%02d:%02d', CAST((pulangNormMin/60) AS INTEGER), CAST((pulangNormMin%60) AS INTEGER)) WHEN '{time_mode}' = 'wib-add' THEN printf('%02d:%02d', CAST((masukNormMinAdd/60) AS INTEGER), CAST((masukNormMinAdd%60) AS INTEGER)) || ' - ' || printf('%02d:%02d', CAST((pulangNormMinAdd/60) AS INTEGER), CAST((pulangNormMinAdd%60) AS INTEGER)) ELSE '' END AS jamNormalisasi, " \
                  f"printf('%02d:%02d', CAST((masukMin/60) AS INTEGER), CAST((masukMin%60) AS INTEGER)) AS jamMasukAsli, " \
                  f"printf('%02d:%02d', CAST((pulangMin/60) AS INTEGER), CAST((pulangMin%60) AS INTEGER)) AS jamPulangAsli, " \
                  f"({use_pulang_expr} - {use_masuk_expr})::DOUBLE AS durasiMin, " \
                  f"CASE WHEN (COALESCE(jabatan, '') <> '' AND lower(jabatan) IN ({', '.join([f"'{k.strip().lower()}'" for k in (cfg.get('jabatanMaster') or []) if isinstance(k, dict) and k.get('nama')])}) ) THEN 'durasi' ELSE 'reguler' END AS metode, " \
                  f"COALESCE(jenis, '') AS jenis, " \
                  f"CASE WHEN substr(tanggal,1,10) IN ({', '.join([f"'{h.get('d')}'" for h in (cfg.get('holidays') or []) if isinstance(h, dict) and h.get('d')])}) THEN 'Ya' ELSE 'Tidak' END AS statusHariLibur, " \
                  f"COALESCE(lp.jenis, '') AS statusCuti, " \
                  f"FALSE AS statusDuplikasi, " \
                  f"CASE WHEN {use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL THEN 'Tidak Lengkap' ELSE 'Lengkap' END AS statusLengkap, " \
                  f"CASE WHEN {use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL THEN {cfg.get('potonganTidakLengkap', 3)} ELSE 0 END AS potTidakLengkap, " \
                  f"(CASE WHEN ({use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL) THEN 0 ELSE ({late_case}) END) AS potKeterlambatan, " \
                  f"(CASE WHEN ({use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL) THEN 0 ELSE ({early_case}) END) AS potPulangCepat, " \
                  f"(CASE WHEN (COALESCE(jabatan, '') <> '' AND lower(jabatan) IN ({', '.join([f"'{k.strip().lower()}'" for k in (cfg.get('jabatanMaster') or []) if isinstance(k, dict) and k.get('nama')])}) ) THEN ({durasi_case}) ELSE 0 END) AS potDurasi, " \
                  f"((CASE WHEN {use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL THEN {cfg.get('potonganTidakLengkap', 3)} ELSE 0 END) + (CASE WHEN ({use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL) THEN 0 ELSE ({late_case}) END) + (CASE WHEN ({use_masuk_expr} IS NULL OR {use_pulang_expr} IS NULL) THEN 0 ELSE ({early_case}) END) + (CASE WHEN (COALESCE(jabatan, '') <> '' AND lower(jabatan) IN ({', '.join([f"'{k.strip().lower()}'" for k in (cfg.get('jabatanMaster') or []) if isinstance(k, dict) and k.get('nama')])}) ) THEN ({durasi_case}) ELSE 0 END))::DOUBLE AS totalHarian, " \
                  f"'' AS flags " \
                  f"FROM raw_import LEFT JOIN _leave lp ON (CAST(raw_import.nip AS TEXT) = CAST(lp.nip AS TEXT) AND raw_import.tanggal::DATE BETWEEN lp.mulai::DATE AND lp.selesai::DATE) " \
                  f"WHERE substr(tanggal,1,7) = '{bulan}' "
            if unit and unit != '' and 'unit' in dconn.execute('SELECT * FROM raw_import LIMIT 1').columns:
                sql += f" AND unit = '{unit}' "
            sql += f" LIMIT {limit} OFFSET {offset}"

            dconn.execute(sql)
            offset += limit
            processed += limit
            rows_written += dconn.execute('SELECT COUNT(*) FROM hitung_harian').fetchone()[0] - rows_written
            # update progress in sqlite
            progress = min(1.0, processed / total)
            _update_job(job_id, progress=progress, message=f'Processed {processed} / {total}', status='running')
            # check cancel
            jr = sqlite_conn.execute('SELECT status FROM jobs WHERE id = ?', (job_id,)).fetchone()
            if jr and jr['status'] == 'cancelled':
                _update_job(job_id, status='cancelled', finished_at=_now_iso(), message='Cancelled by user', progress=processed / total if total else 0.0)
                return rows_written
        # finished
        return rows_written
    finally:
        try:
            dconn.close()
        except Exception:
            pass
        sqlite_conn.close()


@database_job
def run_compute_harian_job(job_id: str, bulan: str, time_mode: str, unit: Optional[str]):
    # Called in background process
    try:
        _update_job(job_id, status='running', started_at=_now_iso(), progress=0.0, message='Started')
        # Run compute using DuckDB SQL
        rows = compute_harian_duckdb(job_id, bulan, timeMode, unit)
        _update_job(job_id, status='finished', finished_at=_now_iso(), progress=1.0, message='Completed', result_table='hitung_harian', row_count=rows)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        _update_job(job_id, status='failed', finished_at=_now_iso(), progress=0.0, message=str(exc) + '\n' + tb)


@app.post('/api/compute/harians')
def api_compute_harians(bulan: str = Query(..., description='Bulan contoh: 2026-08'), timeMode: str = Query('original'), unit: Optional[str] = Query(None)):
    """Start an asynchronous compute job for hitung_harian."""
    job_id = str(uuid.uuid4())
    payload = {'bulan': bulan, 'timeMode': timeMode, 'unit': unit}
    conn = get_connection()
    try:
        ensure_jobs_table(conn)
        conn.execute('INSERT INTO jobs (id, type, status, payload, progress, message) VALUES (?, ?, ?, ?, ?, ?)', (job_id, 'hitung_harian', 'queued', json.dumps(payload, ensure_ascii=False), 0.0, 'Queued'))
        conn.commit()
    finally:
        conn.close()
    # Keep DuckDB jobs in the server process and preserve queue cancellation.
    future = _executor.submit(run_compute_harian_job, job_id, bulan, timeMode, unit)
    _job_futures[job_id] = future
    return {'job_id': job_id, 'status': 'queued'}


@app.post('/api/jobs/export')
def create_export_job(payload: dict) -> dict:
    """Create a background export job that generates an XLSX or ZIP(CSV) file in backend/exports.
    Payload should include: bulan (YYYY-MM), optional unit, optional jabatan, optional sheet_names
    (list of sheet display names), optional format ('xlsx'|'csv'). Returns the created job id.
    """
    bulan = str(payload.get('bulan') or '')
    if not bulan:
        raise HTTPException(status_code=400, detail='Missing bulan')
    unit = payload.get('unit')
    jabatan = payload.get('jabatan')
    sheet_names = payload.get('sheet_names') or []
    fmt = str(payload.get('format') or 'xlsx').lower()
    if fmt not in ('xlsx', 'csv'):
        fmt = 'xlsx'
    new_job_id = uuid.uuid4().hex
    conn = get_connection()
    try:
        ensure_jobs_table(conn)
        conn.execute('INSERT INTO jobs (id, type, status, payload, progress, message, started_at, finished_at, result_table) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (new_job_id, 'export', 'queued', json.dumps({'bulan': bulan, 'unit': unit, 'jabatan': jabatan, 'sheet_names': sheet_names, 'format': fmt}, ensure_ascii=False), 0.0, 'Queued', None, None, None))
        conn.commit()
    finally:
        conn.close()
    future = _executor.submit(run_export_job, new_job_id, bulan, unit, sheet_names, fmt, jabatan, payload.get('expected_final'))
    _job_futures[new_job_id] = future
    return {'status': 'ok', 'job_id': new_job_id}


@app.get('/api/jobs/{job_id}')
def api_get_job(job_id: str):
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Job not found')
        return dict(row)
    finally:
        conn.close()


@app.get('/api/jobs')
def api_list_jobs(limit: int = Query(50, ge=1, le=1000)):
    conn = get_connection()
    try:
        rows = conn.execute('SELECT * FROM jobs ORDER BY started_at DESC NULLS LAST LIMIT ?', (limit,)).fetchall()
        return {'status': 'ok', 'jobs': [dict(r) for r in rows]}
    finally:
        conn.close()


@app.get('/api/jobs/{job_id}/download')
def api_download_job_result(job_id: str):
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Job not found')
        if row['status'] != 'finished' or not row['result_table']:
            raise HTTPException(status_code=404, detail='Result not available')
        path = row['result_table']
        # If stored as absolute path, use it; otherwise assume relative to EXPORT_DIR
        if not os.path.isabs(path):
            path = os.path.join(EXPORT_DIR, path)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail='Result file missing')
        if path.endswith('.xlsx'):
            media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif path.endswith('.zip'):
            media = 'application/zip'
        else:
            media = 'application/octet-stream'
        return FileResponse(path, media_type=media, filename=os.path.basename(path))
    finally:
        conn.close()


@app.get('/api/compute/harians/result')
def api_compute_harians_result(bulan: str = Query(...), unit: Optional[str] = Query(None), limit: int = Query(50)):
    df = read_workflow_table_global('hitung_harian', bulan, unit)
    if df.empty:
        return {'rows': [], 'count': 0}
    df = df.head(limit)
    return {'rows': df.to_dict(orient='records'), 'count': len(df)}


@app.post('/api/jobs/{job_id}/cancel')
def api_cancel_job(job_id: str):
    # existing cancel behavior remains

    """Cancel a queued/running job. Attempts to cancel the running future and marks job as cancelled in DB."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Job tidak ditemukan')
        status = row['status']
        if status in ('finished', 'failed', 'cancelled'):
            return {'job_id': job_id, 'status': status}
        # attempt to cancel future
        fut = _job_futures.get(job_id)
        if fut:
            fut.cancel()
        _update_job(job_id, status='cancelled', finished_at=_now_iso(), message='Cancelled by user', progress=row['progress'] or 0.0)
        return {'job_id': job_id, 'status': 'cancelled'}
    finally:
        conn.close()


@app.post('/api/jobs/{job_id}/retry')
def api_retry_job(job_id: str):
    """Retry a failed or cancelled job by enqueuing a new job with same payload."""
    conn = get_connection()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Job tidak ditemukan')
        payload = row['payload']
        try:
            payload_obj = json.loads(payload) if isinstance(payload, str) else payload
        except Exception:
            payload_obj = {}
        new_job_id = str(uuid.uuid4())
        ensure_jobs_table(conn)
        conn.execute('INSERT INTO jobs (id, type, status, payload, progress, message) VALUES (?, ?, ?, ?, ?, ?)', (new_job_id, row['type'] or 'hitung_harian', 'queued', json.dumps(payload_obj, ensure_ascii=False), 0.0, 'Retried'))
        conn.commit()
        # submit
        _job_futures[new_job_id] = _executor.submit(run_compute_harian_job, new_job_id, payload_obj.get('bulan'), payload_obj.get('timeMode', 'original'), payload_obj.get('unit'))
        return {'job_id': new_job_id, 'status': 'queued'}
    finally:
        conn.close()


@app.get("/")
def serve_index() -> FileResponse:
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=404, detail="index.html tidak ditemukan di folder aplikasi")
    return FileResponse(INDEX_FILE, media_type="text/html; charset=utf-8")


if ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
