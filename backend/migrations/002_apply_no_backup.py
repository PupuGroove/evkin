"""
Apply migration without attempting file-level backup. Use when EVKIN_MASTER.duckdb is locked and a file copy cannot be made.
Usage:
  python 002_apply_no_backup.py
This will append raw_import->absensi_raw and hitung_harian->absensi_hasil directly into the DuckDB file.
"""
from pathlib import Path
import sqlite3
import duckdb
import pandas as pd
import uuid
import sys

repo_root = Path(__file__).resolve().parent.parent
sqlite_path = repo_root / 'evkin.db'
duck_path = repo_root / 'data' / 'EVKIN_MASTER.duckdb'

if not sqlite_path.exists():
    print('Legacy sqlite database not found at', sqlite_path)
    sys.exit(1)
if not duck_path.exists():
    print('Target DuckDB not found at', duck_path)
    sys.exit(1)

print('Applying migration WITHOUT file backup')
print('Legacy (sqlite):', sqlite_path)
print('Target (duckdb):', duck_path)

sconn = sqlite3.connect(str(sqlite_path))
sconn.row_factory = sqlite3.Row
dconn = duckdb.connect(str(duck_path))

try:
    # raw_import
    try:
        cnt_raw = sconn.execute('SELECT COUNT(*) FROM raw_import').fetchone()[0]
    except Exception:
        cnt_raw = 0
    if cnt_raw > 0:
        print('Migrating raw_import -> absensi_raw (rows:', cnt_raw, ')')
        df_raw = pd.read_sql_query('SELECT * FROM raw_import', sconn)
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
        out = pd.DataFrame()
        out['id'] = [str(uuid.uuid4()) for _ in range(len(df_raw))]
        out['import_batch_id'] = None
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
        # write
        dconn.register('tmp_raw', out)
        try:
            dconn.execute('CREATE TABLE IF NOT EXISTS absensi_raw AS SELECT * FROM tmp_raw LIMIT 0')
        except Exception:
            pass
        dconn.execute('INSERT INTO absensi_raw SELECT * FROM tmp_raw')
        try:
            dconn.unregister('tmp_raw')
        except Exception:
            pass
        print('  Appended', f"{len(out):,}", 'rows to absensi_raw')
    else:
        print('No raw_import data found to migrate')

    # hitung_harian
    try:
        cnt_h = sconn.execute('SELECT COUNT(*) FROM hitung_harian').fetchone()[0]
    except Exception:
        cnt_h = 0
    if cnt_h > 0:
        print('Migrating hitung_harian -> absensi_hasil (rows:', cnt_h, ')')
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
        print('  Appended', f"{len(out2):,}", 'rows to absensi_hasil')
    else:
        print('No hitung_harian data found to migrate')

    # final counts
    try:
        c1 = dconn.execute("SELECT COUNT(*) FROM absensi_raw").fetchone()[0]
    except Exception:
        c1 = 0
    try:
        c2 = dconn.execute("SELECT COUNT(*) FROM absensi_hasil").fetchone()[0]
    except Exception:
        c2 = 0
    print('\nPost-migration counts:')
    print(' absensi_raw:', f"{c1:,}")
    print(' absensi_hasil:', f"{c2:,}")

finally:
    sconn.close()
    dconn.close()
