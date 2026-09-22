import os
import asyncio
from pathlib import Path
import tempfile
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from backend import pengembalian
from backend.pengembalian_archive import (
    ArchiveService,
    SOURCE_AWAL,
    SOURCE_PENYESUAIAN,
)
from backend.pengembalian_progress import ProgressService
from backend.pengembalian_monthly import MonthlyMasterService
from backend.pengembalian_dasar_2025 import DasarPengembalian2025Service
from fastapi.responses import StreamingResponse
import io
import hashlib

from backend.pengembalian_excel_rekap import read_rekap_sheets

router = APIRouter()


def _require_pengembalian_api_key(request: Request):
    expected_key = os.environ.get('EVKIN_API_KEY') or os.environ.get('EVKIN_ANALYTICS_API_KEY')
    if not expected_key:
        return True
    key = request.headers.get('x-evkin-api-key') or request.headers.get('x-api-key') or request.headers.get('authorization')
    if key and key.lower().startswith('bearer '):
        key = key.split(' ', 1)[1]
    if key != expected_key:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return True


def _pagination(limit, offset=0, max_limit=1000):
    try:
        safe_limit = int(limit)
        safe_offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="limit dan offset harus berupa angka") from exc
    if safe_limit < 1 or safe_limit > max_limit:
        raise HTTPException(status_code=400, detail=f"limit harus antara 1 dan {max_limit}")
    if safe_offset < 0:
        raise HTTPException(status_code=400, detail="offset tidak boleh negatif")
    return safe_limit, safe_offset


class ImportRow(BaseModel):
    nip: str
    tahun: int
    bulan: int
    komponen: Optional[str] = 'TUKIN'
    nominal_awal: float
    source_table: Optional[str] = None
    source_record_id: Optional[str] = None
    notes: Optional[str] = None


class ImportPayload(BaseModel):
    rows: List[ImportRow]
    nama_file: Optional[str] = None
    jenis_data: Optional[str] = 'pengembalian_tukin'
    periode: Optional[str] = None
    created_by: Optional[str] = 'system'


class CaseResponse(BaseModel):
    case_id: str


