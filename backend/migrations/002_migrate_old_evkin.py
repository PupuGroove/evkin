"""
Migration 002: migrate raw_import and hitung_harian from legacy SQLite evkin.db -> EVKIN_MASTER.duckdb
Supports dry-run (default) and --apply to perform writes.
Usage:
  python 002_migrate_old_evkin.py [--apply]

Dry-run will report counts, sample rows and duplicate keys.
When --apply is used this script will:
  - backup EVKIN_MASTER.duckdb to data/backup
  - copy raw_import -> absensi_raw (with conservative column mapping and generated ids)
  - copy hitung_harian -> absensi_hasil (best-effort mapping of fields)

The script is careful not to DROP or DELETE existing data; it appends and is idempotent if repeated (generates new ids each run).
"""
from pathlib import Path
import argparse
import sqlite3
import duckdb
import pandas as pd
import uuid
import shutil
import datetime
import sys


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

    # connect
    sconn = sqlite3.connect(str(sqlite_path))
    sconn.row_factory = sqlite3.Row
    dconn = duckdb.connect(str(duck_path))

    try:
        # REPORT counts
        tables = ['raw_import', 'hitung_harian']
        report = {}
        for t in tables:
            exists = table_exists_sqlite(sconn, t)
            cnt = 0
            sample = []
            dups = None
            if exists:
                try:
                    cnt = sconn.execute(f'SELECT COUNT(*) as c FROM "{t}"').fetchone()[0]
                except Exception as e:
                    cnt = 0
                try:
                    sample_rows = sconn.execute(f'SELECT * FROM "{t}" LIMIT 5').fetchall()
                    for r in sample_rows:
                        sample.append(dict(r))
                except Exception:
                    sample = []
                # duplicate analysis for raw_import: nip + tanggal
                if t == 'raw_import':
                    try:
                        dups = sconn.execute("SELECT NIP as nip, Tanggal as tanggal, COUNT(*) as c FROM raw_import GROUP BY NIP, Tanggal HAVING COUNT(*) > 1 ORDER BY c DESC LIMIT 10").fetchall()
                    except Exception:
                        dups = []
            report[t] = {'exists': exists, 'count': cnt, 'sample': sample, 'dups': [dict(x) for x in dups] if dups is not None else None}

        print('\n-- Source report (sqlite) --')
        for t, info in report.items():
            print(f"Table {t}: exists={info['exists']} count={fmt(info['count'])}")
            if info['dups']:
                print('  sample duplicates (nip,date,count):')
                for d in info['dups']:
                    print('   ', d.get('nip'), d.get('tanggal'), d.get('c'))
            if info['sample']:
                print('  sample row keys:', list(info['sample'][0].keys()))
        # show target counts
        print('\n-- Target report (duckdb) --')
        try:
            d_tables = [r[0] for r in dconn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
        except Exception:
            d_tables = []
        for t in ['absensi_raw', 'absensi_hasil']:
            if t in d_tables:
                try:
                    c = dconn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception:
                    c = 0
                print(f"Table {t}: count={fmt(c)}")
            else:
                print(f"Table {t}: (missing)")

        if not args.apply:
            print('\nDry-run complete. No data written. To apply changes re-run with --apply')
            return

        # APPLY mode: backup duckdb then copy
        ts = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'EVKIN_MASTER_pre_migrate_{ts}.duckdb'
        print('Backing up', duck_path, '->', backup_path)
        try:
            shutil.copy2(duck_path, backup_path)
            print('Backup created:', backup_path)
        except PermissionError as exc:
            print('Warning: could not create backup because file is in use: ', exc, file=sys.stderr)
            print('Proceeding without creating a full file backup. Ensure you have offline backups if needed.', file=sys.stderr)
        # create an import batch id for this apply so migrated rows can be traced
        batch_id = str(uuid.uuid4())
        print('Import batch id:', batch_id)

        # Migrate raw_import -> absensi_raw (idempotent, skip duplicates)
        if report['raw_import']['exists'] and report['raw_import']['count'] > 0:
            print('Migrating raw_import -> absensi_raw ...')
            df_raw = pd.read_sql_query('SELECT * FROM raw_import', sconn)
            # Normalize columns: attempt to map known source columns to target columns
            col_map = {}
            # source columns are case sensitive in sqlite; create lowercase map
            lower_cols = {c.lower(): c for c in df_raw.columns}
            def pick(cols):
                for c in cols:
                    if c.lower() in lower_cols:
                        return lower_cols[c.lower()]
                return None
            col_nip = pick(['nip'])
            col_tgl = pick(['tanggal','date','tgl'])
            col_masuk = pick(['jam masuk','jammasuk','jam_masuk','jam masuk'])
            col_pulang = pick(['jam pulang','jampulang','jam_pulang'])
            col_jenis = pick(['jenis absen','jenis','keterangan'])
            col_prov = pick(['provinsi'])
            # build target frame
            out = pd.DataFrame()
            out['id'] = [str(uuid.uuid4()) for _ in range(len(df_raw))]
            # tag with batch id so migrated rows are traceable
            out['import_batch_id'] = batch_id
            out['nip'] = df_raw[col_nip] if col_nip in df_raw.columns else df_raw.iloc[:,0]
            out['tanggal'] = pd.to_datetime(df_raw[col_tgl], dayfirst=True, errors='coerce').dt.date.astype(str)
            out['jam_masuk'] = df_raw[col_masuk] if col_masuk in df_raw.columns else None
            out['jam_pulang'] = df_raw[col_pulang] if col_pulang in df_raw.columns else None
            out['jenis_absen'] = df_raw[col_jenis] if col_jenis in df_raw.columns else None
            out['timezone_asal'] = df_raw[col_prov] if col_prov in df_raw.columns else None
            out['jam_masuk_wib'] = None
            out['jam_pulang_wib'] = None
            out['source_file'] = None
            out['created_at'] = pd.Timestamp.utcnow()
            # write to duckdb (append) but skip rows that already appear to exist
            dconn.register('tmp_raw', out)
            try:
                dconn.execute('CREATE TABLE IF NOT EXISTS absensi_raw AS SELECT * FROM tmp_raw LIMIT 0')
            except Exception:
                pass
            # compute counts before
            try:
                before_cnt = dconn.execute("SELECT COUNT(*) FROM absensi_raw").fetchone()[0]
            except Exception:
                before_cnt = 0
            # insert only rows that don't match on (nip, tanggal, jam_masuk, jam_pulang)
            insert_sql = (
                "INSERT INTO absensi_raw "
                "SELECT tmp.* FROM tmp_raw AS tmp "
                "LEFT JOIN absensi_raw AS a ON a.nip = tmp.nip AND a.tanggal = tmp.tanggal "
                "AND (a.jam_masuk = tmp.jam_masuk OR (a.jam_masuk IS NULL AND tmp.jam_masuk IS NULL)) "
                "AND (a.jam_pulang = tmp.jam_pulang OR (a.jam_pulang IS NULL AND tmp.jam_pulang IS NULL)) "
                "WHERE a.id IS NULL"
            )
            dconn.execute(insert_sql)
            try:
                dconn.unregister('tmp_raw')
            except Exception:
                pass
            # compute inserted
            try:
                after_cnt = dconn.execute("SELECT COUNT(*) FROM absensi_raw").fetchone()[0]
                inserted = after_cnt - before_cnt
            except Exception:
                inserted = None
            if inserted is None:
                print('  Wrote (unknown) rows to absensi_raw')
            else:
                print('  Appended', fmt(inserted), 'rows to absensi_raw')
        else:
            print('No raw_import data to migrate')

        # Migrate hitung_harian -> absensi_hasil (best-effort)
        if report['hitung_harian']['exists'] and report['hitung_harian']['count'] > 0:
            print('Migrating hitung_harian -> absensi_hasil ...')
            df_h = pd.read_sql_query('SELECT * FROM hitung_harian', sconn)
            lower_cols = {c.lower(): c for c in df_h.columns}
            def pick_h(cols):
                for c in cols:
                    if c.lower() in lower_cols:
                        return lower_cols[c.lower()]
                return None
            nip = pick_h(['nip'])
            tgl = pick_h(['tanggal','tgl','date'])
            masuk = pick_h(['jamMasuk','jammasuk','jam_masuk','masuk'])
            pulang = pick_h(['jamPulang','jampulang','jam_pulang','pulang'])
            durmin = pick_h(['durasiMin','durasi_min','durasimin'])
            late = pick_h(['_latemin','latemin'])
            early = pick_h(['_earlymin','earlymin'])
            total_pct = pick_h(['totalHarian','totalharian','total_harian'])

            out2 = pd.DataFrame()
            out2['id'] = [str(uuid.uuid4()) for _ in range(len(df_h))]
            out2['absensi_raw_id'] = None
            out2['nip'] = df_h[nip] if nip in df_h.columns else df_h.iloc[:,0]
            out2['tanggal'] = pd.to_datetime(df_h[tgl], errors='coerce').dt.date.astype(str) if tgl in df_h.columns else None
            out2['jam_masuk'] = df_h[masuk] if masuk in df_h.columns else None
            out2['jam_pulang'] = df_h[pulang] if pulang in df_h.columns else None
            # total_jam_kerja from durasiMin (minutes -> hours)
            if durmin in df_h.columns:
                out2['total_jam_kerja'] = pd.to_numeric(df_h[durmin], errors='coerce') / 60.0
            else:
                out2['total_jam_kerja'] = None
            out2['keterlambatan_menit'] = df_h[late] if late in df_h.columns else None
            out2['pulang_cepat_menit'] = df_h[early] if early in df_h.columns else None
            out2['status_absen'] = None
            out2['persen_potongan'] = pd.to_numeric(df_h[total_pct], errors='coerce') if total_pct in df_h.columns else None
            out2['nominal_potongan'] = None
            out2['keterangan'] = None
            out2['rule_version'] = None
            out2['created_at'] = pd.Timestamp.utcnow()
            out2['updated_at'] = None

            dconn.register('tmp_h', out2)
            try:
                dconn.execute('CREATE TABLE IF NOT EXISTS absensi_hasil AS SELECT * FROM tmp_h LIMIT 0')
            except Exception:
                pass
            dconn.execute('INSERT INTO absensi_hasil SELECT * FROM tmp_h')
            try:
                dconn.unregister('tmp_h')
            except Exception:
                pass
            print('  Wrote', fmt(len(out2)), 'rows to absensi_hasil')
        else:
            print('No hitung_harian data to migrate')

        print('\nMigration APPLY completed successfully')

    finally:
        sconn.close()
        dconn.close()


if __name__ == '__main__':
    main()
