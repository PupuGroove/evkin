FastAPI + DuckDB backend (minimal)

Requirements
- Python 3.9+
- Install from requirements.txt: pip install -r requirements.txt

Quickstart
1. Create and activate a virtualenv (recommended):
   python -m venv .venv
   .\.venv\Scripts\activate
2. Install dependencies:
   pip install -r requirements.txt
3. Load your CSV into DuckDB using the loader utility:
   python loader.py C:\full\path\to\people.csv
   (for large CSVs the loader streams with pandas chunks)
4. Start the API server:
   uvicorn main:app --reload --host 127.0.0.1 --port 8000

Endpoints
- GET /health -> health check
- GET /people?offset=0&limit=100&q=search -> paginated results (q is case-insensitive search on name)
- POST /load-csv {"path": "C:/full/path/to/file.csv"} -> load CSV into DuckDB (overwrites table)

Notes
- DuckDB is an analytical DB that stores data on-disk and is fast for OLAP queries.
- For concurrency or multi-user scenarios, consider Postgres as an alternative.
- Optionally add a small sync mechanism if you want client-side edits reconciled back to the DB.

---

**Copyright © Dio Fajrul Iman**
