"""
Inspect sqlite schema for backend/evkin.db and print PRAGMA table_info for each table.
"""
import sqlite3
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sqlite_path = repo_root / 'evkin.db'
if not sqlite_path.exists():
    print('evkin.db not found at', sqlite_path)
    raise SystemExit(1)

conn = sqlite3.connect(str(sqlite_path))
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
rows = cur.fetchall()
for (t,) in rows:
    print('\nTABLE:', t)
    try:
        cols = conn.execute(f"PRAGMA table_info('{t}')").fetchall()
        for c in cols:
            # cid,name,type,notnull,dflt_value,pk
            print('  -', c[1], c[2], 'pk' if c[5] else '')
    except Exception as e:
        print('  (error reading columns)', e)

conn.close()
