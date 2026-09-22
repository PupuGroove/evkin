"""Additive, idempotent optional SKP/Final snapshot schema."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.final_tukin import migrate

def main(db_path=None):
    migrate(db_path or os.environ.get('EVKIN_DUCKDB_PATH') or str(Path(__file__).resolve().parents[1]/'data'/'EVKIN_MASTER.duckdb'))

if __name__=='__main__': main()
