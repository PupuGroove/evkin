"""
Test script to compare Python (compute_harian_core) vs DuckDB (compute_harian_duckdb) outputs
Run: python -m backend.tests.compare_compute
"""
import tempfile
import os
import shutil
import sqlite3
import pandas as pd
import duckdb

# Import module via package path (ensure backend is importable)
import importlib.util
spec = importlib.util.spec_from_file_location('evkin_export_api', os.path.join(os.path.dirname(__file__), '..', 'evkin_export_api.py'))
evkin_export_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evkin_export_api)

SAMPLE_CSV = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'data', 'contoh_absensi.csv'))


def setup_temp_dbs():
    tmpdir = tempfile.mkdtemp(prefix='evkin_test_')
    db_path = os.path.join(tmpdir, 'evkin_test.db')
    duck_path = os.path.join(tmpdir, 'evkin_test.duckdb')
    return tmpdir, db_path, duck_path


def load_csv_to_sqlite(db_path):
    df = pd.read_csv(SAMPLE_CSV, dayfirst=True)
    conn = sqlite3.connect(db_path)
    try:
        df.to_sql('raw_import', conn, if_exists='replace', index=False)
    finally:
        conn.close()


def load_csv_to_duck(duck_path):
    df = pd.read_csv(SAMPLE_CSV, dayfirst=True)
    dconn = duckdb.connect(duck_path)
    try:
        dconn.register('tmp', df)
        dconn.execute('CREATE OR REPLACE TABLE raw_import AS SELECT * FROM tmp')
    finally:
        dconn.close()


def run_compare():
    tmpdir, db_path, duck_path = setup_temp_dbs()
    print('Temp dir:', tmpdir)
    # monkeypatch paths in module
    evkin_export_api.DB_PATH = db_path
    evkin_export_api.DUCKDB_PATH = duck_path

    # load sample csv into both DBs
    load_csv_to_sqlite(db_path)
    load_csv_to_duck(duck_path)

    # ensure jobs table
    conn = evkin_export_api.get_connection()
    try:
        evkin_export_api.ensure_jobs_table(conn)
    finally:
        conn.close()

    # run python compute (writes to sqlite)
    print('Running compute_harian_core (python)...')
    rows_py = evkin_export_api.compute_harian_core('2026-08', time_mode='original', unit=None, job_id=None)
    print('Rows written (python):', rows_py)

    # run duckdb compute (writes to duckdb)
    print('Running compute_harian_duckdb (duckdb)...')
    rows_ddb = evkin_export_api.compute_harian_duckdb(job_id='test', bulan='2026-08', time_mode='original', unit=None, chunk_size=1000)
    print('Rows written (duckdb):', rows_ddb)

    # read outputs
    conn = sqlite3.connect(db_path)
    try:
        df_py = pd.read_sql_query('SELECT * FROM hitung_harian', conn)
    except Exception:
        df_py = pd.DataFrame()
    finally:
        conn.close()

    dconn = duckdb.connect(duck_path)
    try:
        try:
            df_ddb = dconn.execute('SELECT * FROM hitung_harian').fetchdf()
        except Exception:
            df_ddb = pd.DataFrame()
    finally:
        dconn.close()

    print('Python rows:', len(df_py), 'DuckDB rows:', len(df_ddb))

    # quick compare on key columns
    if not df_py.empty and not df_ddb.empty:
        key = ['nip', 'tanggal']
        merged = df_py.merge(df_ddb, on=key, suffixes=('_py', '_ddb'), how='outer', indicator=True)
        diffs = []
        for col in ['totalHarian', 'potKeterlambatan', 'potPulangCepat', 'potDurasi', 'potTidakLengkap']:
            col_py = col + '_py'
            col_ddb = col + '_ddb'
            if col_py in merged.columns and col_ddb in merged.columns:
                m = merged[merged[col_py].fillna(0) != merged[col_ddb].fillna(0)]
                if not m.empty:
                    diffs.append((col, len(m)))
        print('Differences:', diffs)
    else:
        print('One of the outputs is empty; cannot compare')

    # cleanup
    print('Cleaning up temp dir:', tmpdir)
    shutil.rmtree(tmpdir)


if __name__ == '__main__':
    run_compare()
