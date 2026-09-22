"""
Utility to load a CSV into DuckDB and perform basic schema / size checks.
Run: python loader.py /path/to/people.csv
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

try:
    from backend.schema_sync import create_table_from_relation, insert_relation_by_name
except ModuleNotFoundError:  # pragma: no cover - direct execution from backend/
    from schema_sync import create_table_from_relation, insert_relation_by_name


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python loader.py /full/path/to/file.csv')
        sys.exit(1)

    p = Path(sys.argv[1])
    if not p.exists():
        print('File not found:', p)
        sys.exit(2)

    con = duckdb.connect(database='hr.duckdb')
    size_mb = p.stat().st_size / (1024 * 1024)
    print(f'Loading {p} ({size_mb:.2f} MB)')

    if size_mb > 200:
        print('Large file detected, using pandas chunks to stream...')
        chunks = pd.read_csv(p, chunksize=100000)
        first = True
        total = 0
        for chunk in chunks:
            n = len(chunk)
            total += n
            print(f'Ingesting chunk with {n} rows (total {total})')
            con.register('temp_df', chunk)
            if first:
                create_table_from_relation(con, 'people', 'temp_df')
                first = False
            else:
                insert_relation_by_name(con, 'people', 'temp_df')
            con.unregister('temp_df')
        print('Done. Total rows:', total)
    else:
        csv_path = str(p).replace('\\', '/')
        con.execute('CREATE OR REPLACE TABLE people AS SELECT * FROM read_csv_auto(?)', [csv_path])
        n = con.execute('SELECT count(*) FROM people').fetchone()[0]
        print('Done. Rows:', n)

    print('Example: SELECT count(*) FROM people;')
    print(con.execute('SELECT count(*) FROM people').fetchall())
    con.close()