@router.post('/cases/import')
def import_cases(payload: ImportPayload, request: Request):
    # minimal API that accepts a JSON batch and records import_batch + cases + initial history
    try:
        created_by = payload.created_by or 'system'
        batch_meta = {
            'nama_file': payload.nama_file,
            'jenis_data': payload.jenis_data,
            'periode': payload.periode,
            'tahun': None,
            'jumlah_baris': len(payload.rows),
        }
        batch_id = pengembalian.record_import_batch_and_audit(batch_meta, created_by=created_by)
        results = []
        for r in payload.rows:
            # create case (include komponen so case_id reflects business identity)
            case_id = pengembalian.create_case(nip=r.nip, tahun=r.tahun, bulan=r.bulan, created_by=created_by, komponen=(r.komponen if hasattr(r, 'komponen') else None))
            # initial history = liability positive nominal_awal
            hid = pengembalian.insert_history_event(case_id=case_id, event_type='initial_import', amount=float(r.nominal_awal), created_by=created_by, source_table=r.source_table, source_record_id=r.source_record_id, import_batch_id=batch_id, notes=r.notes)
            results.append({'case_id': case_id, 'history_id': hid})
        return {'status': 'ok', 'batch_id': batch_id, 'results': results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# New endpoint specifically for HISTORY_AWAL transactional import
class HistoryAwalRow(BaseModel):
    nip: Optional[str] = None
    nama: Optional[str] = None
    periode: Optional[str] = None
    tahun: Optional[int] = None
    bulan: Optional[int] = None
    komponen: Optional[str] = None
    nominal_awal: Optional[float] = None
    nominal_tukin: Optional[float] = None
    nominal_uang_makan: Optional[float] = None
    sumber_data: Optional[str] = None
    tahun_sp2d: Optional[int] = None
    nomor_sp2d: Optional[str] = None
    provinsi: Optional[str] = None
    unit_kerja: Optional[str] = None
    jenis_pegawai: Optional[str] = None
    status_awal: Optional[str] = None
    source_file: Optional[str] = None
    source_sheet: Optional[str] = None
    source_row: Optional[int] = None


class HistoryAwalPayload(BaseModel):
    rows: List[HistoryAwalRow]
    filename: Optional[str] = None
    file_hash: Optional[str] = None
    created_by: Optional[str] = 'system'


@router.post('/import/history_awal')
def import_history_awal(payload: HistoryAwalPayload):
    if not payload.file_hash:
        raise HTTPException(status_code=400, detail='file_hash is required')
    rows = [r.dict() for r in payload.rows]
    res = pengembalian.import_history_awal(rows, file_hash=payload.file_hash, filename=payload.filename or 'unknown', import_type='HISTORY_AWAL', created_by=payload.created_by or 'system')
    if res.get('status') == 'error':
        raise HTTPException(status_code=500, detail=res.get('message'))
    if res.get('status') == 'duplicate':
        return {'status': 'duplicate', 'batch_id': res.get('batch_id'), 'message': res.get('message')}
    return {'status': 'ok', 'batch_id': res.get('batch_id'), 'counts': {'total': res.get('total_rows'), 'success': res.get('success_rows'), 'failed': res.get('failed_rows')}}


@router.get('/cases/{case_id}/history')
def case_history(case_id: str):
    h = pengembalian.get_history(case_id)
    return {'case_id': case_id, 'history': h}


@router.get('/cases/{case_id}/position')
def case_position(case_id: str):
    pos = pengembalian.get_current_position(case_id)
    return {'case_id': case_id, 'position': pos}


@router.get('/cases')
def list_cases(request: Request, limit: int = 200, offset: int = 0):
    """Return a paginated list of cases (lightweight)."""
    _require_pengembalian_api_key(request)
    safe_limit, safe_offset = _pagination(limit, offset)
    try:
        # lightweight projection
        q = 'SELECT case_id, nip, tahun, bulan, status, created_at FROM pengembalian_tukin_case ORDER BY created_at DESC LIMIT ? OFFSET ?'
        rows = pengembalian._get_conn().execute(q, [safe_limit, safe_offset]).fetchall()
        res = []
        for r in rows:
            res.append({
                'case_id': r[0], 'nip': r[1], 'tahun': r[2], 'bulan': r[3], 'status': r[4], 'created_at': r[5]
            })
        return {'status': 'ok', 'rows': res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# RETURN-2: Dasar Perhitungan endpoints
class DasarRow(BaseModel):
    case_id: Optional[str] = None
    nip: Optional[str] = None
    periode: Optional[str] = None
    komponen: Optional[str] = None
    nilai_awal: Optional[float] = None
    nilai_dasar: Optional[float] = None
    nilai_penyesuaian: Optional[float] = None
    tukin_seharusnya: Optional[float] = None
    nominal_pengembalian: Optional[float] = None
    calculation_version: Optional[str] = None
    rule_version: Optional[str] = None
    calculated_at: Optional[str] = None


class DasarPayload(BaseModel):
    rows: List[DasarRow]
    batch_name: Optional[str] = None
    calculation_version: Optional[str] = None
    rule_version: Optional[str] = None
    created_by: Optional[str] = 'system'


@router.post('/dasar')
def create_dasar(payload: DasarPayload):
    try:
        rows = [r.dict() for r in payload.rows]
        batch_meta = {'batch_name': payload.batch_name, 'calculation_version': payload.calculation_version, 'rule_version': payload.rule_version}
        res = pengembalian.insert_dasar_perhitungan_batch(rows, batch_meta=batch_meta, created_by=payload.created_by or 'system')
        if res.get('status') != 'ok':
            raise Exception(res.get('message') or 'Failed to insert dasar perhitungan')
        return {'status': 'ok', 'batch_id': res.get('batch_id'), 'inserted': res.get('inserted')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/dasar/{case_id}')
def get_dasar(case_id: str):
    try:
        rows = pengembalian.get_dasar_by_case(case_id)
        return {'status': 'ok', 'case_id': case_id, 'rows': rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# RETURN-2: Penyesuaian endpoints
class PenyesuaianRow(BaseModel):
    case_id: Optional[str] = None
    nip: Optional[str] = None
    periode: Optional[str] = None
    komponen: Optional[str] = None
    nominal_sebelum: Optional[float] = None
    nominal_setelah: Optional[float] = None
    selisih: Optional[float] = None
    jenis_penyesuaian: Optional[str] = None
    alasan_penyesuaian: Optional[str] = None
    reference_id: Optional[str] = None


class PenyesuaianPayload(BaseModel):
    rows: List[PenyesuaianRow]
    created_by: Optional[str] = 'system'


@router.post('/penyesuaian')
def create_penyesuaian(payload: PenyesuaianPayload):
    try:
        rows = [r.dict() for r in payload.rows]
        res = pengembalian.insert_penyesuaian(rows, created_by=payload.created_by or 'system')
        if res.get('status') != 'ok':
            raise Exception(res.get('message') or 'Failed to insert penyesuaian')
        return {'status': 'ok', 'inserted': res.get('inserted')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/penyesuaian/{case_id}')
def list_penyesuaian(case_id: str):
    try:
        rows = pengembalian.get_penyesuaian_by_case(case_id)
        return {'status': 'ok', 'case_id': case_id, 'rows': rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# RETURN-3: Send BPK, RETURN-4: Send Bank, RETURN-5: Bank Results
class SendBatchItem(BaseModel):
    case_id: Optional[str] = None
    nip: Optional[str] = None
    periode: Optional[str] = None
    komponen: Optional[str] = None
    nominal: Optional[float] = None
    source_file: Optional[str] = None
    source_row: Optional[int] = None
    notes: Optional[str] = None
    archive_row_id: Optional[str] = None
    comparison_key: Optional[str] = None
    source_dataset: Optional[str] = None
    source_version: Optional[str] = None
    archive_version: Optional[str] = None
    bpk_reference: Optional[str] = None


class SendBatchPayload(BaseModel):
    items: Optional[List[SendBatchItem]] = None
    batch_name: Optional[str] = None
    created_by: Optional[str] = 'system'


@router.post('/send_bpk')
def api_send_bpk(request: Request, payload: SendBatchPayload):
    """Create a BPK batch record and insert details. If items omitted, caller should provide items or backend can select candidates later (not auto-selected here)."""
    _require_pengembalian_api_key(request)
    try:
        items = [i.dict() for i in payload.items] if payload.items else []
        batch_meta = {'batch_name': payload.batch_name}
        res = pengembalian.send_bpk_batch(items=items, batch_meta=batch_meta, created_by=payload.created_by or 'system')
        if res.get('status') != 'ok':
            raise Exception(res.get('message') or 'Failed to create BPK batch')
        archive_result = ArchiveService().record_bpk_history(
            res.get('batch_id'), items, payload.created_by or 'system'
        )
        return {'status': 'ok', 'batch_id': res.get('batch_id'),
                'inserted': res.get('inserted'), 'archive_bpk': archive_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/send_bank')
def api_send_bank(request: Request, payload: SendBatchPayload):
    _require_pengembalian_api_key(request)
    try:
        items = [i.dict() for i in payload.items] if payload.items else []
        batch_meta = {'batch_name': payload.batch_name}
        res = pengembalian.send_bank_batch(items=items, batch_meta=batch_meta, created_by=payload.created_by or 'system')
        if res.get('status') != 'ok':
            raise Exception(res.get('message') or 'Failed to create Bank batch')
        return {'status': 'ok', 'batch_id': res.get('batch_id'), 'inserted': res.get('inserted')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BankResultRow(BaseModel):
    bank_detail_id: Optional[str] = None
    case_id: Optional[str] = None
    nip: Optional[str] = None
    nominal: Optional[float] = None
    status: Optional[str] = None
    reason: Optional[str] = None


class BankResultPayload(BaseModel):
    results: List[BankResultRow]
    created_by: Optional[str] = 'system'


@router.post('/result_bank/{bank_batch_id}')
def api_record_bank_results(request: Request, bank_batch_id: str, payload: BankResultPayload):
    _require_pengembalian_api_key(request)
    try:
        rows = [r.dict() for r in payload.results]
        res = pengembalian.record_bank_results(bank_batch_id=bank_batch_id, results=rows, created_by=payload.created_by or 'system')
        if res.get('status') != 'ok':
            raise Exception(res.get('message') or 'Failed to record bank results')
        return {'status': 'ok', 'inserted': res.get('inserted'), 'failed': res.get('failed')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/result_bank/{bank_batch_id}')
def api_get_bank_results(request: Request, bank_batch_id: str):
    _require_pengembalian_api_key(request)
    try:
        rows = pengembalian.get_bank_results_by_batch(bank_batch_id)
        return {'status': 'ok', 'bank_batch_id': bank_batch_id, 'rows': rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Master Pengembalian archive/comparison API
# ---------------------------------------------------------------------------
def _archive_service():
    # Construct per request so EVKIN_DUCKDB_PATH changes made by tests/runtime
    # are honored, just like the legacy helper module.
    return ArchiveService()


def _progress_service():
    archive = _archive_service()
    return ProgressService(archive.repository.db_path)


def _monthly_service():
    return MonthlyMasterService()


# ---------------------------------------------------------------------------
# Official monthly Master Pengembalian (21062026 MASTER UPDATE- (1).xlsx)
# ---------------------------------------------------------------------------
@router.post("/monthly/preview")
def monthly_preview(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        content = MonthlyMasterService.decode_file(payload)
        return _monthly_service().preview_file(content, payload.get("filename"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/monthly/import")
def monthly_import(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        content = MonthlyMasterService.decode_file(payload)
        return _monthly_service().import_file(
            content=content,
            filename=payload.get("filename") or "21062026 MASTER UPDATE- (1).xlsx",
            period_id=str(payload.get("periode_id") or "").strip(),
            imported_by=payload.get("created_by") or "system",
            metadata=payload.get("metadata") or {},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/dashboard")
def monthly_dashboard(request: Request, periode_id: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().dashboard(periode_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/list")
def monthly_list(request: Request, search: Optional[str] = None,
                 periode_id: Optional[str] = None, tahun: Optional[int] = None,
                 bulan: Optional[int] = None, tahun_sp2d: Optional[int] = None,
                 zona_waktu: Optional[str] = None, status_tendik: Optional[str] = None,
                 provinsi: Optional[str] = None, status_send_bpk: Optional[str] = None,
                 alasan_perubahan: Optional[str] = None, status_perubahan: Optional[str] = None,
                 validation_status: Optional[str] = None,
                 limit: int = 100, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset, max_limit=1000)
    filters = {key: value for key, value in {
        "search": search, "periode_id": periode_id, "tahun": tahun, "bulan": bulan,
        "tahun_sp2d": tahun_sp2d, "zona_waktu": zona_waktu,
        "status_tendik": status_tendik, "provinsi": provinsi,
        "status_send_bpk": status_send_bpk, "alasan_perubahan": alasan_perubahan,
        "status_perubahan": status_perubahan,
        "validation_status": validation_status,
    }.items() if value not in (None, "")}
    try:
        return _monthly_service().list_rows(filters, limit, offset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/detail/{row_id}")
def monthly_detail(row_id: str, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().detail(row_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/monthly/reasons")
def monthly_reasons(request: Request, periode_id: Optional[str] = None,
                    status_send_bpk: Optional[str] = None, bulan: Optional[int] = None):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().reasons(periode_id, status_send_bpk, bulan)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/bnba/{nip}")
def monthly_bnba_trace(nip: str, request: Request, periode_id: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().bnba_trace(nip, periode_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/monthly/imports")
def monthly_imports(request: Request, limit: int = 100):
    _require_pengembalian_api_key(request)
    limit, _ = _pagination(limit, 0)
    return _monthly_service().imports(limit)


@router.post("/monthly/imports/{import_id}/activate")
def monthly_activate_import(import_id: str, payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().activate(import_id, payload.get("created_by") or "system")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/monthly/imports/{import_id}")
def monthly_delete_import(import_id: str, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().delete_import(import_id, "ui")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/monthly/source-database/reset")
def monthly_reset_source_database(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    required = "RESET SUMBER MASTER PENGEMBALIAN"
    if str(payload.get("confirmation") or "").strip().upper() != required:
        raise HTTPException(status_code=400, detail=f"Konfirmasi wajib: {required}")
    try:
        return _monthly_service().reset_source_database(
            payload.get("reset_by") or "ui"
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/reconciliation")
def monthly_reconciliation(request: Request, periode_id: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _monthly_service().reconciliation(periode_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/monthly/download")
def monthly_download(request: Request, search: Optional[str] = None,
                     periode_id: Optional[str] = None, tahun: Optional[int] = None,
                     bulan: Optional[int] = None, tahun_sp2d: Optional[int] = None,
                     zona_waktu: Optional[str] = None, status_tendik: Optional[str] = None,
                     provinsi: Optional[str] = None, status_send_bpk: Optional[str] = None,
                     alasan_perubahan: Optional[str] = None, status_perubahan: Optional[str] = None,
                     validation_status: Optional[str] = None):
    _require_pengembalian_api_key(request)
    filters = {key: value for key, value in locals().items()
               if key not in {"request"} and value not in (None, "")}
    try:
        content = _monthly_service().export_xlsx(filters)
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="MASTER_PENGEMBALIAN_FINAL.xlsx"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/monthly/clear")
def monthly_clear(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    if str(payload.get("confirmation") or "").strip().upper() != "RESET MASTER PENGEMBALIAN":
        raise HTTPException(status_code=400, detail="Konfirmasi tidak sesuai")
    return archive_clear(payload, request)


def _archive_rows(payload: dict):
    rows = payload.get("rows")
    if rows is None:
        rows = payload.get("data")
    if rows is None:
        rows = payload.get("data_awal") or payload.get("data_penyesuaian")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="rows harus berupa array")
    return rows


def _archive_source(payload: dict, default=SOURCE_AWAL):
    return payload.get("source") or payload.get("source_type") or payload.get("jenis_data") or default


def _writable_period(service: ArchiveService, metadata: dict):
    period_id = str(metadata.get("periode_id") or "").strip()
    if not period_id:
        raise HTTPException(status_code=400, detail="Pilih Database Master/Periode sebelum melanjutkan")
    try:
        return service.assert_period_writable(period_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/archive/preview")
def archive_preview(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        rows = _archive_rows(payload)
        embedded = bool((payload.get("metadata") or payload).get("embedded_final_columns"))
        preview_source = "DATA_AWAL" if embedded else _archive_source(payload)
        service = _archive_service()
        metadata = dict(payload.get("metadata") or payload)
        _writable_period(service, metadata)
        result = service.preview(rows, preview_source, metadata)
        result["embedded_final_columns"] = embedded
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/import")
def archive_import(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        rows = _archive_rows(payload)
        metadata = dict(payload.get("metadata") or {})
        if "import_mode" in payload and "import_mode" not in metadata:
            metadata["import_mode"] = payload["import_mode"]
        for key in ("filename", "file_hash", "periode", "batch"):
            if key in payload and key not in metadata:
                metadata[key] = payload[key]
        imported_by = payload.get("created_by") or "system"
        service = _archive_service()
        _writable_period(service, metadata)
        if metadata.get("embedded_final_columns"):
            result = service.import_bnba_combined(
                rows, metadata, imported_by
            )
        else:
            result = service.import_rows(
                rows, _archive_source(payload), metadata, imported_by
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/compare")
def archive_compare(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        filters = dict(payload.get("filters") or {})
        # Accept convenient top-level filters from the UI.
        for key in ("nip", "tahun_sp2d", "periode", "bulan", "batch", "komponen", "flag"):
            if key in payload and key not in filters:
                filters[key] = payload[key]
        return _archive_service().compare(
            filters=filters,
            source_a=payload.get("source_a") or SOURCE_AWAL,
            source_b=payload.get("source_b") or SOURCE_PENYESUAIAN,
            created_by=payload.get("created_by") or "system",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/list")
def archive_list(
    request: Request,
    source: str = SOURCE_AWAL,
    nip: Optional[str] = None,
    search: Optional[str] = None,
    nama: Optional[str] = None,
    periode_id: Optional[str] = None,
    tahun_sp2d: Optional[int] = None,
    periode: Optional[str] = None,
    bulan: Optional[int] = None,
    batch: Optional[str] = None,
    komponen: Optional[str] = None,
    flag: Optional[str] = None,
    bpk_batch: Optional[int] = None,
    provinsi: Optional[str] = None,
    kabupaten_kota: Optional[str] = None,
    kdanaksatker: Optional[str] = None,
    unit_kerja: Optional[str] = None,
    version: Optional[str] = None,
    status_perubahan: Optional[str] = None,
    jenis_perubahan: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset)
    try:
        filters = {
            "nip": nip, "search": search, "nama": nama, "periode_id": periode_id, "tahun_sp2d": tahun_sp2d, "periode": periode, "bulan": bulan,
            "batch": batch, "komponen": komponen, "flag": flag, "bpk_batch": bpk_batch,
            "provinsi": provinsi,
            "kabupaten_kota": kabupaten_kota, "kdanaksatker": kdanaksatker, "version": version,
            "status_perubahan": status_perubahan, "jenis_perubahan": jenis_perubahan,
            "limit": limit, "offset": offset,
        }
        return {"status": "ok", "source": source, "rows": _archive_service().list(source, filters)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/detail/{row_id}")
def archive_detail(row_id: str, request: Request, source: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        row = _archive_service().detail(row_id, source)
        if row is None:
            raise HTTPException(status_code=404, detail="Archive row tidak ditemukan")
        return {"status": "ok", "row": row}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/archive/detail/{row_id}")
def archive_delete_row(row_id: str, payload: dict, request: Request,
                       source: str = "DATA_AWAL"):
    _require_pengembalian_api_key(request)
    required = f"HAPUS ARSIP {row_id}"
    if str(payload.get("confirmation") or "").strip().upper() != required.upper():
        raise HTTPException(status_code=400, detail=f"Konfirmasi wajib: {required}")
    try:
        return _archive_service().delete_archive_row(row_id, source)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/final")
def archive_final(
    request: Request,
    nip: Optional[str] = None,
    search: Optional[str] = None,
    nama: Optional[str] = None,
    periode_id: Optional[str] = None,
    tahun_sp2d: Optional[int] = None,
    nomor_sp2d: Optional[str] = None,
    tahun: Optional[int] = None,
    periode: Optional[str] = None,
    bulan: Optional[int] = None,
    batch: Optional[str] = None,
    komponen: Optional[str] = None,
    provinsi: Optional[str] = None,
    kabupaten_kota: Optional[str] = None,
    kdanaksatker: Optional[str] = None,
    unit_kerja: Optional[str] = None,
    status_perubahan: Optional[str] = None,
    status_compare: Optional[str] = None,
    payment_status: Optional[str] = None,
    change_class: Optional[str] = None,
    arah_perubahan: Optional[str] = None,
    flag_ada_perubahan: Optional[str] = None,
    flag_perubahan_oktober: Optional[str] = None,
    flag_perubahan_november: Optional[str] = None,
    flag_perubahan_desember: Optional[str] = None,
    flag_perubahan_total: Optional[str] = None,
    batch_oktober_normalized: Optional[str] = None,
    batch_november_normalized: Optional[str] = None,
    batch_desember_normalized: Optional[str] = None,
    final_batch_normalized: Optional[str] = None,
    record_ids: Optional[str] = None,
    bpk_batch: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
):
    _require_pengembalian_api_key(request)
    try:
        filters = {
            "nip": nip, "search": search, "nama": nama, "periode_id": periode_id, "tahun_sp2d": tahun_sp2d,
            "nomor_sp2d": nomor_sp2d, "tahun": tahun, "periode": periode,
            "bulan": bulan, "batch": batch, "komponen": komponen,
            "provinsi": provinsi, "kabupaten_kota": kabupaten_kota, "unit_kerja": unit_kerja,
            "kdanaksatker": kdanaksatker, "unit_kerja": unit_kerja,
            "status_perubahan": status_perubahan, "status_compare": status_compare,
            "payment_status": payment_status, "change_class": change_class,
            "arah_perubahan": arah_perubahan, "flag_ada_perubahan": flag_ada_perubahan,
            "flag_perubahan_oktober": flag_perubahan_oktober,
            "flag_perubahan_november": flag_perubahan_november,
            "flag_perubahan_desember": flag_perubahan_desember,
            "flag_perubahan_total": flag_perubahan_total,
            "batch_oktober_normalized": batch_oktober_normalized,
            "batch_november_normalized": batch_november_normalized,
            "batch_desember_normalized": batch_desember_normalized,
            "final_batch_normalized": final_batch_normalized,
        }
        if record_ids:
            filters["record_ids"] = record_ids
        if bpk_batch is not None:
            filters["bpk_batch"] = bpk_batch
        filters["_page_limit"] = limit
        filters["_page_offset"] = offset
        result = _archive_service().final(filters)
        result["total"] = result.get("total", len(result.get("rows", [])))
        result["offset"] = offset
        result["limit"] = limit
        if not result.get("materialized"):
            result["rows"] = result.get("rows", [])[offset:offset + limit]
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/final/ids")
def archive_final_ids(request: Request):
    """Return only FINAL record IDs for select-all and bulk export actions."""
    _require_pengembalian_api_key(request)
    allowed = {
        "nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun", "periode", "bulan",
        "search",
        "batch", "komponen", "provinsi", "kabupaten_kota", "kdanaksatker",
        "unit_kerja",
        "status_compare", "status_perubahan", "payment_status", "change_class", "arah_perubahan", "flag_ada_perubahan",
        "flag_perubahan_oktober", "flag_perubahan_november",
        "flag_perubahan_desember", "flag_perubahan_total",
        "batch_oktober_normalized", "batch_november_normalized",
        "batch_desember_normalized", "final_batch_normalized", "bpk_batch",
    }
    params = dict(request.query_params)
    filters = {key: value for key, value in params.items() if key in allowed and value not in (None, "")}
    try:
        rows = _archive_service().final(filters).get("rows", [])
        return {"status": "ok", "total": len(rows),
                "record_ids": [row["record_id"] for row in rows]}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/bpk-reconciliation")
def archive_bpk_reconciliation(request: Request, bpk_batch: Optional[str] = None,
                               tahun_sp2d: Optional[int] = None, periode: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        filters = {"bpk_batch": bpk_batch, "tahun_sp2d": tahun_sp2d, "periode": periode}
        result = _archive_service().bpk_reconciliation(filters)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/daily-compare")
def archive_daily_compare(request: Request, nip: Optional[str] = None,
                          periode: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().compare_daily(nip, periode)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/daily-detail/{nip}")
def archive_daily_detail(nip: str, request: Request, periode: Optional[str] = None,
                         periode_id: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().daily_detail(nip, periode, periode_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/bpk-reconciliation/download")
def archive_bpk_reconciliation_download(request: Request, bpk_batch: Optional[str] = None,
                                        tahun_sp2d: Optional[int] = None,
                                        periode: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        result = _archive_service().bpk_reconciliation(
            {"bpk_batch": bpk_batch, "tahun_sp2d": tahun_sp2d, "periode": periode}
        )
        content = _archive_service().export_xlsx(compare_result={"details": result["rows"]})
        return StreamingResponse(io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="rekonsiliasi_bpk.xlsx"'})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/archive/history")
def archive_history(request: Request, source: Optional[str] = None, limit: int = 100):
    _require_pengembalian_api_key(request)
    limit, _ = _pagination(limit)
    try:
        return {"status": "ok", **_archive_service().history(source, limit)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/imports/{import_id}/active")
def archive_set_import_active(import_id: str, payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().set_import_active(import_id, bool(payload.get('is_active')))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/database/clear")
def archive_clear_database(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    required = 'RESET DATABASE MASTER PENGEMBALIAN'
    if str(payload.get('confirmation') or '').strip().upper() != required:
        raise HTTPException(status_code=400, detail=f'Konfirmasi wajib: {required}')
    try:
        return _archive_service().clear_archive_database()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/aggregate")
def archive_aggregate(payload: dict, request: Request):
    """Aggregate BNBA values without exposing database-specific SQL."""
    _require_pengembalian_api_key(request)
    try:
        source = _archive_source(payload)
        filters = dict(payload.get("filters") or {})
        group_by = payload.get("group_by") or ["periode"]
        if isinstance(group_by, str):
            group_by = [group_by]
        return {"status": "ok", "source": source,
                "rows": _archive_service().aggregate(source, filters, group_by)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/dashboard")
def archive_dashboard(
    request: Request,
    source: Optional[str] = None,
    nip: Optional[str] = None,
    search: Optional[str] = None,
    nama: Optional[str] = None,
    tahun_sp2d: Optional[int] = None,
    periode: Optional[str] = None,
    bulan: Optional[int] = None,
    batch: Optional[str] = None,
    komponen: Optional[str] = None,
    provinsi: Optional[str] = None,
    kabupaten_kota: Optional[str] = None,
    kdanaksatker: Optional[str] = None,
    unit_kerja: Optional[str] = None,
    version: Optional[str] = None,
    status_perubahan: Optional[str] = None,
    jenis_perubahan: Optional[str] = None,
    status_compare: Optional[str] = None,
    arah_perubahan: Optional[str] = None,
    flag_ada_perubahan: Optional[str] = None,
    flag_perubahan_oktober: Optional[str] = None,
    flag_perubahan_november: Optional[str] = None,
    flag_perubahan_desember: Optional[str] = None,
    flag_perubahan_total: Optional[str] = None,
    batch_oktober_normalized: Optional[str] = None,
    batch_november_normalized: Optional[str] = None,
    batch_desember_normalized: Optional[str] = None,
    final_batch_normalized: Optional[str] = None,
):
    _require_pengembalian_api_key(request)
    filters = {
        "nip": nip, "search": search, "nama": nama, "tahun_sp2d": tahun_sp2d, "periode": periode, "bulan": bulan,
        "batch": batch, "komponen": komponen, "source": source, "provinsi": provinsi,
        "kabupaten_kota": kabupaten_kota, "kdanaksatker": kdanaksatker,
        "unit_kerja": unit_kerja, "search": search, "version": version,
        "status_perubahan": status_perubahan, "jenis_perubahan": jenis_perubahan,
        "status_compare": status_compare, "arah_perubahan": arah_perubahan,
        "flag_ada_perubahan": flag_ada_perubahan,
        "flag_perubahan_oktober": flag_perubahan_oktober,
        "flag_perubahan_november": flag_perubahan_november,
        "flag_perubahan_desember": flag_perubahan_desember,
        "flag_perubahan_total": flag_perubahan_total,
        "batch_oktober_normalized": batch_oktober_normalized,
        "batch_november_normalized": batch_november_normalized,
        "batch_desember_normalized": batch_desember_normalized,
        "final_batch_normalized": final_batch_normalized,
    }
    try:
        return {"status": "ok", **_archive_service().dashboard(filters)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/progress")
def archive_progress(request: Request, nip: Optional[str] = None, search: Optional[str] = None,
                     tahun_sp2d: Optional[int] = None, provinsi: Optional[str] = None,
                     nama_bank: Optional[str] = None, bank: Optional[str] = None,
                     periode_debit: Optional[str] = None,
                     bulan_debit: Optional[int] = None, tahun_debit: Optional[int] = None,
                     komponen: Optional[str] = None, komponen_debit: Optional[str] = None,
                     status: Optional[str] = None, status_debit: Optional[str] = None,
                     status_progress: Optional[str] = None, tenor_bulan: Optional[int] = None,
                     tahap: Optional[int] = None, stage_mode: Optional[str] = None,
                     import_batch_id: Optional[str] = None, batch_id: Optional[str] = None,
                     tanggal_proses: Optional[str] = None, periode_id: Optional[str] = None,
                     all_periods: bool = False,
                     limit: int = 50, offset: int = 0, cursor: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        limit, offset = _pagination(limit, offset, 500)
        values = locals().copy()
        filters = {key: values[key] for key in (
            "search", "tahun_sp2d", "provinsi", "nama_bank", "bank", "periode_debit",
            "bulan_debit", "tahun_debit", "komponen", "komponen_debit", "status", "status_debit", "status_progress",
            "tenor_bulan", "tahap", "stage_mode", "import_batch_id", "batch_id", "tanggal_proses", "periode_id", "all_periods"
        ) if values.get(key) not in (None, "")}
        if nip and not search:
            filters["search"] = nip
        return _progress_service().progress(filters, limit, offset, cursor)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/progress/wide")
def archive_progress_wide(request: Request, search: Optional[str] = None,
                          tahun_sp2d: Optional[int] = None, provinsi: Optional[str] = None,
                          nama_bank: Optional[str] = None, bank: Optional[str] = None,
                          komponen: Optional[str] = None, komponen_debit: Optional[str] = None,
                          status: Optional[str] = None, status_debit: Optional[str] = None,
                          status_progress: Optional[str] = None, tahap: Optional[int] = None,
                          stage_mode: Optional[str] = None, import_batch_id: Optional[str] = None,
                          batch_id: Optional[str] = None, tanggal_proses: Optional[str] = None,
                          periode_id: Optional[str] = None, all_periods: bool = False,
                          limit: int = 50, offset: int = 0):
    _require_pengembalian_api_key(request)
    try:
        limit, offset = _pagination(limit, offset, 200)
        values = locals().copy()
        filters = {key: values[key] for key in ("search","tahun_sp2d","provinsi","nama_bank","bank",
            "komponen","komponen_debit","status","status_debit","status_progress","tahap","stage_mode",
            "import_batch_id","batch_id","tanggal_proses","periode_id","all_periods")
            if values.get(key) not in (None, "")}
        return _progress_service().wide_progress(filters, limit, offset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/progress/import")
def archive_progress_import(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        batch_id = payload.get("import_batch_id")
        if batch_id:
            return _progress_service().commit_batch(batch_id, payload.get("created_by") or "system",
                                                    bool(payload.get("include_warnings", False)))
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise HTTPException(status_code=400, detail="rows harus berupa array")
        return _progress_service().import_rows(rows, payload.get("metadata") or {},
                                               payload.get("created_by") or "system")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/progress/preview")
def archive_progress_preview(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="rows harus berupa array")
    try:
        return _progress_service().preview(rows, payload.get("metadata") or {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/progress/baseline/preview")
async def archive_progress_baseline_preview(request: Request, periode_id: str,
                                            filename: str = "baseline.xlsx"):
    _require_pengembalian_api_key(request)
    temporary_path = None
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(prefix="evkin_progress_baseline_", suffix=".xlsx", delete=False) as temporary:
            temporary_path = temporary.name
            async for chunk in request.stream():
                digest.update(chunk)
                temporary.write(chunk)
        metadata = {"periode_id": periode_id, "filename": Path(filename).name,
                    "file_hash": digest.hexdigest(), "created_by": "ui",
                    "import_mode": "INITIAL_BASELINE"}
        return await asyncio.to_thread(_progress_service().preview_baseline_workbook, temporary_path, metadata)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/dasar-2025/preview")
async def dasar_2025_preview(request: Request, filename: str = "dasar-2025.xlsx"):
    _require_pengembalian_api_key(request)
    try:
        content = await request.body()
        if not content:
            raise ValueError("File XLSX kosong")
        return await asyncio.to_thread(
            DasarPengembalian2025Service(os.environ.get("EVKIN_DUCKDB_PATH") or pengembalian.DUCKDB_PATH).preview,
            content, Path(filename).name,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/dasar-2025/import")
async def dasar_2025_import(request: Request, filename: str = "dasar-2025.xlsx",
                            imported_by: str = "system"):
    _require_pengembalian_api_key(request)
    try:
        content = await request.body()
        if not content:
            raise ValueError("File XLSX kosong")
        return await asyncio.to_thread(
            DasarPengembalian2025Service(os.environ.get("EVKIN_DUCKDB_PATH") or pengembalian.DUCKDB_PATH).commit,
            content, Path(filename).name, imported_by,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/progress/imports/{batch_id}/rollback")
def archive_progress_rollback(batch_id: str, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _progress_service().rollback_batch(batch_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/progress/imports/{batch_id}/validation-result")
def archive_progress_validation_result(batch_id: str, request: Request):
    _require_pengembalian_api_key(request)
    try:
        content = _progress_service().validation_result_xlsx(batch_id)
        return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="VALIDASI_{batch_id}.xlsx"'})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/progress/backfill")
def archive_progress_backfill(request: Request):
    _require_pengembalian_api_key(request)
    return _progress_service().backfill()


@router.get("/archive/progress/history")
def archive_progress_history(request: Request, nip: Optional[str] = None,
                             tahun_sp2d: Optional[int] = None, nama_bank: Optional[str] = None,
                             periode_debit: Optional[str] = None, status_debit: Optional[str] = None,
                             import_batch_id: Optional[str] = None, tahap: Optional[int] = None,
                             komponen_debit: Optional[str] = None, limit: int = 100, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset, 500)
    values = locals().copy()
    filters = {key: values[key] for key in ("nip", "tahun_sp2d", "nama_bank", "periode_debit",
        "status_debit", "import_batch_id", "tahap", "komponen_debit") if values.get(key) not in (None, "")}
    return _progress_service().history(filters, limit, offset)


@router.get("/archive/progress/transactions")
def archive_progress_transactions(request: Request, periode_id: Optional[str] = None,
                                  tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                                  nip: Optional[str] = None, provinsi: Optional[str] = None,
                                  tahap: Optional[int] = None, stage_mode: Optional[str] = None,
                                  bank: Optional[str] = None, status: Optional[str] = None,
                                  batch_id: Optional[str] = None, tanggal_proses: Optional[str] = None,
                                  all_periods: bool = False, limit: int = 100, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset, 500)
    values=locals().copy()
    filters={key:values[key] for key in ("periode_id","tahun_sp2d","komponen","nip","provinsi",
        "tahap","stage_mode","bank","status","batch_id","tanggal_proses","all_periods")
        if values.get(key) not in (None,"")}
    return _progress_service().transactions(filters,limit,offset)


@router.get("/archive/progress/recaps")
def archive_progress_recaps(request: Request, tahun_sp2d: Optional[int] = None,
                           provinsi: Optional[str] = None, nama_bank: Optional[str] = None,
                           periode_debit: Optional[str] = None, search: Optional[str] = None,
                           status_progress: Optional[str] = None, status_debit: Optional[str] = None,
                           komponen_debit: Optional[str] = None, tahap: Optional[int] = None,
                           import_batch_id: Optional[str] = None, periode_id: Optional[str] = None,
                           stage_mode: Optional[str] = None, all_periods: bool = False):
    _require_pengembalian_api_key(request)
    values = locals().copy()
    filters = {key: values[key] for key in ("tahun_sp2d", "provinsi", "nama_bank", "periode_debit",
        "search", "status_progress", "status_debit", "komponen_debit", "tahap", "stage_mode",
        "import_batch_id", "periode_id", "all_periods")
               if values.get(key) not in (None, "")}
    return _progress_service().recaps(filters)


@router.get("/archive/progress/imports")
@router.get("/archive/progress/import-batches")
def archive_progress_imports(request: Request, periode_id: Optional[str] = None,
                             batch_status: Optional[str] = None, all_periods: bool = False,
                             limit: int = 100):
    _require_pengembalian_api_key(request)
    limit, _ = _pagination(limit, 0, 500)
    filters={"periode_id":periode_id,"batch_status":batch_status,"all_periods":all_periods}
    filters={key:value for key,value in filters.items() if value not in (None,"")}
    return _progress_service().batches(filters,limit)


@router.get("/archive/progress/kpi-summary")
def archive_progress_kpi_summary(request: Request, periode_id: Optional[str] = None,
                                 tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                                 nip: Optional[str] = None, provinsi: Optional[str] = None,
                                 kabupaten_kota: Optional[str] = None, batch_bpk: Optional[str] = None,
                                 tahap: Optional[int] = None, stage_mode: Optional[str] = None,
                                 bank: Optional[str] = None, status: Optional[str] = None,
                                 batch_id: Optional[str] = None, tanggal_proses: Optional[str] = None,
                                 all_periods: bool = False):
    _require_pengembalian_api_key(request)
    values=locals().copy()
    filters={key:values[key] for key in ("periode_id","tahun_sp2d","komponen","nip","provinsi","kabupaten_kota","batch_bpk",
        "tahap","stage_mode","bank","status","batch_id","tanggal_proses","all_periods")
        if values.get(key) not in (None,"")}
    return _progress_service().kpi_summary(filters)


@router.get("/archive/progress/operational-dashboard")
def archive_progress_operational_dashboard(request: Request, periode_id: Optional[str] = None,
                                            tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                                            provinsi: Optional[str] = None, kabupaten_kota: Optional[str] = None,
                                            batch_bpk: Optional[str] = None, tahap: Optional[int] = None,
                                            stage_mode: Optional[str] = None, bank: Optional[str] = None,
                                            batch_id: Optional[str] = None, all_periods: bool = False):
    _require_pengembalian_api_key(request)
    values=locals().copy()
    filters={key:values[key] for key in ("periode_id","tahun_sp2d","komponen","provinsi","kabupaten_kota",
        "batch_bpk","tahap","stage_mode","bank","batch_id","all_periods") if values.get(key) not in (None,"")}
    return _progress_service().operational_dashboard(filters)


@router.get("/archive/progress/filter-options")
def archive_progress_filter_options(request: Request, periode_id: Optional[str] = None,
                                    tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                                    provinsi: Optional[str] = None, kabupaten_kota: Optional[str] = None,
                                    batch_bpk: Optional[str] = None, bank: Optional[str] = None,
                                    all_periods: bool = False):
    """Small dynamic option payload for the read-only operational dashboard."""
    _require_pengembalian_api_key(request)
    values = locals().copy()
    filters = {key: values[key] for key in ("periode_id", "tahun_sp2d", "komponen", "provinsi",
        "kabupaten_kota", "batch_bpk", "bank", "all_periods") if values.get(key) not in (None, "")}
    return _progress_service().filter_options(filters)


@router.get("/archive/progress/stage-summary")
def archive_progress_stage_summary(request: Request, periode_id: Optional[str] = None,
                                   tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                                   provinsi: Optional[str] = None, tahap: Optional[int] = None,
                                   stage_mode: Optional[str] = None, bank: Optional[str] = None,
                                   status: Optional[str] = None, batch_id: Optional[str] = None,
                                   all_periods: bool = False):
    _require_pengembalian_api_key(request)
    values=locals().copy()
    filters={key:values[key] for key in ("periode_id","tahun_sp2d","komponen","provinsi","tahap",
        "stage_mode","bank","status","batch_id","all_periods") if values.get(key) not in (None,"")}
    return _progress_service().recaps(filters)


@router.get("/archive/progress/sdm")
def archive_progress_sdm(request: Request, periode_id: Optional[str] = None,
                         tahun_sp2d: Optional[int] = None, komponen: Optional[str] = None,
                         nip: Optional[str] = None, provinsi: Optional[str] = None,
                         kabupaten_kota: Optional[str] = None, batch_bpk: Optional[str] = None,
                         tahap: Optional[int] = None, stage_mode: Optional[str] = None,
                         bank: Optional[str] = None, status: Optional[str] = None,
                         batch_id: Optional[str] = None, all_periods: bool = False,
                         limit: int = 50, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit,offset=_pagination(limit,offset,200)
    values=locals().copy()
    filters={key:values[key] for key in ("periode_id","tahun_sp2d","komponen","nip","provinsi","kabupaten_kota","batch_bpk","tahap",
        "stage_mode","bank","status","batch_id","all_periods") if values.get(key) not in (None,"")}
    return _progress_service().wide_progress(filters,limit,offset)


@router.get("/archive/progress/template")
def archive_progress_template(request: Request):
    _require_pengembalian_api_key(request)
    content = _progress_service().template_xlsx()
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="TEMPLATE_IMPORT_PROGRESS_PENGEMBALIAN.xlsx"'})


@router.get("/archive/progress/download")
def archive_progress_download(request: Request, tahun_sp2d: Optional[int] = None,
                              provinsi: Optional[str] = None, nama_bank: Optional[str] = None,
                              periode_debit: Optional[str] = None, status_progress: Optional[str] = None,
                              search: Optional[str] = None, status_debit: Optional[str] = None,
                              komponen_debit: Optional[str] = None, tahap: Optional[int] = None,
                              import_batch_id: Optional[str] = None, periode_id: Optional[str] = None,
                              stage_mode: Optional[str] = None, all_periods: bool = False,
                              official: bool = False):
    _require_pengembalian_api_key(request)
    values = locals().copy()
    filters = {key: values[key] for key in ("tahun_sp2d", "provinsi", "nama_bank", "periode_debit", "status_progress",
        "search", "status_debit", "komponen_debit", "tahap", "stage_mode", "import_batch_id",
        "periode_id", "all_periods")
               if values.get(key) not in (None, "")}
    content = _progress_service().export_xlsx(filters,official=official)
    return StreamingResponse(io.BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{"LAPORAN_RESMI" if official else "PROGRESS_PENGEMBALIAN"}.xlsx"'})


@router.get("/periods")
def list_periods(request: Request):
    _require_pengembalian_api_key(request)
    try:
        return {"status": "ok", "rows": _archive_service().periods()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memuat periode: {exc}")


@router.post("/periods")
def create_period(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().create_period(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/periods/active")
def get_active_period(request: Request):
    _require_pengembalian_api_key(request)
    return {"status": "ok", "row": _archive_service().active_period()}


@router.post("/periods/{periode_id}/action")
def period_action(periode_id: str, payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().transition_period(
            periode_id, payload.get("action"), payload.get("created_by") or "system"
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/periods/{periode_id}/reset")
def reset_period(periode_id: str, payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    expected = f"RESET PERIODE {periode_id}".upper()
    confirmation = str(payload.get("confirmation") or "").strip().upper()
    if confirmation != expected:
        raise HTTPException(status_code=400, detail=f'Konfirmasi harus bernilai "{expected}"')
    try:
        return _archive_service().reset_period(
            periode_id, payload.get("created_by") or "system"
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/periods/{periode_id}")
def delete_period(periode_id: str, payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    expected = f"HAPUS PERIODE {periode_id}".upper()
    confirmation = str(payload.get("confirmation") or "").strip().upper()
    if confirmation != expected:
        raise HTTPException(status_code=400, detail=f'Konfirmasi harus bernilai "{expected}"')
    try:
        return _archive_service().delete_period(periode_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/datasets/import")
def import_dataset(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="rows harus berupa array")
    try:
        service = _archive_service()
        metadata = dict(payload.get("metadata") or {})
        _writable_period(service, metadata)
        return service.import_dataset(
            rows, metadata, payload.get("created_by") or "system"
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/datasets/import-workbook")
async def import_dataset_workbook(request: Request, periode_id: str,
                                  filename: str = "data_dasar_perhitungan.xlsx"):
    """Stream a large XLSX and import only REKAP OKT/NOV/DES columns A:B."""
    _require_pengembalian_api_key(request)
    service = _archive_service()
    _writable_period(service, {"periode_id": periode_id})
    suffix = Path(filename).suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(status_code=400, detail="Import server hanya menerima file .xlsx")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="evkin_rekap_", suffix=".xlsx",
                                         delete=False) as temporary:
            temporary_path = temporary.name
            async for chunk in request.stream():
                temporary.write(chunk)
        sheets = await asyncio.to_thread(read_rekap_sheets, temporary_path)
        imported = []
        for sheet in sheets:
            metadata = {
                "periode_id": periode_id,
                "filename": Path(filename).name,
                "sheet_name": sheet["sheet_name"],
                "bulan": sheet["bulan"],
                "nama_dataset": f"Data Dasar {sheet['sheet_name']}",
                "jenis_dataset": "DATA_DASAR_PERHITUNGAN_REKAP",
                "import_mode": "SERVER_STREAM_REKAP",
                "defer_rebuild": True,
            }
            imported.append(await asyncio.to_thread(
                service.import_dataset, sheet["rows"], metadata, "ui-server"
            ))
        calculation = await asyncio.to_thread(service.rebuild_dasar_absensi, periode_id)
        return {"status": "ok", "filename": Path(filename).name,
                "datasets": len(imported), "rows": sum(item["rows"] for item in imported),
                "results": imported, "calculation": calculation}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/datasets/materialize-rekap")
def materialize_rekap(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    try:
        service = _archive_service()
        period_id = str(payload.get("periode_id") or "").strip()
        _writable_period(service, {"periode_id": period_id})
        dataset_id = str(payload.get("dataset_id") or "").strip()
        if dataset_id:
            return service.materialize_rekap_dataset(dataset_id)
        return service.materialize_rekap_datasets(period_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/archive/dasar-absensi/{nip}")
def archive_dasar_absensi(nip: str, request: Request,
                          periode_id: Optional[str] = None):
    _require_pengembalian_api_key(request)
    try:
        return _archive_service().dasar_absensi(nip=nip, period_id=periode_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/datasets")
def list_datasets(request: Request, limit: int = 100, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset)
    return _archive_service().datasets(limit, offset)


@router.get("/datasets/{dataset_id}/rows")
def get_dataset_rows(dataset_id: str, request: Request, search: Optional[str] = None,
                     limit: int = 100, offset: int = 0):
    _require_pengembalian_api_key(request)
    limit, offset = _pagination(limit, offset)
    return _archive_service().dataset_rows(dataset_id, search, limit, offset)


@router.get("/datasets/{dataset_id}/download")
def download_dataset(dataset_id: str, request: Request):
    _require_pengembalian_api_key(request)
    try:
        content = _archive_service().export_dataset_xlsx(dataset_id)
        return StreamingResponse(io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="data_dasar_{dataset_id}.xlsx"'})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/payments/import")
def import_payments(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="rows harus berupa array")
    try:
        return _archive_service().import_payments(
            rows, payload.get("metadata") or {}, payload.get("created_by") or "system"
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/archive/clear")
def archive_clear(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    confirmation = str(payload.get("confirmation") or "")
    if confirmation not in {"HAPUS MASTER PENGEMBALIAN", "RESET MASTER PENGEMBALIAN"}:
        raise HTTPException(
            status_code=400,
            detail='Konfirmasi harus bernilai "RESET MASTER PENGEMBALIAN"',
        )
    try:
        return _archive_service().clear_database()
    except Exception as exc:
        message = str(exc)
        if "Failed to delete all rows from index" in message or "database has been invalidated" in message:
            message = (
                "Reset dihentikan karena mesin indeks DuckDB mengalami fatal error. "
                "Data tidak dinyatakan berhasil direset; jalankan ulang backend lalu coba kembali."
            )
            raise HTTPException(status_code=503, detail=message)
        raise HTTPException(status_code=400, detail=message[:2000])


@router.post("/progress/clear")
def progress_clear(payload: dict, request: Request):
    _require_pengembalian_api_key(request)
    confirmation = str(payload.get("confirmation") or "")
    if confirmation not in {"HAPUS PROGRES PENGEMBALIAN", "RESET PROGRESS PENGEMBALIAN"}:
        raise HTTPException(
            status_code=400,
            detail='Konfirmasi harus bernilai "RESET PROGRESS PENGEMBALIAN"',
        )
    try:
        return _progress_service().clear_database()
    except Exception as exc:
        message = str(exc)
        if "Failed to delete all rows from index" in message or "database has been invalidated" in message:
            message = (
                "Reset dihentikan karena mesin indeks DuckDB mengalami fatal error. "
                "Data tidak dinyatakan berhasil direset; jalankan ulang backend lalu coba kembali."
            )
            raise HTTPException(status_code=503, detail=message)
        raise HTTPException(status_code=400, detail=message[:2000])


@router.get("/archive/download")
def archive_download(
    request: Request,
    source: Optional[str] = None,
    compare_id: Optional[str] = None,
    only_changed: bool = False,
    nip: Optional[str] = None,
    search: Optional[str] = None,
    nama: Optional[str] = None,
    periode_id: Optional[str] = None,
    tahun_sp2d: Optional[int] = None,
    periode: Optional[str] = None,
    bulan: Optional[int] = None,
    batch: Optional[str] = None,
    komponen: Optional[str] = None,
    provinsi: Optional[str] = None,
    kabupaten_kota: Optional[str] = None,
    kdanaksatker: Optional[str] = None,
    unit_kerja: Optional[str] = None,
    version: Optional[str] = None,
    status_perubahan: Optional[str] = None,
    jenis_perubahan: Optional[str] = None,
    status_compare: Optional[str] = None,
    payment_status: Optional[str] = None,
    change_class: Optional[str] = None,
    arah_perubahan: Optional[str] = None,
    flag_ada_perubahan: Optional[str] = None,
    flag_perubahan_oktober: Optional[str] = None,
    flag_perubahan_november: Optional[str] = None,
    flag_perubahan_desember: Optional[str] = None,
    flag_perubahan_total: Optional[str] = None,
    batch_oktober_normalized: Optional[str] = None,
    batch_november_normalized: Optional[str] = None,
    batch_desember_normalized: Optional[str] = None,
    final_batch_normalized: Optional[str] = None,
    record_ids: Optional[str] = None,
):
    _require_pengembalian_api_key(request)
    service = _archive_service()
    try:
        filters = {
            "nip": nip, "search": search, "nama": nama, "periode_id": periode_id, "tahun_sp2d": tahun_sp2d, "periode": periode,
            "bulan": bulan, "batch": batch, "komponen": komponen, "provinsi": provinsi,
            "kabupaten_kota": kabupaten_kota, "kdanaksatker": kdanaksatker,
            "unit_kerja": unit_kerja, "version": version,
            "status_perubahan": status_perubahan, "jenis_perubahan": jenis_perubahan,
            "status_compare": status_compare, "payment_status": payment_status,
            "change_class": change_class, "arah_perubahan": arah_perubahan,
            "flag_ada_perubahan": flag_ada_perubahan,
            "flag_perubahan_oktober": flag_perubahan_oktober,
            "flag_perubahan_november": flag_perubahan_november,
            "flag_perubahan_desember": flag_perubahan_desember,
            "flag_perubahan_total": flag_perubahan_total,
            "batch_oktober_normalized": batch_oktober_normalized,
            "batch_november_normalized": batch_november_normalized,
            "batch_desember_normalized": batch_desember_normalized,
            "final_batch_normalized": final_batch_normalized,
        }
        if record_ids:
            filters["record_ids"] = record_ids
        result = None
        if compare_id or only_changed:
            # Re-run only when a caller asks for a downloaded comparison. This
            # keeps the endpoint useful without coupling it to a DB-specific
            # result format.
            result = service.compare(filters=filters)
            if only_changed:
                result["details"] = [
                    detail for detail in result["details"]
                    if detail["result_type"] == "BERUBAH"
                ]
        export_source = source or ("DATA_FINAL" if not result else None)
        content = service.export_xlsx(source=export_source, filters=filters, compare_result=result)
        filename = "pengembalian_archive.xlsx" if result is None else "pengembalian_compare.xlsx"
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
