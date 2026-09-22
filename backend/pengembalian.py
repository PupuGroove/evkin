"""
Service / repository helpers for pengembalian tukin (RETURN-1)
Uses DuckDB and follows project's audit/import_batch conventions.
"""
from __future__ import annotations

import duckdb
import uuid
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

# Keep this repository module independent from the API module to avoid a
# circular import while the FastAPI routers are being registered.
DUCKDB_PATH = os.environ.get('EVKIN_DUCKDB_PATH') or str(Path(__file__).resolve().parent / 'data' / 'EVKIN_MASTER.duckdb')


def _get_conn():
    return duckdb.connect(os.environ.get('EVKIN_DUCKDB_PATH') or DUCKDB_PATH)


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _ensure_tables():
    # safe no-op if migration applied
    conn = _get_conn()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS pengembalian_tukin_case (_tmp TEXT)')
    finally:
        conn.close()


def create_case(nip: str, tahun: int, bulan: int, tipe_kewajiban: str = 'tukin', created_by: str = 'system', metadata: Optional[Dict[str, Any]] = None, pengembalian_id: Optional[str] = None, case_id: Optional[str] = None, komponen: Optional[str] = None) -> str:
    """
    Create a case using a new connection (backwards compatible). For transactional import flows prefer create_case_with_conn.
    Accepts optional case_id (if caller wants to control identifier) and komponen to be embedded in case_id.
    """
    conn = _get_conn()
    try:
        return create_case_with_conn(conn, nip=nip, tahun=tahun, bulan=bulan, tipe_kewajiban=tipe_kewajiban, created_by=created_by, metadata=metadata, pengembalian_id=pengembalian_id, case_id=case_id, komponen=komponen)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _generate_case_id(nip: Optional[str], tahun: Optional[int], bulan: Optional[int], komponen: Optional[str]) -> str:
    """
    Generate business-format case_id like: RET-YYYY-MM-<6digits>-KOMPONEN
    Uses nip+periode+komponen+timestamp to reduce collision risk while keeping human-readable parts.
    """
    # safe defaults
    y = str(tahun) if tahun is not None else '0000'
    m = f"{int(bulan):02d}" if bulan is not None else '00'
    comp = (komponen or 'TUKIN').upper().replace(' ', '_')
    base = f"{nip or ''}:{y}:{m}:{comp}:{datetime.utcnow().isoformat()}"
    # take last 6 hex digits of sha1
    import hashlib
    h = hashlib.sha1(base.encode('utf-8')).hexdigest()[:6]
    return f"RET-{y}-{m}-{h}-{comp}"


def create_case_with_conn(conn, nip: str, tahun: int, bulan: int, tipe_kewajiban: str = 'tukin', created_by: str = 'system', metadata: Optional[Dict[str, Any]] = None, pengembalian_id: Optional[str] = None, case_id: Optional[str] = None, komponen: Optional[str] = None) -> str:
    """
    Insert a case using the provided duckdb connection. Caller controls transaction.
    If case_id not provided, generate a business-format case_id that includes periode and komponen.
    """
    if not case_id:
        case_id = _generate_case_id(nip, tahun, bulan, komponen or tipe_kewajiban)
    now = _now_iso()
    cols = ['case_id', 'pengembalian_id', 'tipe_kewajiban', 'nip', 'tahun', 'bulan', 'status', 'metadata', 'created_at', 'created_by']
    vals = [case_id, pengembalian_id, tipe_kewajiban, nip, tahun, bulan, 'open', json.dumps(metadata) if metadata else None, now, created_by]
    placeholders = ','.join(['?'] * len(vals))
    conn.execute(f"INSERT INTO pengembalian_tukin_case ({', '.join(cols)}) VALUES ({placeholders})", vals)
    return case_id


