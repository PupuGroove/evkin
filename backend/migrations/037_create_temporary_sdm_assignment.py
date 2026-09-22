"""Migration 037: effective-month temporary SDM assignments from one-sheet imports."""
from pathlib import Path
import importlib
import os

import duckdb

ensure_shared_master_schema = importlib.import_module(
    "backend.migrations.035_create_shared_sdm_master"
).ensure_shared_master_schema


def main() -> None:
    db_path = os.environ.get("EVKIN_DUCKDB_PATH") or str(
        Path(__file__).resolve().parents[1] / "data" / "EVKIN_MASTER.duckdb"
    )
    with duckdb.connect(db_path) as conn:
        ensure_shared_master_schema(conn)
    print(f"Migration 037 applied: temporary SDM assignments at {db_path}")


if __name__ == "__main__":
    main()
