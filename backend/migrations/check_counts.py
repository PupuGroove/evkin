import duckdb, pathlib, sys
p = pathlib.Path(r'C:\Users\USER\Documents\EVKIN_ABSENSI_v1.5 update terbaru\EVKIN_ABSENSI_v1.5 diocode\backend\data\EVKIN_MASTER.duckdb')
print('DB path:', p)
print('Exists:', p.exists())
if not p.exists():
    sys.exit(0)
con = duckdb.connect(str(p), read_only=True)
for t in ['absensi_raw','absensi_hasil','import_batch','audit_log']:
    try:
        c = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except Exception as e:
        c = f'ERROR: {e}'
    print(f'{t}: {c}')
con.close()
