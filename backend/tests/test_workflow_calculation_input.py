import sqlite3

import duckdb
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import evkin_export_api as api


@pytest.fixture
def workflow_db(tmp_path, monkeypatch):
    path = str(tmp_path / "calculation-input.duckdb")
    monkeypatch.setattr(api, "DUCKDB_PATH", path)
    monkeypatch.setattr(api, "get_connection", lambda: sqlite3.connect(":memory:"))
    if api._workflow_read_base is not None:
        api._workflow_read_base.close()
        api._workflow_read_base = None
        api._workflow_read_path = None
    api.ensure_duckdb_master_schema()
    yield path
    if api._workflow_read_base is not None:
        api._workflow_read_base.close()
        api._workflow_read_base = None
        api._workflow_read_path = None


def raw_rows(count):
    return [
        {
            "NIP": f"{index:018d}", "Nama": f"Pegawai {index}",
            "Tanggal": f"{index % 28 + 1:02d}/08/2026",
            "Jam Masuk": "07:30", "Jam Pulang": "16:00",
        }
        for index in range(count)
    ]


def persist_import(rows, workflow_id="WORKFLOW-A", expected=None):
    expected = len(rows) if expected is None else expected
    api.sync_workflow_table({
        "source": "raw_import", "rows": rows, "replace": True,
        "workflow_id": workflow_id, "periode": "2026-08",
    })
    api.sync_workflow_table({
        "source": "processed_data", "rows": [], "replace": True,
        "workflow_id": workflow_id, "periode": "2026-08",
    })
    api.sync_workflow_table({
        "source": "config", "replace": True,
        "workflow_id": workflow_id, "periode": "2026-08", "rows": [{
            "saved": True,
            "_workflow": {
                "workflow_id": workflow_id, "month": "2026-08",
                "importStatus": "COMPLETE",
                "importStats": {
                    "totalRaw": expected, "totalRecord": expected,
                    "months": ["2026-08"],
                },
            },
        }],
    })


def test_ten_rows_are_complete_without_workflow_record_duplication(workflow_db):
    persist_import(raw_rows(10))
    state = api.get_workflow_state()
    assert state["meta"]["workflow_id"] == "WORKFLOW-A"
    assert state["meta"]["total_row_counts"]["raw_import"] == 10
    result = api.get_workflow_calculation_input("WORKFLOW-A", 1, 500)
    assert result["import_status"] == "COMPLETE"
    assert result["persisted_source_rows"] == result["expected_source_rows"] == 10
    assert len(result["rows"]) == 10
    with duckdb.connect(workflow_db) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info('workflow_records')").fetchall()]
        assert columns == ["_empty"]
        assert connection.execute("SELECT count(*) FROM workflow_records").fetchone()[0] == 0


def test_calculation_input_pages_all_rows_above_ui_limit(workflow_db):
    rows = raw_rows(1201)
    api.sync_workflow_table({
        "source": "raw_import", "rows": rows[:700], "replace": True,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08",
    })
    api.sync_workflow_table({
        "source": "raw_import", "rows": rows[700:], "replace": False,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08",
    })
    api.sync_workflow_table({
        "source": "processed_data", "rows": [], "replace": True,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08",
    })
    api.sync_workflow_table({
        "source": "config", "replace": True,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08", "rows": [{
            "saved": True, "_workflow": {
                "workflow_id": "WORKFLOW-A", "month": "2026-08",
                "importStatus": "COMPLETE",
                "importStats": {"totalRaw": 1201, "totalRecord": 1201, "months": ["2026-08"]},
            },
        }],
    })
    pages = [api.get_workflow_calculation_input("WORKFLOW-A", page, 500) for page in (1, 2, 3)]
    assert [len(item["rows"]) for item in pages] == [500, 500, 201]
    assert sum(len(item["rows"]) for item in pages) == 1201
    assert all(item["total"] == 1201 for item in pages)
    ui = api.get_workflow_data("raw_import", 1, 1000, None, "default")
    assert ui["page_size"] == 500 and len(ui["rows"]) == 500


