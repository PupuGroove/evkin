"""
Insert an import_batch record and a corresponding audit_log entry into EVKIN_MASTER.duckdb
Records the counts currently in absensi_raw and absensi_hasil and marks that the migration was applied without file backup.
Usage:
  python 003_record_import_batch.py
"""
from pathlib import Path
import duckdb
import uuid
from datetime import datetime
import json

repo_root = Path(__file__).resolve().parent.parent
duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'

if not duck_path.exists():
    print('DuckDB not found at', duck_path)
    raise SystemExit(1)

conn = duckdb.connect(str(duck_path))
try:
    # get counts
    def safe_count(tbl):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        except Exception:
            return None
    c_raw = safe_count('absensi_raw')
    c_hasil = safe_count('absensi_hasil')

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + 'Z'

    # inspect import_batch columns
    try:
        cols = conn.execute("PRAGMA table_info('import_batch')").fetchall()
    except Exception:
        cols = []
    col_names = [r[1] for r in cols] if cols else []

    ib_fields = {}
    if 'id' in col_names:
        ib_fields['id'] = batch_id
    if 'created_at' in col_names:
        ib_fields['created_at'] = now
    if 'source' in col_names:
        ib_fields['source'] = 'legacy_sqlite: evkin.db'
    if 'note' in col_names:
        ib_fields['note'] = 'Migration 002 applied WITHOUT file-level backup; migrated raw_import and hitung_harian'
    if 'raw_count' in col_names:
        ib_fields['raw_count'] = c_raw
    if 'hasil_count' in col_names:
        ib_fields['hasil_count'] = c_hasil
    if 'details' in col_names:
        ib_fields['details'] = json.dumps({'no_backup': True})

    if ib_fields:
        cols_sql = ', '.join(ib_fields.keys())
        vals_sql = ', '.join(['?'] * len(ib_fields))
        conn.execute(f"INSERT INTO import_batch ({cols_sql}) VALUES ({vals_sql})", tuple(ib_fields.values()))
        print('Inserted import_batch', batch_id)
    else:
        print('No import_batch table or no matching columns to insert into import_batch')

    # create audit_log entry
    try:
        cols_a = conn.execute("PRAGMA table_info('audit_log')").fetchall()
    except Exception:
        cols_a = []
    col_names_a = [r[1] for r in cols_a] if cols_a else []

    al_fields = {}
    al_id = str(uuid.uuid4())
    if 'id' in col_names_a:
        al_fields['id'] = al_id
    if 'created_at' in col_names_a:
        al_fields['created_at'] = now
    if 'action' in col_names_a:
        al_fields['action'] = 'migration_apply'
    if 'table_name' in col_names_a:
        al_fields['table_name'] = 'absensi_raw,absensi_hasil'
    if 'record_id' in col_names_a:
        al_fields['record_id'] = None
    if 'details' in col_names_a:
        al_fields['details'] = json.dumps({
            'batch_id': batch_id,
            'raw_count': c_raw,
            'hasil_count': c_hasil,
            'no_backup': True
        })
    if 'user' in col_names_a:
        al_fields['user'] = 'system:migration_002_no_backup'

    if al_fields:
        cols_sql = ', '.join(al_fields.keys())
        vals_sql = ', '.join(['?'] * len(al_fields))
        conn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({vals_sql})", tuple(al_fields.values()))
        print('Inserted audit_log', al_id)
    else:
        print('No audit_log table or no matching columns to insert into audit_log')

    # report
    print('Counts recorded: absensi_raw=', c_raw, ' absensi_hasil=', c_hasil)
finally:
    conn.close()
