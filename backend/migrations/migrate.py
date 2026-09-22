"""
Simple migration runner: executes numbered migration scripts in this folder in filename-sorted order.
Run: python migrate.py
"""
import subprocess
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent

def find_migrations():
    files = [p for p in MIGRATIONS_DIR.iterdir() if p.is_file() and p.name.split('_')[0].isdigit() and p.suffix == '.py']
    files_sorted = sorted(files, key=lambda p: p.name)
    return files_sorted


def run_migration(path: Path):
    print(f"Running migration: {path.name}")
    res = subprocess.run([sys.executable, str(path)], check=False)
    if res.returncode != 0:
        raise SystemExit(f"Migration {path.name} failed with exit code {res.returncode}")


def main():
    migrations = find_migrations()
    if not migrations:
        print('No migrations found')
        return
    for m in migrations:
        run_migration(m)
    print('All migrations executed')

if __name__ == '__main__':
    main()