def test_raw_import_chunks_keep_stable_text_types_for_blank_and_mixed_cells(workflow_db):
    first = raw_rows(2)
    first[0]["Kolom Campuran"] = 123
    first[1]["Kolom Campuran"] = 456
    first[0]["Tanggal"] = 46234
    first[1]["Tanggal"] = 46235
    second = raw_rows(2)
    second[0]["Kolom Campuran"] = ""
    second[1]["Kolom Campuran"] = "KETERANGAN"

    api.sync_workflow_table({
        "source": "raw_import", "rows": first, "replace": True,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08",
    })
    appended = api.sync_workflow_table({
        "source": "raw_import", "rows": second, "replace": False,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08",
    })
    assert appended["total_rows"] == 4
    api.sync_workflow_table({
        "source": "config", "replace": True,
        "workflow_id": "WORKFLOW-A", "periode": "2026-08", "rows": [{
            "saved": True, "_workflow": {
                "workflow_id": "WORKFLOW-A", "month": "2026-08",
                "importStatus": "COMPLETE",
                "importStats": {"totalRaw": 4, "totalRecord": 4, "months": ["2026-08"]},
            },
        }],
    })

    with duckdb.connect(workflow_db) as connection:
        types = {row[1]: row[2] for row in connection.execute(
            "PRAGMA table_info('raw_import')"
        ).fetchall()}
        assert set(types.values()) == {"VARCHAR"}
        values = connection.execute(
            'SELECT "Kolom Campuran" FROM raw_import ORDER BY rowid'
        ).fetchall()
    assert values == [("123",), ("456",), ("",), ("KETERANGAN",)]
    hydrated = api.get_workflow_calculation_input("WORKFLOW-A", 1, 500)
    assert hydrated["persisted_source_rows"] == hydrated["expected_source_rows"] == 4
    assert len(hydrated["rows"]) == 4


def test_calculation_input_rejects_other_workflow_and_incomplete_import(workflow_db):
    persist_import(raw_rows(10), expected=10)
    with pytest.raises(HTTPException) as mismatch:
        api.get_workflow_calculation_input("WORKFLOW-B", 1, 500)
    assert mismatch.value.status_code == 409
    assert mismatch.value.detail["code"] == "WORKFLOW_SCOPE_MISMATCH"

    persist_import(raw_rows(9), expected=10)
    with pytest.raises(HTTPException) as incomplete:
        api.get_workflow_calculation_input("WORKFLOW-A", 1, 500)
    assert incomplete.value.status_code == 409
    assert incomplete.value.detail["code"] == "IMPORT_INCOMPLETE"
    assert incomplete.value.detail["persisted_source_rows"] == 9


def test_chunk_schema_error_returns_safe_stage_message(workflow_db, monkeypatch):
    monkeypatch.setenv("EVKIN_API_KEY", "test-key")
    client = TestClient(api.app, raise_server_exceptions=False)
    headers = {"X-EVKIN-API-Key": "test-key"}
    first = client.post("/api/workflow/sync-table", headers=headers, json={
        "source": "raw_import", "replace": True, "workflow_id": "default",
        "rows": [{"NIP": "1", "Tanggal": "01/08/2026", "Opsional": "X"}],
    })
    assert first.status_code == 200
    failed = client.post("/api/workflow/sync-table", headers=headers, json={
        "source": "raw_import", "replace": False, "workflow_id": "default",
        "rows": [{"NIP": "2", "Tanggal": "02/08/2026"}],
    })
    assert failed.status_code == 409
    assert failed.json()["detail"] == {
        "code": "WORKFLOW_PERSISTENCE_SCHEMA_MISMATCH",
        "message": "Penyimpanan impor gagal karena struktur antar-batch tidak konsisten.",
        "stage": "IMPORT_PERSISTENCE",
    }
