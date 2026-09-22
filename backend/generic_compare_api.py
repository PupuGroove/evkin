from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from backend import generic_compare

router = APIRouter()


class CompareRequest(BaseModel):
    run_name: Optional[str] = None
    table_a: str = Field(..., description="Table name or SELECT SQL for Data A")
    table_b: str = Field(..., description="Table name or SELECT SQL for Data B")
    keys: List[str]
    compare_columns: Optional[List[str]] = None
    created_by: Optional[str] = 'system'


@router.post('/compare/run')
def run_compare(req: CompareRequest):
    try:
        summary = generic_compare.run_generic_compare(req.run_name or 'generic-compare', req.table_a, req.table_b, req.keys, req.compare_columns, created_by=req.created_by or 'system')
        return {'status': 'ok', 'summary': summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/compare/runs')
def list_runs(limit: int = 50):
    conn = None
    try:
        conn = generic_compare._get_conn()
        rows = conn.execute('SELECT run_id, run_name, started_at, finished_at, status, total_a, total_b, matched_count, changed_count, only_a_count, only_b_count FROM generic_compare_run ORDER BY started_at DESC LIMIT ?', [limit]).fetchall()
        res = [dict(r) for r in rows]
        return {'status': 'ok', 'runs': res}
    finally:
        if conn:
            conn.close()


@router.get('/compare/run/{run_id}/details')
def get_run_details(run_id: str, limit: int = 100, offset: int = 0):
    conn = None
    try:
        conn = generic_compare._get_conn()
        rows = conn.execute('SELECT id, key_values, result_type, diffs, created_at FROM generic_compare_detail WHERE run_id = ? ORDER BY created_at LIMIT ? OFFSET ?', [run_id, limit, offset]).fetchall()
        res = [dict(r) for r in rows]
        return {'status': 'ok', 'details': res}
    finally:
        if conn:
            conn.close()
