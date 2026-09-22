from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "pembulatan_jobs.db")

app = FastAPI(title="EVKIN Pembulatan Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rounding_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            file_name TEXT,
            selected_columns TEXT,
            unit INTEGER,
            method TEXT,
            total REAL,
            initial REAL,
            correction REAL,
            final REAL,
            rows_json TEXT,
            summary_json TEXT,
            status TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def parse_numeric(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("Rp", "").replace(" ", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 and "," not in s:
        s = s.replace(".", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def round_value(raw: float, unit: float, method: str) -> float:
    q = raw / unit
    if method == "floor":
        return float(__import__('math').floor(q) * unit)
    if method == "ceil":
        return float(__import__('math').ceil(q) * unit)
    return float(round(q) * unit)


class ProcessRequest(BaseModel):
    rows: List[Dict[str, Any]]
    valueColumn: Optional[str] = None
    selectedColumns: Optional[List[str]] = None
    unit: int = 1000
    method: str = "nearest"
    fileName: Optional[str] = None


def build_result(rows: List[Dict[str, Any]], value_column: str, unit: int, method: str):
    result = []
    for index, row in enumerate(rows, start=1):
        original = round(parse_numeric(row.get(value_column, 0)))
        rounded = round(round_value(original, unit, method))
        result.append({
            "no": index,
            "raw": dict(row),
            "original": original,
            "rounded": rounded,
            "correction": 0,
            "final": rounded,
            "fraction": (original / unit) - __import__('math').floor(original / unit),
        })

    total = sum(x["original"] for x in result)
    initial = sum(x["rounded"] for x in result)
    residual = round((total - initial) * 100) / 100
    steps = round(residual / unit)

    if abs(residual - steps * unit) < 0.01 and result:
        if steps > 0:
            sorted_rows = sorted(result, key=lambda x: x["fraction"], reverse=True)
            for index, item in enumerate(sorted_rows):
                if index < steps:
                    item["correction"] += unit
            for offset in range(len(result), steps):
                result[offset % len(result)]["correction"] += unit
        elif steps < 0:
            n = abs(steps)
            sorted_rows = sorted(result, key=lambda x: x["fraction"])
            for index, item in enumerate(sorted_rows):
                if index < n:
                    item["correction"] -= unit
            for offset in range(len(result), n):
                result[offset % len(result)]["correction"] -= unit

    for item in result:
        item["final"] = item["rounded"] + item["correction"]

    final_total = sum(x["final"] for x in result)
    diff = round(total - final_total)
    if diff != 0 and result:
        result[-1]["correction"] += diff
        result[-1]["final"] += diff

    for item in result:
        item["original"] = round(item["original"])
        item["rounded"] = round(item["rounded"])
        item["correction"] = round(item["correction"])
        item["final"] = round(item["final"])

    return {
        "result": result,
        "total": total,
        "initial": initial,
        "correction": sum(x["correction"] for x in result),
        "final": sum(x["final"] for x in result),
    }


def save_job(file_name: Optional[str], selected_columns: List[str], unit: int, method: str, rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = conn.execute(
        """
        INSERT INTO rounding_jobs (
            created_at, file_name, selected_columns, unit, method,
            total, initial, correction, final, rows_json, summary_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            created_at,
            file_name,
            json.dumps(selected_columns, ensure_ascii=False),
            int(unit),
            method,
            float(summary["total"]),
            float(summary["initial"]),
            float(summary["correction"]),
            float(summary["final"]),
            json.dumps(rows, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
            "completed",
        ),
    )
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(job_id)


@app.get("/health")
def health():
    return {"status": "ok", "service": "EVKIN Pembulatan Backend", "port": 9101}


@app.get("/api/pembulatan/jobs/{job_id}")
def get_job(job_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM rounding_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Job pembulatan tidak ditemukan")

    return {
        "id": row["id"],
        "fileName": row["file_name"],
        "selectedColumns": json.loads(row["selected_columns"] or "[]"),
        "unit": row["unit"],
        "method": row["method"],
        "total": row["total"],
        "initial": row["initial"],
        "correction": row["correction"],
        "final": row["final"],
        "rows": json.loads(row["rows_json"] or "[]"),
        "summary": json.loads(row["summary_json"] or "{}"),
        "status": row["status"],
    }


@app.post("/api/pembulatan/process")
def process_pembulatan(request: ProcessRequest):
    if not request.rows:
        raise ValueError("Rows is empty")

    selected_columns = request.selectedColumns or []
    if not selected_columns and request.valueColumn:
        selected_columns = [request.valueColumn]
    if not selected_columns:
        raise ValueError("Pilih minimal satu kolom nominal")

    output_rows = [dict(row) for row in request.rows]
    summary = {
        "total": 0,
        "initial": 0,
        "correction": 0,
        "final": 0,
        "rows": output_rows,
    }

    for column in selected_columns:
        parsed = build_result(output_rows, column, request.unit, request.method)
        for item in parsed["result"]:
            row = output_rows[item["no"] - 1]
            row[f"{column}_Pembulatan_Awal"] = item["rounded"]
            row[f"{column}_Koreksi_Rekonsiliasi"] = item["correction"]
            row[f"{column}_Tukin_Final"] = item["final"]
            row[f"{column}_Status_Rekonsiliasi"] = "Sama" if abs(item["final"] - item["original"]) < 0.01 else "Dikoreksi"

        summary["total"] += parsed["total"]
        summary["initial"] += parsed["initial"]
        summary["correction"] += parsed["correction"]
        summary["final"] += parsed["final"]

    diff = round(summary["final"] - summary["total"])
    job_id = save_job(request.fileName, selected_columns, request.unit, request.method, output_rows, summary)
    return {
        "status": "ok",
        "jobId": job_id,
        "total": summary["total"],
        "initial": summary["initial"],
        "correction": summary["correction"],
        "final": summary["final"],
        "selisih": diff,
        "rows": output_rows,
        "selectedColumns": selected_columns,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9101)
