"""Migration 022: create BPK and Bank batch/detail/result tables for pengembalian flows
Non-destructive: uses IF NOT EXISTS
"""
from pathlib import Path
import duckdb
import os

DB = os.environ.get('EVKIN_DUCKDB_PATH') or str(Path(__file__).resolve().parent.parent / 'data' / 'EVKIN_MASTER.duckdb')

print('Running migration 022_create_bpk_bank_tables on', DB)
conn = duckdb.connect(DB)
try:
    conn.execute('''
    CREATE TABLE IF NOT EXISTS pengembalian_bpk_batch (
        batch_id TEXT PRIMARY KEY,
        batch_name TEXT,
        created_at TEXT,
        created_by TEXT,
        status TEXT,
        metadata TEXT
    )''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS pengembalian_bpk_detail (
        id TEXT PRIMARY KEY,
        batch_id TEXT,
        case_id TEXT,
        nip TEXT,
        periode TEXT,
        komponen TEXT,
        nominal DOUBLE,
        created_at TEXT,
        created_by TEXT,
        source_file TEXT,
        source_row INTEGER,
        notes TEXT
    )''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS pengembalian_bank_batch (
        batch_id TEXT PRIMARY KEY,
        batch_name TEXT,
        created_at TEXT,
        created_by TEXT,
        status TEXT,
        metadata TEXT
    )''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS pengembalian_bank_detail (
        id TEXT PRIMARY KEY,
        batch_id TEXT,
        case_id TEXT,
        nip TEXT,
        periode TEXT,
        komponen TEXT,
        nominal DOUBLE,
        created_at TEXT,
        created_by TEXT,
        reference TEXT
    )''')

    conn.execute('''
    CREATE TABLE IF NOT EXISTS pengembalian_bank_result (
        id TEXT PRIMARY KEY,
        bank_batch_id TEXT,
        bank_detail_id TEXT,
        case_id TEXT,
        nip TEXT,
        nominal DOUBLE,
        status TEXT,
        reason TEXT,
        processed_at TEXT,
        processed_by TEXT
    )''')

    conn.commit()
    print('Migration 022 applied successfully')
finally:
    conn.close()
