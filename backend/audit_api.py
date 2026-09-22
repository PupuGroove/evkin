from fastapi import APIRouter, HTTPException, Request
import duckdb
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.evkin_export_api import DUCKDB_PATH

router = APIRouter()


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _insert_audit(conn, entry: Dict[str, Any]) -> Optional[str]:
    """
    Insert a single audit entry into audit_log table if columns exist. Returns inserted id or None.
    Tolerant to varying audit_log schemas.
    """
    try:
        try:
            cols = conn.execute("PRAGMA table_info('audit_log')").fetchall()
        except Exception:
            cols = []
        names = [r[1] for r in cols] if cols else []
        fields: Dict[str, Any] = {}
        aid = entry.get('id') or str(uuid.uuid4())
        now = entry.get('timestamp') or _now_iso()
        if 'id' in names:
            fields['id'] = aid
        if 'timestamp' in names:
            fields['timestamp'] = now
        elif 'created_at' in names:
            fields['created_at'] = now
        if 'action' in names and 'action' in entry:
            fields['action'] = entry.get('action')
        elif 'action' in names:
            fields['action'] = entry.get('type') or entry.get('event') or None
        if 'table_name' in names and 'table_name' in entry:
            fields['table_name'] = entry.get('table_name')
        if 'record_id' in names and 'record_id' in entry:
            fields['record_id'] = entry.get('record_id')
        if 'user' in names and 'user' in entry:
            fields['user'] = entry.get('user')
        # prefer a generic JSON column if present
        if 'source' in names:
            fields['source'] = json.dumps(entry.get('source') if 'source' in entry else entry)
        elif 'details' in names:
            fields['details'] = json.dumps(entry.get('details') if 'details' in entry else entry)
        # support old_value/new_value pattern
        if 'old_value' in names and 'new_value' in names:
            fields['old_value'] = json.dumps(entry.get('old_value')) if 'old_value' in entry else None
            fields['new_value'] = json.dumps(entry.get('new_value') if 'new_value' in entry else entry)
        # If no conventional fields found, try to put payload into 'details' or 'source' if available
        if not fields and names:
            # place everything into first JSON-like column if exists
            chosen = None
            for candidate in ['source', 'details', 'new_value']:
                if candidate in names:
                    chosen = candidate
                    break
            if chosen:
                fields[chosen] = json.dumps(entry)
        if not fields:
            # nothing to insert into audit_log (no matching columns), skip
            return None
        cols_sql = ', '.join(fields.keys())
        vals = tuple(fields.values())
        placeholders = ', '.join(['?'] * len(vals))
        conn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({placeholders})", vals)
        return aid
    except Exception:
        return None


@router.post('/api/audit')
def post_audit(payload: Dict[str, Any], request: Request):
    """Accept a single audit entry (JSON) and insert into audit_log if possible."""
    try:
        dconn = duckdb.connect(DUCKDB_PATH)
        try:
            aid = _insert_audit(dconn, payload)
            if aid:
                return {"status": "ok", "id": aid}
            else:
                raise HTTPException(status_code=400, detail='audit_log table missing or no matching columns to insert')
        finally:
            dconn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/api/audit/batch')
def post_audit_batch(payload: Dict[str, Any], request: Request):
    """Accept batch audits: {"audits": [ ... ]} and insert as many as possible.
    Returns summary {inserted: n, failed: m, ids: [...]}
    """
    audits: List[Dict[str, Any]] = payload.get('audits') or []
    if not isinstance(audits, list):
        raise HTTPException(status_code=400, detail='audits must be a list')
    inserted = 0
    failed = 0
    ids: List[str] = []
    try:
        dconn = duckdb.connect(DUCKDB_PATH)
        try:
            for a in audits:
                try:
                    aid = _insert_audit(dconn, a)
                    if aid:
                        inserted += 1
                        ids.append(aid)
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            return {"status": "ok", "inserted": inserted, "failed": failed, "ids": ids}
        finally:
            dconn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