def insert_history_event(case_id: str, event_type: str, amount: float, created_by: str = 'system', source_table: Optional[str] = None, source_record_id: Optional[str] = None, import_batch_id: Optional[str] = None, notes: Optional[str] = None, currency: Optional[str] = None, source_type: Optional[str] = None, source_file: Optional[str] = None, source_sheet: Optional[str] = None, source_row: Optional[int] = None, source_batch: Optional[str] = None, parent_record_id: Optional[str] = None, calculation_id: Optional[str] = None, calculation_version: Optional[str] = None) -> str:
    conn = _get_conn()
    hid = str(uuid.uuid4())
    now = _now_iso()
    try:
        cols = ['id', 'case_id', 'event_type', 'amount', 'currency', 'balance_after', 'source_table', 'source_record_id', 'import_batch_id', 'notes', 'revision', 'created_at', 'created_by']
        vals = [hid, case_id, event_type, amount, currency, None, source_table, source_record_id, import_batch_id, notes, 1, now, created_by]
        # append lineage columns if present (columns are added by migration 015)
        cols += ['source_type', 'source_file', 'source_sheet', 'source_row', 'source_batch', 'parent_record_id', 'calculation_id', 'calculation_version']
        vals += [source_type, source_file, source_sheet, source_row, source_batch, parent_record_id, calculation_id, calculation_version]
        placeholders = ','.join(['?'] * len(vals))
        conn.execute(f"INSERT INTO pengembalian_tukin_history ({', '.join(cols)}) VALUES ({placeholders})", vals)
        # also write to audit_log following project's pattern
        _record_audit(conn, table_name='pengembalian_tukin_history', record_id=hid, action='insert_history', user=created_by, details={
            'case_id': case_id,
            'event_type': event_type,
            'amount': amount,
            'source_table': source_table,
            'source_record_id': source_record_id,
            'import_batch_id': import_batch_id,
            'source_type': source_type,
            'source_file': source_file,
            'source_sheet': source_sheet,
            'source_row': source_row,
            'source_batch': source_batch,
            'parent_record_id': parent_record_id,
            'calculation_id': calculation_id,
            'calculation_version': calculation_version,
        })
        return hid
    finally:
        conn.close()


