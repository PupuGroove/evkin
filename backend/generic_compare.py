"""
Generic data compare service.
Provides a simple, configurable compare: Data A vs Data B using user-specified key columns.
Stores runs in generic_compare_run and details in generic_compare_detail (DuckDB).

This initial implementation uses pandas DataFrame merge for clarity. For very large tables, consider implementing purely-in-SQL or chunked processing.
"""
from __future__ import annotations

import duckdb
import uuid
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from pathlib import Path

# DuckDB path inside repository (backend/data/EVKIN_MASTER.duckdb)
DUCKDB_PATH = str(Path(__file__).resolve().parent / 'data' / 'EVKIN_MASTER.duckdb')


def _get_conn():
    return duckdb.connect(DUCKDB_PATH)


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _to_json_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


def run_generic_compare(run_name: str, table_a: str, table_b: str, keys: List[str], compare_columns: Optional[List[str]] = None, created_by: str = 'system') -> Dict[str, Any]:
    """
    Run a generic compare between table_a and table_b. table_a/table_b can be table names or SQL expressions (SELECT ...).
    keys: list of column names used as join key.
    compare_columns: optional list of columns to compare; if None, compare all common columns except keys.

    Returns summary dict and writes run + detail rows to DuckDB tables.
    """
    conn = _get_conn()
    run_id = 'GRC-' + uuid.uuid4().hex
    started_at = _now_iso()

    # Persist run header (basic)
    try:
        conn.execute('INSERT INTO generic_compare_run (run_id, run_name, table_a, table_b, keys, compare_columns, started_at, status, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (run_id, run_name, table_a, table_b, json.dumps(keys), _to_json_safe(compare_columns), started_at, 'running', created_by))
    except Exception:
        # if insert fails (table missing), attempt to create it is migration's job; raise
        conn.close()
        raise

    try:
        # Prepare SQL for selecting data
        def prepare_select(spec: str) -> str:
            s = spec.strip()
            if s.lower().startswith('select'):
                return f'({s}) as src'
            else:
                # assume table name
                return f'(SELECT * FROM "{s}") as src'

        sel_a = f'SELECT * FROM {prepare_select(table_a)}'
        sel_b = f'SELECT * FROM {prepare_select(table_b)}'

        # fetch dataframes using duckdb -> pandas
        try:
            import pandas as pd
        except Exception:
            conn.close()
            raise

        df_a = conn.execute(sel_a).fetchdf()
        df_b = conn.execute(sel_b).fetchdf()

        total_a = len(df_a)
        total_b = len(df_b)

        # detect duplicates in A and B
        dup_a_keys = []
        dup_b_keys = []
        if total_a > 0:
            dup_a = df_a.groupby(keys).size().reset_index(name='cnt')
            dup_a_keys = dup_a[dup_a['cnt'] > 1][keys].to_dict(orient='records') if not dup_a.empty else []
        if total_b > 0:
            dup_b = df_b.groupby(keys).size().reset_index(name='cnt')
            dup_b_keys = dup_b[dup_b['cnt'] > 1][keys].to_dict(orient='records') if not dup_b.empty else []

        # decide compare columns
        if compare_columns is None:
            common_cols = [c for c in df_a.columns if c in df_b.columns and c not in keys]
        else:
            common_cols = [c for c in compare_columns if c in df_a.columns and c in df_b.columns]

        # outer merge on keys
        merged = df_a.merge(df_b, on=keys, how='outer', suffixes=('_a', '_b'), indicator=True)

        # summary counters
        matched = 0
        changed = 0
        only_a = 0
        only_b = 0
        duplicate = 0
        nominal_diff = 0

        # insert details per row
        import math
        for idx, row in merged.iterrows():
            key_vals = {k: row.get(k) for k in keys}
            indicator = row.get('_merge')
            record_a = None
            record_b = None
            result_type = None
            diffs = {}

            if indicator == 'left_only':
                result_type = 'ONLY_A'
                only_a += 1
                record_a = {c: row.get(c + '_a') for c in df_a.columns}
            elif indicator == 'right_only':
                result_type = 'ONLY_B'
                only_b += 1
                record_b = {c: row.get(c + '_b') for c in df_b.columns}
            else:
                # present in both
                # check duplicates first
                # duplicates detection based on dup_a_keys/dup_b_keys
                is_dup = False
                for dk in dup_a_keys:
                    if all((str(key_vals.get(k)) == str(dk.get(k))) for k in keys):
                        is_dup = True
                        break
                for dk in dup_b_keys:
                    if all((str(key_vals.get(k)) == str(dk.get(k))) for k in keys):
                        is_dup = True
                        break
                if is_dup:
                    result_type = 'DUPLICATE'
                    duplicate += 1
                else:
                    # compare columns
                    equal_all = True
                    numeric_diff_found = False
                    for col in common_cols:
                        a_val = row.get(col + '_a')
                        b_val = row.get(col + '_b')
                        if pd.isna(a_val) and pd.isna(b_val):
                            continue
                        if a_val == b_val:
                            continue
                        # check numeric difference
                        try:
                            a_num = float(a_val) if a_val is not None else float('nan')
                            b_num = float(b_val) if b_val is not None else float('nan')
                            if not (math.isnan(a_num) and math.isnan(b_num)) and abs(a_num - b_num) > 1e-9:
                                numeric_diff_found = True
                                diffs[col] = {'a': a_val, 'b': b_val}
                                equal_all = False
                                # don't break — collect diffs
                                continue
                        except Exception:
                            # non-numeric or can't cast
                            equal_all = False
                            diffs[col] = {'a': a_val, 'b': b_val}
                    if equal_all:
                        result_type = 'MATCH'
                        matched += 1
                    else:
                        if numeric_diff_found:
                            result_type = 'NOMINAL_DIFFERENCE'
                            nominal_diff += 1
                        else:
                            result_type = 'CHANGED'
                            changed += 1
                    # attach both records
                    record_a = {c: row.get(c + '_a') for c in df_a.columns}
                    record_b = {c: row.get(c + '_b') for c in df_b.columns}

            # if left_only or right_only, still capture full record if possible
            if record_a is None and indicator in ('both','left_only'):
                record_a = {c: row.get(c + '_a') for c in df_a.columns if (c + '_a') in row.index}
            if record_b is None and indicator in ('both','right_only'):
                record_b = {c: row.get(c + '_b') for c in df_b.columns if (c + '_b') in row.index}

            # store detail row
            detail_id = 'GCD-' + uuid.uuid4().hex
            try:
                conn.execute('INSERT INTO generic_compare_detail (id, run_id, key_values, record_a, record_b, result_type, diffs) VALUES (?, ?, ?, ?, ?, ?, ?)',
                             (detail_id, run_id, _to_json_safe(key_vals), _to_json_safe(record_a), _to_json_safe(record_b), result_type, _to_json_safe(diffs)))
            except Exception as e:
                # best-effort: continue
                pass

        # update run summary
        finished_at = _now_iso()
        try:
            conn.execute('UPDATE generic_compare_run SET finished_at = ?, status = ?, total_a = ?, total_b = ?, matched_count = ?, changed_count = ?, only_a_count = ?, only_b_count = ?, duplicate_count = ?, nominal_diff_count = ? WHERE run_id = ?',
                         (finished_at, 'done', int(total_a), int(total_b), int(matched), int(changed), int(only_a), int(only_b), int(duplicate), int(nominal_diff), run_id))
        except Exception:
            pass

        summary = {
            'run_id': run_id,
            'run_name': run_name,
            'total_a': total_a,
            'total_b': total_b,
            'matched': matched,
            'changed': changed,
            'only_a': only_a,
            'only_b': only_b,
            'duplicate': duplicate,
            'nominal_diff': nominal_diff,
            'finished_at': finished_at
        }
        conn.close()
        return summary
    except Exception as e:
        try:
            conn.execute('UPDATE generic_compare_run SET finished_at = ?, status = ? WHERE run_id = ?', (_now_iso(), 'error', run_id))
        except Exception:
            pass
        conn.close()
        raise
