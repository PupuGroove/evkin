"""
Migration 004: migrate SDM-related tables from legacy SQLite -> EVKIN_MASTER.duckdb
Supports dry-run (default) and --apply. On --apply creates a file-level backup, inserts data and records import_batch + audit_log.
Dedupe behavior: when source rows contain 'nip' (case-insensitive) and a date-like column (tanggal/tgl/date) we'll skip inserting rows that match on (nip, tanggal). For simple master records with 'nip' only, skip if nip already exists.
"""
from pathlib import Path
import argparse
import sqlite3
import duckdb
import pandas as pd
import uuid
import shutil
import datetime
import json
import sys

SOURCE_TABLES = ['master_data', 'rekap_sdm']  # guessed SDM-related tables; will detect existence


def fmt(n):
    return f"{n:,}"


def table_exists_sqlite(conn, t):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,))
    return cur.fetchone() is not None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run)')
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sqlite_path = repo_root / 'evkin.db'
    duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'
    backup_dir = repo_root / 'data' / 'backup'
    backup_dir.mkdir(parents=True, exist_ok=True)

    if not sqlite_path.exists():
        print('Legacy sqlite database not found at', sqlite_path)
        sys.exit(1)
    if not duck_path.exists():
        print('Target DuckDB not found at', duck_path)
        print('Please run 001_create_master_schema.py first')
        sys.exit(1)

    print('Legacy (sqlite):', sqlite_path)
    print('Target (duckdb):', duck_path)
    print('Mode:', 'APPLY' if args.apply else 'DRY-RUN')

    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row
    dconn = duckdb.connect(str(duck_path))

    try:
        report = {}
        for t in SOURCE_TABLES:
            exists = table_exists_sqlite(sconn, t)
            cnt = 0
            sample = []
            if exists:
                try:
                    cnt = sconn.execute(f"SELECT COUNT(*) as c FROM '{t}'").fetchone()[0]
                except Exception:
                    cnt = 0
                try:
                    sample_rows = sconn.execute(f"SELECT * FROM '{t}' LIMIT 5").fetchall()
                    for r in sample_rows:
                        sample.append(dict(r))
                except Exception:
                    sample = []
            report[t] = {'exists': exists, 'count': cnt, 'sample': sample}

        print('\n-- SDM Source report (sqlite) --')
        for t, info in report.items():
            print(f"Table {t}: exists={info['exists']} count={fmt(info['count'])}")
            if info['sample']:
                print('  sample row keys:', list(info['sample'][0].keys()))

        if not args.apply:
            print('\nDry-run complete. No data written. To apply changes re-run with --apply')
            return

        # APPLY: backup
        ts = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'EVKIN_MASTER_pre_migrate_004_{ts}.duckdb'
        print('Backing up', duck_path, '->', backup_path)
        shutil.copy2(duck_path, backup_path)

        batch_id = str(uuid.uuid4())
        print('Import batch id:', batch_id)

        # process each source table
        for t in SOURCE_TABLES:
            if not report[t]['exists'] or report[t]['count'] == 0:
                print('Skipping', t, '(no data)')
                continue
            print('Migrating', t, '...')
            df = pd.read_sql_query(f"SELECT * FROM '{t}'", sconn)
            # simple mapping: attempt to keep column names; normalize casing
            df.columns = [c.strip() for c in df.columns]
            # add import_batch_id and id if not present
            if 'id' not in df.columns:
                df.insert(0, 'id', [str(uuid.uuid4()) for _ in range(len(df))])
            df['import_batch_id'] = batch_id

            # dedupe rules: if df has nip and tanggal-like column, avoid inserting rows that match existing (nip,tanggal)
            lower_cols = {c.lower(): c for c in df.columns}
            nip_col = lower_cols.get('nip')
            tgl_col = None
            for cand in ('tanggal','tgl','date'):
                if cand in lower_cols:
                    tgl_col = lower_cols[cand]
                    break

            target_table = 'master_sdm'
            # register tmp
            dconn.register('tmp_src', df)
            try:
                dconn.execute(f"CREATE TABLE IF NOT EXISTS {target_table} AS SELECT * FROM tmp_src LIMIT 0")
            except Exception:
                pass
            if nip_col and tgl_col:
                # skip rows that match on nip+tanggal
                insert_sql = (
                    f"INSERT INTO {target_table} SELECT tmp.* FROM tmp_src tmp "
                    f"LEFT JOIN {target_table} t ON t.nip = tmp.\"{nip_col}\" AND t.tanggal = tmp.\"{tgl_col}\" WHERE t.id IS NULL"
                )
            elif nip_col:
                insert_sql = (
                    f"INSERT INTO {target_table} SELECT tmp.* FROM tmp_src tmp "
                    f"LEFT JOIN {target_table} t ON t.nip = tmp.\"{nip_col}\" WHERE t.id IS NULL"
                )
            else:
                # no key column detected, append all rows but user should verify
                insert_sql = f"INSERT INTO {target_table} SELECT * FROM tmp_src"

            dconn.execute(insert_sql)
            try:
                dconn.unregister('tmp_src')
            except Exception:
                pass
            print('  Migrated', fmt(len(df)), 'rows into', target_table)

        # insert import_batch and audit_log
        try:
            # import_batch
            cols = dconn.execute("PRAGMA table_info('import_batch')").fetchall()
            names = [r[1] for r in cols]
            ib = {}
            if 'id' in names: ib['id'] = batch_id
            if 'created_at' in names: ib['created_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            if 'source' in names: ib['source'] = 'legacy_sqlite: evkin.db (SDM)'
            if ib:
                cols_sql = ', '.join(ib.keys())
                vals = tuple(ib.values())
                placeholders = ', '.join(['?']*len(ib))
                dconn.execute(f"INSERT INTO import_batch ({cols_sql}) VALUES ({placeholders})", vals)
            # audit_log
            cols_a = dconn.execute("PRAGMA table_info('audit_log')").fetchall()
            anames = [r[1] for r in cols_a]
            al = {}
            aid = str(uuid.uuid4())
            if 'id' in anames: al['id'] = aid
            if 'created_at' in anames: al['created_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            if 'action' in anames: al['action'] = 'migration_apply'
            if 'table_name' in anames: al['table_name'] = ','.join(SOURCE_TABLES)
            if 'details' in anames: al['details'] = json.dumps({'batch_id': batch_id, 'tables': SOURCE_TABLES})
            if 'user' in anames: al['user'] = 'system:migration_004'
            if al:
                cols_sql = ', '.join(al.keys())
                vals = tuple(al.values())
                placeholders = ', '.join(['?']*len(al))
                dconn.execute(f"INSERT INTO audit_log ({cols_sql}) VALUES ({placeholders})", vals)
            print('Recorded import_batch and audit_log for SDM migration')
        except Exception as e:
            print('Warning: failed to record import_batch/audit_log:', e)

    finally:
        sconn.close()
        dconn.close()


if __name__ == '__main__':
    main()