def _record_audit(conn, table_name: str, record_id: Optional[str], action: str, user: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Insert an audit_log row using the provided connection. This helper is tolerant to varying audit_log schemas in this project.
    """
    now = _now_iso()
    try:
        try:
            cols = conn.execute("PRAGMA table_info('audit_log')").fetchall()
        except Exception:
            cols = []
        names = [r[1] for r in cols] if cols else []
        fields = {}
        aid = str(uuid.uuid4())
        if 'id' in names:
            fields['id'] = aid
        if 'timestamp' in names:
            fields['timestamp'] = now
        elif 'created_at' in names:
            fields['created_at'] = now
        if 'action' in names:
            fields['action'] = action
        if 'table_name' in names:
            fields['table_name'] = table_name
        if 'record_id' in names:
            fields['record_id'] = record_id
        if 'user' in names:
            fields['user'] = user
        # prefer a generic JSON column if present
        if 'source' in names:
            fields['source'] = json.dumps(details) if details is not None else None
        if 'details' in names and 'source' not in names:
            fields['details'] = json.dumps(details) if details is not None else None
        if 'old_value' in names and 'new_value' in names:
            # place full details into new_value
            fields['old_value'] = None
            fields['new_value'] = json.dumps(details) if details is not None else None
        if fields:
            cols_sql = ', '.join(fields.keys())
            vals = tuple(fields.values())
            conn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
    except Exception:
        # best-effort: don't raise from audit failures
        pass


def get_history(case_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        try:
            df = conn.execute('SELECT * FROM pengembalian_tukin_history WHERE case_id = ? ORDER BY created_at, id', [case_id]).fetchdf()
        except Exception:
            return []
        return df.to_dict(orient='records') if not df.empty else []
    finally:
        conn.close()


def get_current_position(case_id: str) -> float:
    # compute sum of amounts (positive = obligation, negative = repayment) to determine current outstanding
    conn = _get_conn()
    try:
        try:
            res = conn.execute('SELECT SUM(amount) AS s FROM pengembalian_tukin_history WHERE case_id = ?', [case_id]).fetchone()
            s = res[0] if res is not None else None
            return float(s) if s is not None else 0.0
        except Exception:
            return 0.0
    finally:
        conn.close()


def record_import_batch_and_audit(import_payload: Dict[str, Any], created_by: str = 'system') -> str:
    """
    Insert a record into import_batch (if table exists) and create an audit_log entry. Returns batch_id.
    import_payload: dict with metadata fields like nama_file, jenis_data, periode, tahun, jumlah_baris
    This function is non-transactional; for transactional import flows prefer using import_history_awal which performs the full import inside a transaction.
    """
    conn = _get_conn()
    batch_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        try:
            cols = conn.execute("PRAGMA table_info('import_batch')").fetchall()
        except Exception:
            cols = []
        col_names = [r[1] for r in cols] if cols else []
        ib_fields = {}
        if 'id' in col_names:
            ib_fields['id'] = batch_id
        if 'batch_id' in col_names:
            ib_fields['batch_id'] = batch_id
        if 'nama_file' in col_names and 'nama_file' in import_payload:
            ib_fields['nama_file'] = import_payload.get('nama_file')
        # prefer import_type if present, otherwise jenis_data
        if 'import_type' in col_names and 'jenis_data' in import_payload:
            ib_fields['import_type'] = import_payload.get('jenis_data')
        elif 'jenis_data' in col_names and 'jenis_data' in import_payload:
            ib_fields['jenis_data'] = import_payload.get('jenis_data')
        if 'periode' in col_names and 'periode' in import_payload:
            ib_fields['periode'] = import_payload.get('periode')
        if 'tahun' in col_names and 'tahun' in import_payload:
            ib_fields['tahun'] = import_payload.get('tahun')
        if 'jumlah_baris' in col_names and 'jumlah_baris' in import_payload:
            ib_fields['jumlah_baris'] = import_payload.get('jumlah_baris')
        if 'file_hash' in col_names and 'file_hash' in import_payload:
            ib_fields['file_hash'] = import_payload.get('file_hash')
        if 'total_rows' in col_names and 'total_rows' in import_payload:
            ib_fields['total_rows'] = import_payload.get('total_rows')
        if 'success_rows' in col_names and 'success_rows' in import_payload:
            ib_fields['success_rows'] = import_payload.get('success_rows')
        if 'failed_rows' in col_names and 'failed_rows' in import_payload:
            ib_fields['failed_rows'] = import_payload.get('failed_rows')
        if 'imported_at' in col_names:
            ib_fields['imported_at'] = now
        if 'created_at' in col_names and 'created_at' not in ib_fields:
            ib_fields['created_at'] = now
        if ib_fields:
            cols_sql = ', '.join(ib_fields.keys())
            vals = tuple(ib_fields.values())
            conn.execute(f"INSERT INTO import_batch ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
        # audit_log
        try:
            cols_a = conn.execute("PRAGMA table_info('audit_log')").fetchall()
        except Exception:
            cols_a = []
        col_names_a = [r[1] for r in cols_a] if cols_a else []
        al_fields = {}
        al_id = str(uuid.uuid4())
        if 'id' in col_names_a:
            al_fields['id'] = al_id
        if 'timestamp' in col_names_a:
            al_fields['timestamp'] = now
        if 'action' in col_names_a:
            al_fields['action'] = 'import_batch'
        if 'table_name' in col_names_a:
            al_fields['table_name'] = import_payload.get('jenis_data') or 'pengembalian_import'
        if 'record_id' in col_names_a:
            al_fields['record_id'] = batch_id
        if 'user' in col_names_a:
            al_fields['user'] = created_by
        if 'source' in col_names_a:
            al_fields['source'] = json.dumps(import_payload)
        if al_fields:
            cols_sql = ', '.join(al_fields.keys())
            vals = tuple(al_fields.values())
            conn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
        return batch_id
    finally:
        conn.close()


def import_history_awal(rows: List[Dict[str, Any]], file_hash: str, filename: str, import_type: str = 'HISTORY_AWAL', created_by: str = 'system') -> Dict[str, Any]:
    """
    Transactional import of HISTORY_AWAL rows.
    - rows: list of dicts with keys matching pengembalian_history_awal columns (except id, case_id, batch_id, imported_at)
    - file_hash: hash of source file to detect duplicate imports
    - filename: original file name
    Returns dict with batch_id and counts.

    Duplicate detection: if an import_batch exists with same file_hash and import_type, return existing batch_id and do nothing.
    """
    conn = _get_conn()
    now = _now_iso()
    try:
        # inspect import_batch columns and detect duplicate
        try:
            cols = conn.execute("PRAGMA table_info('import_batch')").fetchall()
            col_names = [r[1] for r in cols]
        except Exception:
            col_names = []

        # decide column name for import_type: prefer import_type then jenis_data
        type_col = 'import_type' if 'import_type' in col_names else ('jenis_data' if 'jenis_data' in col_names else None)
        file_hash_col = 'file_hash' if 'file_hash' in col_names else None

        if file_hash_col and type_col:
            q = f"SELECT batch_id FROM import_batch WHERE {file_hash_col} = ? AND {type_col} = ? LIMIT 1"
            existing = conn.execute(q, [file_hash, import_type]).fetchone()
            if existing and existing[0]:
                return {'batch_id': existing[0], 'status': 'duplicate', 'message': 'Duplicate import detected by file_hash'}

        # begin transaction - ensure all-or-nothing
        conn.execute('BEGIN TRANSACTION')
        batch_id = str(uuid.uuid4())
        # insert import_batch record inside transaction so it rolls back on failure
        ib_cols = []
        ib_vals = []
        if 'id' in col_names:
            ib_cols.append('id'); ib_vals.append(batch_id)
        if 'batch_id' in col_names:
            ib_cols.append('batch_id'); ib_vals.append(batch_id)
        if 'nama_file' in col_names:
            ib_cols.append('nama_file'); ib_vals.append(filename)
        if 'import_type' in col_names:
            ib_cols.append('import_type'); ib_vals.append(import_type)
        elif 'jenis_data' in col_names:
            ib_cols.append('jenis_data'); ib_vals.append(import_type)
        if 'file_hash' in col_names:
            ib_cols.append('file_hash'); ib_vals.append(file_hash)
        if 'total_rows' in col_names:
            ib_cols.append('total_rows'); ib_vals.append(len(rows))
        if 'imported_at' in col_names:
            ib_cols.append('imported_at'); ib_vals.append(now)
        if 'status' in col_names:
            ib_cols.append('status'); ib_vals.append('running')
        if ib_cols:
            placeholders = ','.join(['?'] * len(ib_vals))
            conn.execute(f"INSERT INTO import_batch ({', '.join(ib_cols)}) VALUES ({placeholders})", tuple(ib_vals))

        success = 0
        failed = 0
        # prepare insert for pengembalian_history_awal
        for r in rows:
            try:
                # create case using same connection for transactional integrity
                try:
                    case_id = create_case_with_conn(conn, nip=r.get('nip'), tahun=int(r.get('tahun')) if r.get('tahun') is not None else None, bulan=int(r.get('bulan')) if r.get('bulan') is not None else None, created_by=created_by, metadata=None, komponen=r.get('komponen'))
                except Exception:
                    # fallback: if creating case fails, still record row with null case_id to preserve snapshot semantics
                    case_id = None
                hid = str(uuid.uuid4())
                # map fields
                cols_h = ['id', 'case_id', 'batch_id', 'nip', 'nama', 'periode', 'tahun', 'bulan', 'komponen', 'nominal_awal', 'nominal_tukin', 'nominal_uang_makan', 'sumber_data', 'tahun_sp2d', 'nomor_sp2d', 'provinsi', 'unit_kerja', 'jenis_pegawai', 'status_awal', 'source_file', 'source_sheet', 'source_row', 'imported_at', 'source_type', 'source_batch', 'source_record_id', 'parent_record_id', 'calculation_id', 'calculation_version']
                vals_h = [
                    hid,
                    case_id,
                    batch_id,
                    r.get('nip'),
                    r.get('nama'),
                    r.get('periode'),
                    r.get('tahun'),
                    r.get('bulan'),
                    r.get('komponen'),
                    r.get('nominal_awal'),
                    r.get('nominal_tukin'),
                    r.get('nominal_uang_makan'),
                    r.get('sumber_data'),
                    r.get('tahun_sp2d'),
                    r.get('nomor_sp2d'),
                    r.get('provinsi'),
                    r.get('unit_kerja'),
                    r.get('jenis_pegawai'),
                    r.get('status_awal'),
                    r.get('source_file'),
                    r.get('source_sheet'),
                    r.get('source_row'),
                    now,
                    import_type,
                    batch_id,
                    r.get('source_record_id'),
                    r.get('parent_record_id'),
                    r.get('calculation_id'),
                    r.get('calculation_version')
                ]
                placeholders = ','.join(['?'] * len(vals_h))
                conn.execute(f"INSERT INTO pengembalian_history_awal ({', '.join(cols_h)}) VALUES ({placeholders})", tuple(vals_h))
                success += 1
            except Exception as e:
                failed += 1
                # continue inserting other rows; will decide to fail whole import if desired
                # For RETURN-1 we will abort entire import if any failure occurs
                raise

        # update import_batch with success/failed and status
        update_fields = []
        update_vals = []
        if 'success_rows' in col_names:
            update_fields.append('success_rows = ?'); update_vals.append(success)
        if 'failed_rows' in col_names:
            update_fields.append('failed_rows = ?'); update_vals.append(failed)
        if 'status' in col_names:
            update_fields.append("status = ?"); update_vals.append('done')
        if 'imported_at' in col_names and 'imported_at' not in ib_cols:
            update_fields.append('imported_at = ?'); update_vals.append(now)
        if update_fields:
            update_vals.append(batch_id)
            conn.execute(f"UPDATE import_batch SET {', '.join(update_fields)} WHERE batch_id = ?", tuple(update_vals))

        conn.execute('COMMIT')

        # record audit log now (outside transaction to ensure visibility)
        try:
            cols_a = conn.execute("PRAGMA table_info('audit_log')").fetchall()
        except Exception:
            cols_a = []
        col_names_a = [r[1] for r in cols_a] if cols_a else []
        al_fields = {}
        al_id = str(uuid.uuid4())
        if 'id' in col_names_a:
            al_fields['id'] = al_id
        if 'timestamp' in col_names_a:
            al_fields['timestamp'] = now
        if 'action' in col_names_a:
            al_fields['action'] = 'import_history_awal'
        if 'table_name' in col_names_a:
            al_fields['table_name'] = 'pengembalian_history_awal'
        if 'record_id' in col_names_a:
            al_fields['record_id'] = batch_id
        if 'user' in col_names_a:
            al_fields['user'] = created_by
        if 'source' in col_names_a:
            al_fields['source'] = json.dumps({'file_hash': file_hash, 'filename': filename, 'total_rows': len(rows)})
        if al_fields:
            cols_sql = ', '.join(al_fields.keys())
            vals = tuple(al_fields.values())
            conn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)

        return {'batch_id': batch_id, 'status': 'ok', 'total_rows': len(rows), 'success_rows': success, 'failed_rows': failed}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


# simple helper used by tests/migrations


def insert_dasar_perhitungan_batch(rows: List[Dict[str, Any]], batch_meta: Optional[Dict[str, Any]] = None, created_by: str = 'system') -> Dict[str, Any]:
    """
    Insert a batch of dasar perhitungan rows into pengembalian_dasar_perhitungan.
    rows: list of dicts per migration 009 schema keys.
    batch_meta: optional metadata dict (batch_name, calculation_version, rule_version, keterangan)
    Returns dict with batch_id and counts.
    This function is non-destructive and does NOT create history events (per RETURN-2 choice).
    """
    conn = _get_conn()
    try:
        conn.execute('BEGIN TRANSACTION')
        batch_id = str(uuid.uuid4())
        inserted = 0
        try:
            cols_info = conn.execute("PRAGMA table_info('pengembalian_dasar_perhitungan')").fetchall()
            table_cols = [c[1] for c in cols_info] if cols_info else []
        except Exception:
            table_cols = []

        now = _now_iso()
        for r in rows:
            rid = str(uuid.uuid4())
            # prepare fields
            record = dict(r) if isinstance(r, dict) else {}
            # ensure some standard fields
            record.setdefault('id', rid)
            record.setdefault('calculation_batch_id', batch_id)
            record.setdefault('calculation_version', batch_meta.get('calculation_version') if batch_meta else record.get('calculation_version'))
            record.setdefault('rule_version', batch_meta.get('rule_version') if batch_meta else record.get('rule_version'))
            record.setdefault('calculated_at', batch_meta.get('calculated_at') if batch_meta and batch_meta.get('calculated_at') else now)
            # filter keys to table columns
            if table_cols:
                keys = [k for k in record.keys() if k in table_cols]
            else:
                keys = list(record.keys())
            vals = [record.get(k) for k in keys]
            placeholders = ','.join(['?'] * len(vals)) if vals else ''
            if keys:
                conn.execute(f"INSERT INTO pengembalian_dasar_perhitungan ({', '.join(keys)}) VALUES ({placeholders})", tuple(vals))
                inserted += 1
        # audit
        try:
            _record_audit(conn, table_name='pengembalian_dasar_perhitungan', record_id=batch_id, action='insert_dasar_batch', user=created_by, details={'batch_meta': batch_meta, 'inserted': inserted})
        except Exception:
            pass
        try:
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        return {'batch_id': batch_id, 'status': 'ok', 'inserted': inserted}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


# RETURN-3/4/5: BPK/Bank flows

def send_bpk_batch(items: List[Dict[str, Any]], batch_meta: Optional[Dict[str, Any]] = None, created_by: str = 'system') -> Dict[str, Any]:
    """
    Create a BPK batch and insert detail rows. items should include case_id/nip/periode/komponen/nominal.
    Returns batch_id and counts. Append-only and records audit.
    """
    conn = _get_conn()
    try:
        conn.execute('BEGIN TRANSACTION')
        batch_id = str(uuid.uuid4())
        now = _now_iso()
        # insert batch if table exists
        try:
            cols = conn.execute("PRAGMA table_info('pengembalian_bpk_batch')").fetchall()
        except Exception:
            cols = []
        names = [c[1] for c in cols] if cols else []
        batch_fields = {}
        if 'batch_id' in names:
            batch_fields['batch_id'] = batch_id
        if 'batch_name' in names and batch_meta and 'batch_name' in batch_meta:
            batch_fields['batch_name'] = batch_meta.get('batch_name')
        if 'created_at' in names:
            batch_fields['created_at'] = now
        if 'created_by' in names:
            batch_fields['created_by'] = created_by
        if 'status' in names:
            batch_fields['status'] = 'created'
        if 'metadata' in names and batch_meta is not None:
            batch_fields['metadata'] = json.dumps(batch_meta)
        if batch_fields:
            cols_sql = ', '.join(batch_fields.keys())
            vals = tuple(batch_fields.values())
            conn.execute(f"INSERT INTO pengembalian_bpk_batch ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
        # insert details
        inserted = 0
        for it in items:
            try:
                did = str(uuid.uuid4())
                cols_d = conn.execute("PRAGMA table_info('pengembalian_bpk_detail')").fetchall()
                dnames = [c[1] for c in cols_d] if cols_d else []
                dfields = {}
                if 'id' in dnames:
                    dfields['id'] = did
                if 'batch_id' in dnames:
                    dfields['batch_id'] = batch_id
                for k in ('case_id','nip','periode','komponen'):
                    if k in dnames and k in it:
                        dfields[k] = it.get(k)
                if 'nominal' in dnames and 'nominal' in it:
                    dfields['nominal'] = it.get('nominal')
                if 'created_at' in dnames:
                    dfields['created_at'] = now
                if 'created_by' in dnames:
                    dfields['created_by'] = created_by
                if 'source_file' in dnames and 'source_file' in it:
                    dfields['source_file'] = it.get('source_file')
                if 'source_row' in dnames and 'source_row' in it:
                    dfields['source_row'] = it.get('source_row')
                if 'notes' in dnames and 'notes' in it:
                    dfields['notes'] = it.get('notes')
                if dfields:
                    cols_sql = ', '.join(dfields.keys())
                    vals = tuple(dfields.values())
                    conn.execute(f"INSERT INTO pengembalian_bpk_detail ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
                    inserted += 1
            except Exception:
                # continue inserting other details
                continue
        # audit
        try:
            _record_audit(conn, table_name='pengembalian_bpk_batch', record_id=batch_id, action='send_bpk_batch', user=created_by, details={'batch_meta': batch_meta, 'inserted': inserted})
        except Exception:
            pass
        conn.execute('COMMIT')
        return {'status': 'ok', 'batch_id': batch_id, 'inserted': inserted}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


def send_bank_batch(items: List[Dict[str, Any]], batch_meta: Optional[Dict[str, Any]] = None, created_by: str = 'system') -> Dict[str, Any]:
    """
    Create a Bank batch and insert detail rows. Similar to send_bpk_batch.
    """
    conn = _get_conn()
    try:
        conn.execute('BEGIN TRANSACTION')
        batch_id = str(uuid.uuid4())
        now = _now_iso()
        try:
            cols = conn.execute("PRAGMA table_info('pengembalian_bank_batch')").fetchall()
        except Exception:
            cols = []
        names = [c[1] for c in cols] if cols else []
        batch_fields = {}
        if 'batch_id' in names:
            batch_fields['batch_id'] = batch_id
        if 'batch_name' in names and batch_meta and 'batch_name' in batch_meta:
            batch_fields['batch_name'] = batch_meta.get('batch_name')
        if 'created_at' in names:
            batch_fields['created_at'] = now
        if 'created_by' in names:
            batch_fields['created_by'] = created_by
        if 'status' in names:
            batch_fields['status'] = 'created'
        if 'metadata' in names and batch_meta is not None:
            batch_fields['metadata'] = json.dumps(batch_meta)
        if batch_fields:
            cols_sql = ', '.join(batch_fields.keys())
            vals = tuple(batch_fields.values())
            conn.execute(f"INSERT INTO pengembalian_bank_batch ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
        # insert details
        inserted = 0
        for it in items:
            try:
                did = str(uuid.uuid4())
                cols_d = conn.execute("PRAGMA table_info('pengembalian_bank_detail')").fetchall()
                dnames = [c[1] for c in cols_d] if cols_d else []
                dfields = {}
                if 'id' in dnames:
                    dfields['id'] = did
                if 'batch_id' in dnames:
                    dfields['batch_id'] = batch_id
                for k in ('case_id','nip','periode','komponen'):
                    if k in dnames and k in it:
                        dfields[k] = it.get(k)
                if 'nominal' in dnames and 'nominal' in it:
                    dfields['nominal'] = it.get('nominal')
                if 'created_at' in dnames:
                    dfields['created_at'] = now
                if 'created_by' in dnames:
                    dfields['created_by'] = created_by
                if 'reference' in dnames and 'reference' in it:
                    dfields['reference'] = it.get('reference')
                if dfields:
                    cols_sql = ', '.join(dfields.keys())
                    vals = tuple(dfields.values())
                    conn.execute(f"INSERT INTO pengembalian_bank_detail ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
                    inserted += 1
            except Exception:
                continue
        # audit
        try:
            _record_audit(conn, table_name='pengembalian_bank_batch', record_id=batch_id, action='send_bank_batch', user=created_by, details={'batch_meta': batch_meta, 'inserted': inserted})
        except Exception:
            pass
        conn.execute('COMMIT')
        return {'status': 'ok', 'batch_id': batch_id, 'inserted': inserted}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


def record_bank_results(bank_batch_id: str, results: List[Dict[str, Any]], created_by: str = 'system') -> Dict[str, Any]:
    """
    Record bank results (success/failure). For each successful debit, create a history repayment event (negative amount).
    results: list of dicts with keys: bank_detail_id (optional), case_id, nip, nominal, status ('SUCCESS'|'FAILED'), reason
    """
    conn = _get_conn()
    try:
        conn.execute('BEGIN TRANSACTION')
        inserted = 0
        failed = 0
        now = _now_iso()
        for r in results:
            try:
                rid = str(uuid.uuid4())
                cols_r = conn.execute("PRAGMA table_info('pengembalian_bank_result')").fetchall()
                rnames = [c[1] for c in cols_r] if cols_r else []
                rfields = {}
                if 'id' in rnames:
                    rfields['id'] = rid
                if 'bank_batch_id' in rnames:
                    rfields['bank_batch_id'] = bank_batch_id
                if 'bank_detail_id' in rnames and 'bank_detail_id' in r:
                    rfields['bank_detail_id'] = r.get('bank_detail_id')
                for k in ('case_id','nip'):
                    if k in rnames and k in r:
                        rfields[k] = r.get(k)
                if 'nominal' in rnames and 'nominal' in r:
                    rfields['nominal'] = r.get('nominal')
                if 'status' in rnames:
                    rfields['status'] = r.get('status')
                if 'reason' in rnames:
                    rfields['reason'] = r.get('reason')
                if 'processed_at' in rnames:
                    rfields['processed_at'] = now
                if 'processed_by' in rnames:
                    rfields['processed_by'] = created_by
                if rfields:
                    cols_sql = ', '.join(rfields.keys())
                    vals = tuple(rfields.values())
                    conn.execute(f"INSERT INTO pengembalian_bank_result ({cols_sql}) VALUES ({', '.join(['?']*len(vals))})", vals)
                # if success -> create history repayment event (negative amount)
                st = (r.get('status') or '').upper()
                if st in ('SUCCESS', 'BERHASIL') and r.get('nominal'):
                    try:
                        # amount negative to represent repayment
                        hid = insert_history_event(case_id=r.get('case_id'), event_type='bank_debit', amount=-abs(float(r.get('nominal'))), created_by=created_by, source_table='pengembalian_bank_result', source_record_id=rid, import_batch_id=bank_batch_id)
                    except Exception:
                        # continue even if history insertion fails
                        pass
                inserted += 1
            except Exception:
                failed += 1
                continue
        # audit
        try:
            _record_audit(conn, table_name='pengembalian_bank_result', record_id=bank_batch_id, action='record_bank_results', user=created_by, details={'inserted': inserted, 'failed': failed})
        except Exception:
            pass
        conn.execute('COMMIT')
        return {'status': 'ok', 'inserted': inserted, 'failed': failed}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


def get_bank_results_by_batch(bank_batch_id: str):
    conn = _get_conn()
    try:
        try:
            df = conn.execute('SELECT * FROM pengembalian_bank_result WHERE bank_batch_id = ? ORDER BY processed_at', [bank_batch_id]).fetchdf()
        except Exception:
            return []
        return df.to_dict(orient='records') if not df.empty else []
    finally:
        conn.close()


def get_dasar_by_case(case_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        try:
            df = conn.execute('SELECT * FROM pengembalian_dasar_perhitungan WHERE case_id = ? ORDER BY calculated_at DESC', [case_id]).fetchdf()
        except Exception:
            return []
        return df.to_dict(orient='records') if not df.empty else []
    finally:
        conn.close()


def insert_penyesuaian(rows: List[Dict[str, Any]], created_by: str = 'system') -> Dict[str, Any]:
    """
    Insert one or multiple penyesuaian rows into pengembalian_penyesuaian.
    Each row should include case_id, nip, periode, komponen, nominal_sebelum, nominal_setelah, selisih, jenis_penyesuaian, alasan_penyesuaian, reference_id
    Revision is computed per case as max(revision)+1.
    This function does NOT create history events; approvals or send actions will create history entries in later phases.
    """
    conn = _get_conn()
    try:
        conn.execute('BEGIN TRANSACTION')
        inserted = 0
        try:
            cols_info = conn.execute("PRAGMA table_info('pengembalian_penyesuaian')").fetchall()
            table_cols = [c[1] for c in cols_info] if cols_info else []
        except Exception:
            table_cols = []

        # collect case_id set to compute next revision per case
        cases = list({r.get('case_id') for r in rows if r.get('case_id')})
        rev_map = {}
        try:
            for cid in cases:
                res = conn.execute('SELECT MAX(revision) FROM pengembalian_penyesuaian WHERE case_id = ?', [cid]).fetchone()
                rev_map[cid] = (res[0] or 0) + 1
        except Exception:
            # if table missing or error, default to 1 per row
            rev_map = {cid: 1 for cid in cases}

        now = _now_iso()
        for r in rows:
            pid = str(uuid.uuid4())
            rec = dict(r) if isinstance(r, dict) else {}
            rec.setdefault('id', pid)
            cid = rec.get('case_id')
            if cid:
                rec.setdefault('revision', rev_map.get(cid, 1))
            else:
                rec.setdefault('revision', 1)
            rec.setdefault('created_at', now)
            if table_cols:
                keys = [k for k in rec.keys() if k in table_cols]
            else:
                keys = list(rec.keys())
            vals = [rec.get(k) for k in keys]
            if keys:
                conn.execute(f"INSERT INTO pengembalian_penyesuaian ({', '.join(keys)}) VALUES ({', '.join(['?']*len(vals))})", tuple(vals))
                inserted += 1
        # audit
        try:
            _record_audit(conn, table_name='pengembalian_penyesuaian', record_id=None, action='insert_penyesuaian', user=created_by, details={'rows': len(rows)})
        except Exception:
            pass
        try:
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        return {'status': 'ok', 'inserted': inserted}
    except Exception as e:
        try:
            conn.execute('ROLLBACK')
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
    finally:
        conn.close()


def get_penyesuaian_by_case(case_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        try:
            df = conn.execute('SELECT * FROM pengembalian_penyesuaian WHERE case_id = ? ORDER BY created_at DESC', [case_id]).fetchdf()
        except Exception:
            return []
        return df.to_dict(orient='records') if not df.empty else []
    finally:
        conn.close()


if __name__ == '__main__':
    print('pengembalian helper module')
