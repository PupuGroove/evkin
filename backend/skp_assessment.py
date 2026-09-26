"""Monthly SKP assessment, documentation, review, and approval workflow."""
from __future__ import annotations

from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
import importlib
import io
import json
import math
from pathlib import Path
import re
import threading
import uuid
from typing import Any, Callable, Mapping, Optional

import duckdb
from backend.lazy_imports import lazy_module

pd = lazy_module("pandas")
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse


ensure_schema = importlib.import_module(
    "backend.migrations.036_create_skp_assessment_workflow"
).ensure_skp_assessment_schema
ensure_indicator_schema = importlib.import_module(
    "backend.migrations.037_create_skp_indicator_governance"
).ensure_skp_indicator_governance_schema
ensure_deceased_schema = importlib.import_module(
    "backend.migrations.038_create_deceased_sdm_lifecycle"
).ensure_deceased_sdm_schema
ensure_condition_schema = importlib.import_module(
    "backend.migrations.039_create_skp_condition_decisions"
).ensure_skp_condition_decision_schema
ensure_third_missing_unpaid = importlib.import_module(
    "backend.migrations.041_enforce_third_missing_skp_unpaid"
).ensure_third_missing_skp_unpaid
ensure_operational_schema = importlib.import_module(
    "backend.migrations.049_create_skp_operational_workflow"
).ensure_skp_operational_schema

VALID_PREDICATES = {
    "SANGAT BAIK": 0.0,
    "BAIK": 0.0,
    "BUTUH PERBAIKAN": 5.0,
    "KURANG": 10.0,
    "SANGAT KURANG": 15.0,
}
INDICATOR_STATUSES = {"MENCAPAI", "KURANG", "TIDAK_ADA", "BELUM_DINILAI"}
REVIEW_STATUSES = {"PENDING_REVIEW", "RECOMMENDED", "RETURNED", "APPROVED", "FINAL_IMPORTED"}
_LOCK = threading.Lock()
_READY: set[str] = set()
SKP_EXPORT_SHEETS = {
    "summary": "Rekap Tahunan",
    "detail": "Detail Bulanan",
    "meetings": "Keputusan Rapat",
    "exceptions": "Pengecualian",
    "conditions": "Kondisi dan Hukdis",
    "configs": "Versi Konfigurasi",
}
_EXPORT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="skp-export")
_EXPORT_JOBS: dict[str, dict[str, Any]] = {}
_EXPORT_JOBS_LOCK = threading.Lock()

ALIASES = {
    "nip": ("nip", "nipbaru", "nomorindukpegawai"),
    "assessment_period": ("periode", "periodepenilaian", "bulan", "assessmentperiod"),
    "nama": ("nama", "namapegawai", "namasdm"),
    "penilai": ("penilai", "namapenilai", "atasanpenilai"),
    "jabatan": ("jabatan", "namajabatan"),
    "source_predicate": (
        "predikatkinerjaperiodik", "predikat", "nilaiskp", "predikatskp", "tnekin",
    ),
    "report_status": ("tidakbuatskp", "statuslaporanskp", "statusskp"),
    "hek_status": ("hek", "hariefektifkerja", "statushek"),
    "verkom_status": ("verkom", "verifikasikomitmen", "statusverkom"),
    "graduasi_status": ("graduasi", "statusgraduasi"),
    "p2k2_status": ("p2k2", "statusp2k2"),
    "recommendation_reason": ("alasan", "alasannilai", "alasanklasifikasi", "keterangan"),
    "evidence_ref": ("eviden", "bukti", "referensieviden", "nomordokumen"),
    "pokja_notes": ("catatanpokja", "catatanrekomendasipokja", "catatanindikator"),
}

for _code in ("hek", "verkom", "graduasi", "p2k2"):
    ALIASES[f"{_code}_target"] = (
        f"target{_code}", f"{_code}target", f"targetcapaian{_code}",
    )
    ALIASES[f"{_code}_actual"] = (
        f"realisasi{_code}", f"capaian{_code}", f"aktual{_code}", f"{_code}realisasi",
    )
    ALIASES[f"{_code}_pokja_recommendation"] = (
        f"rekomendasipokja{_code}", f"rekomendasi{_code}", f"pokja{_code}",
    )


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _text(value).lower())


def _mapping(columns) -> dict[str, str]:
    cleaned = {_header(column): column for column in columns}
    result = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                result[field] = cleaned[alias]
                break
    return result


def _period(value: Any) -> str:
    result = _text(value)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", result):
        raise ValueError("Periode penilaian harus berformat YYYY-MM")
    return result


def _source_period(value: Any, fallback_year: str) -> str:
    raw = _text(value)
    if not raw:
        return ""
    match = re.search(r"(20\d{2})[-/](0?[1-9]|1[0-2])", raw)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    months = {
        "JANUARI": 1, "FEBRUARI": 2, "MARET": 3, "APRIL": 4, "MEI": 5, "JUNI": 6,
        "JULI": 7, "AGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10, "NOVEMBER": 11, "DESEMBER": 12,
    }
    upper = _predicate(raw)
    for name, month in months.items():
        if name in upper:
            year_match = re.search(r"20\d{2}", raw)
            return f"{year_match.group(0) if year_match else fallback_year}-{month:02d}"
    return raw


def _predicate(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).upper()


def _number(value: Any) -> Optional[float]:
    if value is None or _text(value) == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raw = _text(value).replace("%", "").replace(" ", "")
    if raw.count(",") == 1 and raw.count(".") >= 1:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _indicator(value: Any) -> str:
    raw = _predicate(value).replace("-", "_").replace(" ", "_")
    if not raw:
        return "BELUM_DINILAI"
    if raw in {"ADA", "BAIK", "TERCAPAI", "MENCAPAI_TARGET", "SESUAI", "YA"}:
        return "MENCAPAI"
    if raw in {"TIDAK_ADA", "TIDAKADA", "NIHIL", "TIDAK_MELAKSANAKAN"}:
        return "TIDAK_ADA"
    if raw in {"KURANG", "KURANG_TARGET", "BELUM_MENCAPAI", "TIDAK_MENCAPAI"}:
        return "KURANG"
    if raw in INDICATOR_STATUSES:
        return raw
    return "BELUM_DINILAI"


def classify_skp_report_status(predicate: Any, value: Any = "") -> str:
    """Canonical SKP report classification shared by every Tukin consumer.

    Exemptions are explicit governance decisions and therefore take precedence
    over free-text non-submission phrases.  Consumers must not reimplement this
    ordering because it directly affects streaks and payment eligibility.
    """
    predicate = _predicate(predicate)
    raw = f"{predicate} {_predicate(value)}"
    if "MELAHIRKAN" in raw:
        return "EXEMPT_MATERNITY"
    if any(term in raw for term in ("CUTI", "TUGAS BELAJAR", "MENINGGAL")):
        return "EXEMPT_OTHER"
    if any(term in raw for term in (
        "TIDAK MENGERJAKAN", "TIDAK MEMBUAT", "TIDAK BISA DINILAI",
        "TIDAK DAPAT DINILAI", "TIDAK ADA LAPORAN",
    )):
        return "NOT_SUBMITTED_VERIFIED"
    if predicate in VALID_PREDICATES:
        return "SUBMITTED"
    if predicate == "-" or _predicate(value) == "-":
        return "NOT_SUBMITTED_VERIFIED"
    if not predicate:
        return "DATA_MISSING"
    return "INVALID_PREDICATE"


def canonical_skp_reduction_rate(
    predicate: Any,
    report_status: Any,
    consecutive_missing: Any = 0,
) -> Optional[float]:
    """Return the governed SKP reduction percentage or ``None`` if unresolved."""
    normalized = _predicate(predicate)
    status = _predicate(report_status).replace(" ", "_")
    if status == "SUBMITTED":
        return VALID_PREDICATES.get(normalized)
    if status == "NOT_SUBMITTED_VERIFIED":
        try:
            streak = max(0, int(consecutive_missing or 0))
        except (TypeError, ValueError):
            return None
        return 35.0 if streak == 1 else 70.0 if streak == 2 else 100.0
    if status.startswith("EXEMPT_") or status == "MIGRATED_SNAPSHOT":
        return 0.0
    return None


def resolve_skp_for_tukin(
    row: Optional[Mapping[str, Any]],
    direct_final_import: bool = False,
    attendance_participant: bool = False,
) -> dict[str, Any]:
    """Resolve one SKP source into the canonical Tukin calculation semantic."""
    if not row:
        if attendance_participant:
            return {
                "ready": True, "source_type": "MISSING",
                "source_status": "MISSING_FROM_FINAL_IMPORT", "ready_mode": "FALLBACK",
                "final_value": None, "fallback_policy": "MISSING_SKP_35_PERFORMANCE",
                "fallback_rate": 35.0, "reason_code": "", "reason": "",
                "description": "NIP tidak ditemukan pada hasil Final SKP periode",
            }
        return {
            "ready": False, "source_type": "MISSING", "source_status": "SKP_NOT_FOUND",
            "ready_mode": "BLOCKED", "final_value": None, "fallback_policy": None,
            "fallback_rate": None, "reason_code": "SKP_NOT_FOUND",
            "reason": "SKP belum tersedia", "description": "SKP belum tersedia",
        }
    status = _predicate(row.get("review_status") or row.get("status_skp")).replace(" ", "_")
    direct = bool(direct_final_import or status == "FINAL_IMPORTED"
                  or row.get("source_type") == "DIRECT_FINAL_IMPORT")
    source_type = "DIRECT_FINAL_IMPORT" if direct else "INTERNAL_WORKFLOW"
    if _predicate(row.get("validation_status") or "VALID") != "VALID":
        source_status = "INVALID_FINAL_IMPORT" if direct else "INTERNAL_NOT_FINAL"
        reason = "hasil import final SKP tidak valid" if direct else "data SKP internal tidak valid"
        return {"ready": False, "source_type": source_type, "source_status": source_status,
                "ready_mode": "BLOCKED", "final_value": None, "fallback_policy": None,
                "fallback_rate": None,
                "reason_code": "FINAL_IMPORT_INVALID" if direct else "SKP_INVALID",
                "reason": reason, "description": reason}
    predicate = _predicate(row.get("final_predicate") or row.get("predikat_skp"))
    report_status = _predicate(row.get("report_status") or "SUBMITTED").replace(" ", "_")
    rate = _number(row.get("final_reduction_rate") if "final_reduction_rate" in row
                   else row.get("potongan_skp_percent"))
    if rate is None and report_status == "SUBMITTED":
        rate = VALID_PREDICATES.get(predicate)
    value_valid = rate is not None and 0 <= rate <= 100 and (
        report_status != "SUBMITTED" or predicate in VALID_PREDICATES
    )
    if direct:
        if not value_valid:
            return {"ready": False, "source_type": source_type,
                    "source_status": "INVALID_FINAL_IMPORT", "ready_mode": "BLOCKED",
                    "final_value": None, "fallback_policy": None, "fallback_rate": None,
                    "reason_code": "FINAL_IMPORT_VALUE_INVALID",
                    "reason": "hasil import final tidak memiliki nilai SKP yang valid",
                    "description": "Hasil Import Final tersedia tetapi nilainya tidak valid"}
        return {"ready": True, "source_type": source_type, "source_status": "FINAL_IMPORTED",
                "ready_mode": "NORMAL", "final_value": rate, "fallback_policy": None,
                "fallback_rate": None, "reason_code": "", "reason": "",
                "description": "SKP final tersedia dari Import Hasil Final"}
    if status != "APPROVED":
        return {"ready": False, "source_type": source_type,
                "source_status": "INTERNAL_NOT_FINAL", "ready_mode": "BLOCKED",
                "final_value": None, "fallback_policy": None, "fallback_rate": None,
                "reason_code": "INTERNAL_NOT_APPROVED", "reason": "SKP internal belum APPROVED",
                "description": "Workflow SKP internal belum selesai"}
    if not value_valid:
        return {"ready": False, "source_type": source_type,
                "source_status": "INTERNAL_NOT_FINAL", "ready_mode": "BLOCKED",
                "final_value": None, "fallback_policy": None, "fallback_rate": None,
                "reason_code": "SKP_VALUE_INVALID", "reason": "nilai final SKP internal tidak valid",
                "description": "Nilai final SKP internal tidak valid"}
    return {"ready": True, "source_type": source_type, "source_status": "INTERNAL_APPROVED",
            "ready_mode": "NORMAL", "final_value": rate, "fallback_policy": None,
            "fallback_rate": None, "reason_code": "", "reason": "",
            "description": "SKP internal telah APPROVED"}


def skp_ready_for_tukin(row: Mapping[str, Any], direct_final_import: bool = False) -> dict[str, Any]:
    """Backward-compatible entry point for the canonical SKP resolver."""
    return resolve_skp_for_tukin(row, direct_final_import, attendance_participant=False)


def annotate_skp_tukin_provenance(conn, period: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach direct-final provenance, including compatibility for legacy imports."""
    direct_keys: set[tuple[str, str]] = set()
    tables = {item[0] for item in conn.execute("SHOW TABLES").fetchall()}
    if {"skp_assessment_monthly", "skp_import_batch", "skp_assessment_audit"}.issubset(tables):
        found = conn.execute(
            """SELECT DISTINCT s.nip,s.import_batch_id
               FROM skp_assessment_monthly s
               JOIN skp_import_batch b ON b.id=s.import_batch_id
                    AND b.assessment_period=s.assessment_period
               WHERE s.assessment_period=?
                 AND b.status='COMPLETED' AND coalesce(b.rejected_count,0)=0
                 AND EXISTS (
                    SELECT 1 FROM skp_assessment_audit a
                    WHERE a.assessment_period=s.assessment_period AND a.nip=s.nip
                      AND a.action='IMPORT_FINAL'
                      AND coalesce(a.evidence_ref,'')=coalesce(s.source_file,'')
                 )""", [period],
        ).fetchall()
        direct_keys = {(str(nip), str(batch_id or "")) for nip, batch_id in found}
    annotated = []
    for original in rows:
        row = dict(original)
        key = (str(row.get("nip") or ""), str(row.get("import_batch_id") or ""))
        row["_direct_final_import"] = (
            _predicate(row.get("review_status")).replace(" ", "_") == "FINAL_IMPORTED"
            or key in direct_keys
        )
        row["skp_source_type"] = "DIRECT_FINAL_IMPORT" if row["_direct_final_import"] else "INTERNAL_WORKFLOW"
        annotated.append(row)
    return annotated


def _report_status(predicate: str, value: Any) -> str:
    """Backward-compatible private alias for the canonical classifier."""
    return classify_skp_report_status(predicate, value)


class SkpAssessmentService:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)

    def connect(self):
        conn = duckdb.connect(self.db_path)
        with _LOCK:
            if self.db_path not in _READY:
                ensure_schema(conn)
                ensure_indicator_schema(conn)
                ensure_deceased_schema(conn)
                ensure_condition_schema(conn)
                ensure_third_missing_unpaid(conn)
                ensure_operational_schema(conn)
                _READY.add(self.db_path)
        return conn

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        if frame.empty:
            return []
        records = frame.astype(object).where(pd.notnull(frame), None).to_dict("records")
        for record in records:
            for key, value in list(record.items()):
                if isinstance(value, (date, datetime, pd.Timestamp)):
                    record[key] = value.isoformat()
                elif hasattr(value, "item"):
                    try:
                        record[key] = value.item()
                    except Exception:
                        pass
        return records

    def _master(self) -> tuple[dict[str, dict[str, Any]], bool]:
        with self.connect() as conn:
            try:
                frame = conn.execute(
                    """SELECT m.sdm_id,m.nip,m.nama,m.penilai,m.jabatan,m.unit,m.jenis_sdm,m.active,
                              (SELECT p.wilayah_3t FROM sdm_tukin_profile_history p
                               WHERE p.nip=m.nip ORDER BY p.valid_from DESC,p.created_at DESC LIMIT 1) AS wilayah_3t
                       FROM sdm_master m"""
                ).fetchdf()
            except duckdb.CatalogException:
                return {}, False
        rows = {str(row["nip"]): row for row in frame.to_dict("records")}
        return rows, bool(rows)

    def _active_indicator_configs(self, period: str) -> dict[str, list[dict[str, Any]]]:
        """Return approved rules effective in a period, ordered by scoped priority/version."""
        with self.connect() as conn:
            frame = conn.execute(
                """SELECT * FROM skp_indicator_config
                   WHERE status='APPROVED' AND effective_from<=?
                     AND (effective_to IS NULL OR effective_to='' OR effective_to>=?)
                   ORDER BY CASE WHEN scope_type='ALL' THEN 1 ELSE 0 END,
                            version DESC, updated_at DESC""",
                [period, period],
            ).fetchdf()
        result: dict[str, list[dict[str, Any]]] = {}
        for row in self._records(frame):
            code = _predicate(row.get("indicator_code"))
            result.setdefault(code, []).append(row)
        return result

    def _active_assessment_rules(self, period: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            frame = conn.execute(
                """SELECT * FROM skp_assessment_rule
                   WHERE active=true AND effective_from<=?
                     AND (effective_to IS NULL OR effective_to='' OR effective_to>=?)
                   ORDER BY priority,id""", [period, period]
            ).fetchdf()
        return self._records(frame)

    @staticmethod
    def _rule_matches(rule: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
        field = _text(rule.get("condition_field")).lower()
        value = row.get(field)
        expected = _text(rule.get("threshold_value"))
        operator = _predicate(rule.get("comparison_operator") or "EQ").replace(" ", "_")
        if operator in {"GT", "GTE", "LT", "LTE"}:
            left, right = _number(value), _number(expected)
            if left is None or right is None:
                return False
            return {"GT": left > right, "GTE": left >= right,
                    "LT": left < right, "LTE": left <= right}[operator]
        left = _predicate(value)
        if operator == "IN":
            return left in {_predicate(part) for part in expected.split(",") if _text(part)}
        if operator == "NE":
            return left != _predicate(expected)
        return left == _predicate(expected)

    def _apply_assessment_rule(self, rules: list[dict[str, Any]], row: dict[str, Any]) -> None:
        flag = _predicate(row.get("sdm_flag")).replace(" ", "_") or "NON_3T"
        for rule in rules:
            scope = _predicate(rule.get("flag_scope") or "ALL").replace(" ", "_")
            if scope not in {"ALL", flag}:
                continue
            matched = self._rule_matches(rule, row)
            predicate = rule.get("result_if_met") if matched else rule.get("result_if_not_met")
            reduction = rule.get("reduction_if_met") if matched else rule.get("reduction_if_not_met")
            normalized = _predicate(predicate)
            if normalized not in VALID_PREDICATES:
                continue
            row["recommended_predicate"] = normalized.title()
            row["recommended_reduction_rate"] = (
                float(reduction) if reduction is not None else VALID_PREDICATES[normalized]
            )
            row["assessment_rule_id"] = rule.get("id")
            row["assessment_rule_snapshot"] = json.dumps(rule, ensure_ascii=False, default=str)
            if not row.get("recommendation_reason"):
                row["recommendation_reason"] = f"Rekomendasi aturan: {_text(rule.get('rule_name'))}"
            break

    def _approved_exceptions(self, period: str) -> dict[str, str]:
        with self.connect() as conn:
            frame = conn.execute(
                """SELECT nip,exception_code FROM skp_assessment_exception
                   WHERE assessment_period=? AND status='APPROVED'
                   ORDER BY updated_at DESC,created_at DESC""", [period]
            ).fetchall()
        result: dict[str, str] = {}
        for nip, code in frame:
            key, value = str(nip), _text(code)
            if key not in result or value == "MENINGGAL":
                result[key] = value
        return result

    def _death_records(self) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            frame = conn.execute("SELECT * FROM sdm_death_record WHERE status='VERIFIED'").fetchdf()
        return {str(row["nip"]): row for row in self._records(frame)}

    @staticmethod
    def _config_for_master(configs: list[dict[str, Any]], master: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        for config in configs:
            scope = _predicate(config.get("scope_type"))
            expected = _predicate(config.get("scope_value"))
            if scope == "ALL":
                return config
            if scope == "UNIT" and _predicate(master.get("unit")) == expected:
                return config
            if scope == "JABATAN" and _predicate(master.get("jabatan")) == expected:
                return config
            if scope == "JENIS_SDM" and _predicate(master.get("jenis_sdm")) == expected:
                return config
            if scope == "WILAYAH_3T" and master.get("wilayah_3t") is True and expected in {"", "3T", "YA", "TRUE"}:
                return config
        return None

    @staticmethod
    def _indicator_values(get, code: str, config: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        target = _number(get(f"{code}_target"))
        actual = _number(get(f"{code}_actual"))
        if target is None and config and _predicate(config.get("target_mode")) == "FIXED":
            target = _number(config.get("target_value"))
        explicit = _indicator(get(f"{code}_status"))
        status = explicit
        achievement = None
        if actual is None:
            status = explicit if explicit != "BELUM_DINILAI" else _text((config or {}).get("blank_status")) or "BELUM_DINILAI"
        elif actual == 0 and config:
            status = _text(config.get("zero_status")) or "TIDAK_ADA"
        elif target is not None and target > 0:
            achievement = round(actual / target * 100, 4)
            threshold = _number((config or {}).get("reaches_min_percent")) or 100
            status = "MENCAPAI" if achievement >= threshold else "KURANG"
        elif explicit == "BELUM_DINILAI":
            status = "MENCAPAI" if actual > 0 else "TIDAK_ADA"
        return {
            f"{code}_target": target,
            f"{code}_actual": actual,
            f"{code}_achievement_pct": achievement,
            f"{code}_status": status,
            f"{code}_pokja_recommendation": _text(get(f"{code}_pokja_recommendation")),
        }

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        mode = _text(payload.get("import_mode") or "REVIEW").upper()
        if mode not in {"REVIEW", "FINAL"}:
            raise ValueError("Mode impor harus REVIEW atau FINAL")
        period = _period(payload.get("assessment_period"))
        rows = payload.get("rows") or []
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], Mapping):
            raise ValueError("File SKP tidak berisi baris data")
        mapping = _mapping(rows[0].keys())
        if "nip" not in mapping:
            raise ValueError("Kolom NIP tidak ditemukan")
        if "source_predicate" not in mapping and "report_status" not in mapping:
            raise ValueError("Kolom Predikat Kinerja Periodik/Status Laporan SKP tidak ditemukan")

        master, master_available = self._master()
        configs = {} if mode == "FINAL" else self._active_indicator_configs(period)
        assessment_rules = [] if mode == "FINAL" else self._active_assessment_rules(period)
        exceptions = self._approved_exceptions(period)
        deaths = self._death_records()
        from collections import Counter
        nip_column = mapping['nip']
        nip_counts = Counter(_text(row.get(nip_column)) for row in rows)
        seen: set[str] = set()
        normalized = []
        issues = []
        for source_row, source in enumerate(rows, 2):
            get = lambda field, default="": source.get(mapping[field], default) if field in mapping else default
            nip = _text(get("nip"))
            source_predicate = _predicate(get("source_predicate"))
            report_status = _report_status(source_predicate, get("report_status"))
            if nip in exceptions:
                report_status = (
                    "EXEMPT_MATERNITY" if exceptions[nip] == "CUTI_MELAHIRKAN"
                    else "EXEMPT_DECEASED" if exceptions[nip] == "MENINGGAL"
                    else "EXEMPT_OTHER"
                )
            row_issues = []
            if not nip:
                row_issues.append({"severity": "ERROR", "code": "NIP_EMPTY", "message": "NIP kosong"})
            elif nip_counts[nip] > 1:
                row_issues.append({"severity": "ERROR", "code": "DUPLICATE_NIP", "message": "NIP duplikat dalam file"})
            elif master_available and nip not in master:
                row_issues.append({"severity": "ERROR", "code": "NIP_NOT_IN_MASTER", "message": "NIP tidak ditemukan di Master SDM"})
            source_period = _source_period(get("assessment_period"), period[:4])
            if source_period and source_period != period:
                row_issues.append({"severity": "ERROR", "code": "PERIOD_MISMATCH",
                                   "message": f"Periode file {source_period} tidak sama dengan periode proses {period}"})
            death = deaths.get(nip)
            if death and period >= _text(death.get("stop_effective_period")):
                row_issues.append({
                    "severity": "ERROR", "code": "SDM_INACTIVE_DECEASED",
                    "message": f"SDM meninggal; transaksi baru dihentikan mulai {_text(death.get('stop_effective_period'))}",
                })
            if report_status == "DATA_MISSING":
                row_issues.append({"severity": "ERROR", "code": "PREDICATE_EMPTY", "message": "Predikat/status laporan kosong"})
            elif report_status == "INVALID_PREDICATE":
                row_issues.append({"severity": "ERROR", "code": "INVALID_PREDICATE", "message": f"Predikat tidak dikenal: {source_predicate}"})
            if not master_available:
                row_issues.append({"severity": "ERROR" if mode == "FINAL" else "WARNING", "code": "MASTER_EMPTY", "message": "Master SDM belum tersedia; identitas belum dapat direkonsiliasi"})
            if nip:
                seen.add(nip)
            master_row = master.get(nip, {})
            indicator_values: dict[str, Any] = {}
            config_snapshot: dict[str, Any] = {}
            for code in ("hek", "verkom", "graduasi", "p2k2"):
                config = self._config_for_master(configs.get(code.upper(), []), master_row)
                indicator_values.update(self._indicator_values((lambda field, default="": default) if mode == "FINAL" else get, code, config))
                if config:
                    config_snapshot[code] = {
                        "id": config.get("id"), "code": config.get("config_code"),
                        "version": config.get("version"), "target": config.get("target_value"),
                        "threshold": config.get("reaches_min_percent"),
                    }
            item = {
                "assessment_period": period,
                "nip": nip,
                "sdm_id": master_row.get("sdm_id"),
                "nama": _text(get("nama")) or _text(master_row.get("nama")),
                "penilai": _text(get("penilai")) or _text(master_row.get("penilai")),
                "jabatan": _text(get("jabatan")) or _text(master_row.get("jabatan")),
                "source_predicate": source_predicate.title() if source_predicate in VALID_PREDICATES else source_predicate,
                "recommended_predicate": source_predicate.title() if source_predicate in VALID_PREDICATES else "",
                "recommended_reduction_rate": VALID_PREDICATES.get(source_predicate),
                "final_predicate": "",
                "final_reduction_rate": None,
                "report_status": report_status,
                "sdm_flag": "3T" if master_row.get("wilayah_3t") is True else "NON_3T",
                "assessment_rule_id": None,
                "assessment_rule_snapshot": "",
                **indicator_values,
                "indicator_config_snapshot": json.dumps(config_snapshot, ensure_ascii=False),
                "pokja_notes": _text(get("pokja_notes")),
                "recommendation_reason": _text(get("recommendation_reason")),
                "evidence_ref": _text(get("evidence_ref")),
                "validation_status": "INVALID" if any(i["severity"] == "ERROR" for i in row_issues) else "VALID",
                "review_status": "PENDING_REVIEW",
                "source_row": source_row,
                "issues": row_issues,
            }
            if mode == "REVIEW" and item["validation_status"] == "VALID":
                self._apply_assessment_rule(assessment_rules, item)
            normalized.append(item)
            for issue in row_issues:
                issues.append({"row": source_row, "nip": nip, **issue})
        valid_count = sum(row["validation_status"] == "VALID" for row in normalized)
        return {
            "status": "ok", "import_mode": mode, "assessment_period": period, "row_count": len(rows),
            "valid_count": valid_count, "rejected_count": len(rows) - valid_count,
            "warning_count": sum(i["severity"] == "WARNING" for i in issues),
            "master_available": master_available,
            "active_config_count": sum(len(items) for items in configs.values()),
            "active_assessment_rule_count": len(assessment_rules),
            "rows": normalized, "issues": issues[:500],
        }

    def import_rows(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise ValueError("Impor SKP harus dipreview dan dikonfirmasi")
        period = _period(payload.get("assessment_period"))
        self._ensure_period_open(period)
        preview = self.preview(payload)
        final_mode = preview["import_mode"] == "FINAL"
        if final_mode and (payload.get("final_confirmed") is not True or not _text(payload.get("imported_by"))):
            raise ValueError("Impor final memerlukan nama petugas dan konfirmasi hasil final SKP")
        valid_rows = [row for row in preview["rows"] if row["validation_status"] == "VALID"]
        if final_mode and preview["rejected_count"]:
            raise ValueError("Impor Final SKP diblokir: perbaiki seluruh baris invalid/duplikat terlebih dahulu")
        if not valid_rows:
            raise ValueError("Tidak ada baris valid yang dapat disimpan")
        batch_id = str(uuid.uuid4())
        filename = Path(_text(payload.get("source_file")) or "skp.xlsx").name
        actor = _text(payload.get("imported_by")) or "EVKIN"
        approved_rows = []
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                # Recheck in the write transaction so a period that was locked
                # after preview cannot be overwritten during confirmation.
                self._ensure_period_open(period, conn)
                conn.execute("DELETE FROM skp_period_finalization WHERE assessment_period=?", [period])
                # Preserve every original row, including duplicate/unmatched
                # rows excluded from assessment, for subsequent reconciliation.
                conn.execute('''CREATE TABLE IF NOT EXISTS skp_import_source (
                    batch_id VARCHAR, assessment_period VARCHAR, source_row INTEGER,
                    source_file VARCHAR, raw_json VARCHAR,
                    PRIMARY KEY(batch_id,source_row))''')
                raw_frame = pd.DataFrame([{'batch_id':batch_id, 'assessment_period':period,
                    'source_row':index, 'source_file':filename,
                    'raw_json':json.dumps(source, ensure_ascii=False, default=str)}
                    for index, source in enumerate(payload.get('rows') or [], 2)])
                conn.register('skp_original_rows', raw_frame)
                conn.execute('''INSERT INTO skp_import_source
                    (batch_id, assessment_period, source_row, source_file, raw_json)
                    SELECT batch_id, assessment_period, source_row, source_file, raw_json
                    FROM skp_original_rows''')
                conn.unregister('skp_original_rows')
                for row in valid_rows:
                    previous = conn.execute(
                        "SELECT source_predicate,review_status FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?",
                        [row["assessment_period"], row["nip"]],
                    ).fetchone()
                    conn.execute(
                        "DELETE FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?",
                        [row["assessment_period"], row["nip"]],
                    )
                    conn.execute(
                        """INSERT INTO skp_assessment_monthly
                           (assessment_period,nip,sdm_id,nama,penilai,jabatan,source_predicate,
                            recommended_predicate,final_predicate,report_status,hek_status,
                            verkom_status,graduasi_status,p2k2_status,recommendation_reason,
                            evidence_ref,validation_status,review_status,source_file,source_row,import_batch_id,
                            hek_target,hek_actual,hek_achievement_pct,hek_pokja_recommendation,
                            verkom_target,verkom_actual,verkom_achievement_pct,verkom_pokja_recommendation,
                            graduasi_target,graduasi_actual,graduasi_achievement_pct,graduasi_pokja_recommendation,
                            p2k2_target,p2k2_actual,p2k2_achievement_pct,p2k2_pokja_recommendation,
                            indicator_config_snapshot,pokja_notes,sdm_flag,assessment_rule_id,
                            assessment_rule_snapshot,recommended_reduction_rate,final_reduction_rate)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [row["assessment_period"], row["nip"], row["sdm_id"], row["nama"], row["penilai"],
                         row["jabatan"], row["source_predicate"], row["recommended_predicate"], "",
                         row["report_status"], row["hek_status"], row["verkom_status"],
                         row["graduasi_status"], row["p2k2_status"], row["recommendation_reason"],
                         row["evidence_ref"], "VALID", "PENDING_REVIEW", filename, row["source_row"], batch_id,
                         row["hek_target"], row["hek_actual"], row["hek_achievement_pct"], row["hek_pokja_recommendation"],
                         row["verkom_target"], row["verkom_actual"], row["verkom_achievement_pct"], row["verkom_pokja_recommendation"],
                         row["graduasi_target"], row["graduasi_actual"], row["graduasi_achievement_pct"], row["graduasi_pokja_recommendation"],
                         row["p2k2_target"], row["p2k2_actual"], row["p2k2_achievement_pct"], row["p2k2_pokja_recommendation"],
                         row["indicator_config_snapshot"], row["pokja_notes"], row["sdm_flag"],
                         row["assessment_rule_id"], row["assessment_rule_snapshot"],
                         row["recommended_reduction_rate"],
                         row["recommended_reduction_rate"] if final_mode else None],
                    )
                    self._audit(conn, row["assessment_period"], row["nip"], "IMPORT",
                                json.dumps(previous, default=str) if previous else "",
                                row["source_predicate"], row["recommendation_reason"], row["evidence_ref"], actor)
                    if final_mode:
                        final = _predicate(row["source_predicate"])
                        label = final.title() if final in VALID_PREDICATES else ""
                        conn.execute("""UPDATE skp_assessment_monthly SET final_predicate=?,
                            review_status='FINAL_IMPORTED',reviewed_by=?,reviewed_at=now(),
                            approved_by=NULL,approved_at=NULL,updated_at=now()
                            WHERE assessment_period=? AND nip=?""", [label, actor, period, row["nip"]])
                        self._audit(conn, period, row["nip"], "IMPORT_FINAL", "PENDING_REVIEW",
                                    "FINAL_IMPORTED", "Petugas mengonfirmasi sumber sebagai hasil final SKP", filename, actor)
                        approved_rows.append({"assessment_period": period, "nip": row["nip"],
                            "nama": row["nama"], "penilai": row["penilai"], "jabatan": row["jabatan"],
                            "tahap": "", "predicate_raw": row["source_predicate"], "predicate_normalized": label,
                            "report_status": row["report_status"], "consecutive_missing": 0,
                            "skp_reduction_rate": VALID_PREDICATES.get(final, 0), "payment_eligible": True,
                            "exception_code": None, "source_file": filename, "source_row": row["source_row"],
                            "import_batch_id": batch_id})
                        row["review_status"] = "FINAL_IMPORTED"
                        row["final_predicate"] = label
                conn.execute(
                    """INSERT INTO skp_import_batch
                       (id,assessment_period,source_file,row_count,valid_count,rejected_count,status,imported_by)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [batch_id, preview["assessment_period"], filename, preview["row_count"],
                     len(valid_rows), preview["rejected_count"], "COMPLETED", actor],
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        if final_mode:
            self._sync_approved(period, approved_rows)
        else:
            self._sync_pending(preview["assessment_period"], valid_rows)
        return {**preview, "rows": preview["rows"][:100], "batch_id": batch_id,
                "imported": len(valid_rows),
                "source_type": "DIRECT_FINAL_IMPORT" if final_mode else "INTERNAL_WORKFLOW",
                "ready_for_tukin": bool(final_mode)}

    def list_import_batches(self, period: str) -> dict:
        period = _period(period)
        with self.connect() as conn:
            frame = conn.execute('''SELECT b.*,
                (SELECT count(*) FROM skp_assessment_monthly s WHERE s.import_batch_id=b.id AND s.assessment_period=b.assessment_period) AS current_rows
                FROM skp_import_batch b WHERE assessment_period=? ORDER BY created_at DESC''', [period]).fetchdf()
        return {'batches': self._records(frame)}

    def _removal_plan(self, conn, payload):
        import hashlib
        period = _period(payload.get('assessment_period'))
        self._ensure_period_open(period, conn)
        mode = payload.get('mode')
        clause, params = 'assessment_period=?', [period]
        batch = None
        if mode == 'selected':
            nips = payload.get('nips')
            if not isinstance(nips, list) or not nips or any(not isinstance(nip, str) or not nip.strip() for nip in nips):
                raise ValueError('Pilih minimal satu NIP yang valid')
            clause += ' AND nip IN (SELECT * FROM UNNEST(?))'; params.append(sorted(set(nip.strip() for nip in nips)))
        elif mode == 'batch':
            batch = _text(payload.get('batch_id'))
            found = conn.execute('SELECT status FROM skp_import_batch WHERE id=? AND assessment_period=?', [batch, period]).fetchone()
            if not found: raise ValueError('Batch tidak ditemukan pada periode ini')
            if found[0] == 'CANCELLED': raise ValueError('Batch sudah dibatalkan')
            clause += ' AND import_batch_id=?'; params.append(batch)
        elif mode != 'period':
            raise ValueError('Tindakan penghapusan tidak dikenal')
        rows = self._records(conn.execute('SELECT * FROM skp_assessment_monthly WHERE '+clause+' ORDER BY nip', params).fetchdf())
        if rows and conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='tukin_final_monthly'").fetchone()[0]:
            paid = conn.execute("SELECT count(*) FROM tukin_final_monthly WHERE assessment_period=? AND nip IN (SELECT * FROM UNNEST(?)) AND payment_status='PAID'", [period,[row['nip'] for row in rows]]).fetchone()[0]
            if paid: raise ValueError('Penilaian terkait Tukin yang sudah dibayar tidak dapat dihapus')
        token = hashlib.sha256(json.dumps([period,mode,batch,rows],sort_keys=True,default=str).encode()).hexdigest()
        return period, mode, batch, rows, token

    def preview_removal(self, payload):
        with self.connect() as conn:
            period, mode, batch, rows, token = self._removal_plan(conn, payload)
        return {'assessment_period':period, 'mode':mode, 'batch_id':batch,
                'count':len(rows), 'approved_count':sum(row['review_status']=='APPROVED' for row in rows),
                'preview_token':token}

    def remove_assessments(self, payload):
        if payload.get('confirmed') is not True: raise ValueError('Konfirmasi penghapusan wajib diberikan')
        actor, reason = _text(payload.get('actor')), _text(payload.get('reason'))
        if not actor or not reason: raise ValueError('Nama petugas dan alasan wajib diisi')
        with self.connect() as conn:
            conn.execute('BEGIN TRANSACTION')
            try:
                period, mode, batch, rows, token = self._removal_plan(conn, payload)
                if payload.get('preview_token') != token: raise ValueError('Data berubah sejak preview. Periksa dan konfirmasi ulang.')
                nips = [row['nip'] for row in rows]
                action = {'selected':'DELETE_SELECTED','period':'RESET_PERIOD','batch':'CANCEL_IMPORT_BATCH'}[mode]
                for row in rows:
                    self._audit(conn, period, row['nip'], action, json.dumps(row,ensure_ascii=False,default=str), '', reason, batch or '', actor)
                if nips:
                    conn.execute('DELETE FROM skp_assessment_monthly WHERE assessment_period=? AND nip IN (SELECT * FROM UNNEST(?))', [period,nips])
                    # Keep locked/paid snapshots untouched. Invalidate open
                    # downstream outputs because non-submission streaks may change.
                    tables = {r[0] for r in conn.execute('SHOW TABLES').fetchall()}
                    for table in ('tukin_skp_monthly','tukin_final_monthly'):
                        if table not in tables: continue
                        where = "assessment_period>=? AND nip IN (SELECT * FROM UNNEST(?)) AND assessment_period NOT IN (SELECT assessment_period FROM tukin_period WHERE status IN ('LOCKED','PAID','HISTORICAL_LOCKED'))"
                        affected = self._records(conn.execute(f'SELECT * FROM {table} WHERE '+where,[period,nips]).fetchdf())
                        for item in affected:
                            self._audit(conn, item['assessment_period'], item['nip'], 'INVALIDATE_'+action,
                                json.dumps(item,ensure_ascii=False,default=str), 'REVIEW_REQUIRED', reason, table, actor)
                        if table == 'tukin_skp_monthly':
                            conn.execute('UPDATE tukin_skp_monthly SET payment_eligible=false,updated_at=now() WHERE '+where,[period,nips])
                            conn.execute('DELETE FROM tukin_skp_monthly WHERE assessment_period=? AND nip IN (SELECT * FROM UNNEST(?))',[period,nips])
                        else:
                            conn.execute("UPDATE tukin_final_monthly SET payment_status='HOLD',payment_reason='Penilaian SKP dihapus/dibatalkan; review dan hitung ulang diperlukan',paid_amount=NULL,skp_deduction=NULL,total_deduction=NULL,calculated_entitlement=NULL,updated_at=now() WHERE "+where,[period,nips])
                if batch:
                    conn.execute("UPDATE skp_import_batch SET status='CANCELLED' WHERE id=? AND assessment_period=?",[batch,period])
                self._audit(conn,period,'',action,json.dumps({'batch_id':batch,'count':len(rows)}),'',reason,batch or '',actor)
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK'); raise
        return {'status':'ok','deleted':len(rows),'assessment_period':period,'mode':mode}

    def _sync_pending(self, period: str, rows: list[dict[str, Any]]) -> None:
        annual = importlib.import_module("backend.tukin_annual")
        service = annual.TukinAnnualService(self.db_path)
        prepared = []
        for row in rows:
            prepared.append({
                "assessment_period": period, "nip": row["nip"], "nama": row["nama"],
                "penilai": row["penilai"], "jabatan": row["jabatan"], "tahap": "",
                "predicate_raw": row["source_predicate"], "predicate_normalized": "",
                "report_status": "REVIEW_REQUIRED", "consecutive_missing": 0,
                "skp_reduction_rate": 0, "payment_eligible": False,
                "exception_code": None, "source_file": row.get("source_file") or "SKP_ASSESSMENT",
                "source_row": row["source_row"], "import_batch_id": "ASSESSMENT-PENDING",
            })
        service._upsert_skp(period, prepared, replace_missing_only=False)
        service.recompute_skp_streaks(int(period[:4]))
        service._apply_skp_to_unlocked_final(period)

    @staticmethod
    def _audit(conn, period, nip, action, old, new, reason, evidence, actor):
        conn.execute(
            """INSERT INTO skp_assessment_audit
               (id,assessment_period,nip,action,old_value,new_value,reason,evidence_ref,actor)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [str(uuid.uuid4()), period, nip, action, old, new, reason, evidence, actor],
        )

    def list_rows(self, period: str, q: str = "", review_status: str = "",
                  indicator: str = "", indicator_status: str = "", page: int = 1,
                  per_page: int = 100) -> dict[str, Any]:
        period = _period(period)
        clauses, params = ["assessment_period=?"], [period]
        if q:
            clauses.append("(nip ILIKE '%' || ? || '%' OR nama ILIKE '%' || ? || '%')")
            params.extend([q, q])
        if review_status:
            normalized_review = _predicate(review_status).replace(" ", "_")
            if normalized_review == "NEEDS_REVIEW":
                clauses.append("review_status NOT IN ('APPROVED','FINAL_IMPORTED')")
            else:
                clauses.append("review_status=?"); params.append(normalized_review)
        indicator = _text(indicator).lower()
        if indicator in {"hek", "verkom", "graduasi", "p2k2"} and indicator_status:
            clauses.append(f"{indicator}_status=?"); params.append(_indicator(indicator_status))
        where = " AND ".join(clauses)
        offset = (page - 1) * per_page
        with self.connect() as conn:
            total = conn.execute(f"SELECT count(*) FROM skp_assessment_monthly WHERE {where}", params).fetchone()[0]
            frame = conn.execute(
                f"""SELECT * FROM skp_assessment_monthly WHERE {where}
                    ORDER BY nama,nip LIMIT ? OFFSET ?""", params + [per_page, offset]
            ).fetchdf()
            stats = conn.execute(
                """SELECT count(*) total,
                          count(*) FILTER (WHERE review_status='APPROVED') approved,
                          count(*) FILTER (WHERE review_status='FINAL_IMPORTED') final_imported,
                          count(*) FILTER (WHERE review_status NOT IN ('APPROVED','FINAL_IMPORTED')) pending,
                          count(*) FILTER (WHERE report_status='NOT_SUBMITTED_VERIFIED') not_submitted,
                          count(*) FILTER (WHERE coalesce(nullif(final_predicate,''),nullif(recommended_predicate,''),source_predicate) IN ('Kurang','Sangat Kurang')) low_predicate
                   FROM skp_assessment_monthly WHERE assessment_period=?""", [period]
            ).fetchone()
        return {
            "status": "ok", "assessment_period": period, "total": int(total),
            "page": page, "pages": max(1, math.ceil(total / per_page)),
            "summary": dict(zip(["total", "approved", "final_imported", "pending", "not_submitted", "low_predicate"], map(int, stats))),
            "rows": self._records(frame),
        }

    def list_indicator_configs(self, period: str = "") -> dict[str, Any]:
        params: list[Any] = []
        where = "status<>'DELETED'"
        if period:
            period = _period(period)
            where += " AND effective_from<=? AND (effective_to IS NULL OR effective_to='' OR effective_to>=?)"
            params = [period, period]
        with self.connect() as conn:
            frame = conn.execute(
                f"SELECT * FROM skp_indicator_config WHERE {where} ORDER BY indicator_code,version DESC",
                params,
            ).fetchdf()
        return {"status": "ok", "period": period, "rows": self._records(frame)}

    def list_assessment_rules(self, period: str = "") -> dict[str, Any]:
        params: list[Any] = []
        where = "1=1"
        if period:
            period = _period(period)
            where += " AND effective_from<=? AND (effective_to IS NULL OR effective_to='' OR effective_to>=?)"
            params = [period, period]
        with self.connect() as conn:
            frame = conn.execute(
                f"SELECT * FROM skp_assessment_rule WHERE {where} ORDER BY priority,rule_name", params
            ).fetchdf()
        return {"status": "ok", "period": period, "rows": self._records(frame)}

    def save_assessment_rule(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        rule_id = _text(payload.get("id")) or str(uuid.uuid4())
        name = _text(payload.get("rule_name"))
        actor = _text(payload.get("updated_by") or payload.get("created_by")) or "EVKIN"
        flag = _predicate(payload.get("flag_scope") or "ALL").replace(" ", "_")
        field = _text(payload.get("condition_field")).lower()
        operator = _predicate(payload.get("comparison_operator") or "EQ").replace(" ", "_")
        effective_from = _period(payload.get("effective_from"))
        effective_to = _text(payload.get("effective_to"))
        if effective_to:
            effective_to = _period(effective_to)
            if effective_to < effective_from:
                raise ValueError("Periode akhir aturan tidak boleh sebelum periode mulai")
        if not name:
            raise ValueError("Nama aturan wajib diisi")
        if flag not in {"3T", "NON_3T", "ALL"}:
            raise ValueError("Flag aturan harus 3T, NON_3T, atau ALL")
        allowed_fields = {
            "hek_status", "verkom_status", "graduasi_status", "p2k2_status",
            "hek_achievement_pct", "verkom_achievement_pct", "graduasi_achievement_pct",
            "p2k2_achievement_pct", "report_status", "source_predicate",
        }
        if field not in allowed_fields or operator not in {"EQ", "NE", "IN", "GT", "GTE", "LT", "LTE"}:
            raise ValueError("Kondisi/operator aturan tidak valid")
        met = _predicate(payload.get("result_if_met"))
        not_met = _predicate(payload.get("result_if_not_met"))
        if met not in VALID_PREDICATES or (not_met and not_met not in VALID_PREDICATES):
            raise ValueError("Hasil aturan harus menggunakan predikat SKP yang valid")
        reductions = []
        for key in ("reduction_if_met", "reduction_if_not_met"):
            value = _number(payload.get(key))
            if value is not None and not 0 <= value <= 100:
                raise ValueError("Potongan aturan harus antara 0 dan 100 persen")
            reductions.append(value)
        new_value = {
            "id": rule_id, "rule_name": name, "priority": int(payload.get("priority") or 100),
            "flag_scope": flag, "condition_field": field, "comparison_operator": operator,
            "threshold_value": _text(payload.get("threshold_value")),
            "result_if_met": met.title(), "reduction_if_met": reductions[0],
            "result_if_not_met": not_met.title() if not_met else None,
            "reduction_if_not_met": reductions[1], "active": payload.get("active") is not False,
            "effective_from": effective_from, "effective_to": effective_to or None,
            "created_by": actor,
        }
        with self.connect() as conn:
            old_frame = conn.execute("SELECT * FROM skp_assessment_rule WHERE id=?", [rule_id]).fetchdf()
            old = self._records(old_frame)
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM skp_assessment_rule WHERE id=?", [rule_id])
                conn.execute(
                    """INSERT INTO skp_assessment_rule
                       (id,rule_name,priority,flag_scope,condition_field,comparison_operator,
                        threshold_value,result_if_met,reduction_if_met,result_if_not_met,
                        reduction_if_not_met,active,effective_from,effective_to,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", list(new_value.values())
                )
                conn.execute(
                    "INSERT INTO skp_assessment_rule_audit(id,rule_id,action,old_value,new_value,actor) VALUES (?,?,?,?,?,?)",
                    [str(uuid.uuid4()), rule_id, "UPDATE" if old else "CREATE",
                     json.dumps(old[0], default=str) if old else "",
                     json.dumps(new_value, ensure_ascii=False, default=str), actor],
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"status": "ok", "rule": new_value}

    def non_submission_rules(self, period: str = "") -> dict[str, Any]:
        period = _period(period) if period else ""
        where, params = "1=1", []
        if period:
            where += " AND effective_from<=? AND (effective_to IS NULL OR effective_to='' OR effective_to>=?)"
            params = [period, period]
        with self.connect() as conn:
            frame = conn.execute(
                f"SELECT * FROM skp_non_submission_rule WHERE {where} ORDER BY streak_from", params
            ).fetchdf()
        return {"status": "ok", "period": period, "rows": self._records(frame)}

    def save_non_submission_rules(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        rules = payload.get("rules") or []
        actor = _text(payload.get("updated_by")) or "EVKIN"
        if not isinstance(rules, list) or not rules:
            raise ValueError("Minimal satu aturan tidak mengerjakan SKP wajib diisi")
        prepared = []
        for item in rules:
            start = int(item.get("streak_from") or 0)
            end = int(item["streak_to"]) if item.get("streak_to") not in (None, "") else None
            action = _predicate(item.get("action") or "PERCENT")
            rate = _number(item.get("reduction_rate"))
            effective_from = _period(item.get("effective_from"))
            effective_to = _text(item.get("effective_to"))
            if start < 1 or (end is not None and end < start) or action not in {"PERCENT", "UNPAID"}:
                raise ValueError("Rentang/aksi aturan tidak mengerjakan SKP tidak valid")
            if rate is None or not 0 <= rate <= 100:
                raise ValueError("Potongan tidak mengerjakan SKP harus 0–100 persen")
            prepared.append([_text(item.get("id")) or str(uuid.uuid4()), start, end, action,
                             rate, item.get("active") is not False, effective_from,
                             _period(effective_to) if effective_to else None, actor])
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                for item in prepared:
                    old = conn.execute("SELECT * FROM skp_non_submission_rule WHERE id=?", [item[0]]).fetchone()
                    conn.execute("DELETE FROM skp_non_submission_rule WHERE id=?", [item[0]])
                    conn.execute(
                        """INSERT INTO skp_non_submission_rule
                           (id,streak_from,streak_to,action,reduction_rate,active,effective_from,effective_to,updated_by)
                           VALUES (?,?,?,?,?,?,?,?,?)""", item
                    )
                    conn.execute(
                        "INSERT INTO skp_assessment_rule_audit(id,rule_id,action,old_value,new_value,actor) VALUES (?,?,?,?,?,?)",
                        [str(uuid.uuid4()), item[0], "NON_SUBMISSION_UPDATE",
                         json.dumps(old, default=str) if old else "", json.dumps(item, default=str), actor],
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        years = {int(item[6][:4]) for item in prepared}
        annual = importlib.import_module("backend.tukin_annual").TukinAnnualService(self.db_path)
        for year in years:
            annual.recompute_skp_streaks(year)
        return self.non_submission_rules()

    def delete_indicator_config(self, config_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        actor = _text(payload.get('actor'))
        reason = _text(payload.get('reason'))
        if not actor or not reason:
            raise ValueError('Nama petugas dan alasan penghapusan wajib diisi')
        with self.connect() as conn:
            conn.execute('BEGIN TRANSACTION')
            try:
                rows = self._records(conn.execute('SELECT * FROM skp_indicator_config WHERE id=?', [config_id]).fetchdf())
                if not rows or rows[0]['status'] == 'DELETED':
                    raise ValueError('Versi konfigurasi tidak ditemukan atau sudah dihapus')
                old = rows[0]
                # Preserve the version and imported assessment snapshots. Only
                # future rule selection changes; version numbers are never reused.
                conn.execute("UPDATE skp_indicator_config SET status='DELETED',updated_at=now() WHERE id=?", [config_id])
                self._audit_config(conn, config_id, 'DELETE', json.dumps(old, default=str),
                    json.dumps({'status':'DELETED','reason':reason}, ensure_ascii=False), actor)
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK')
                raise
        return {'status':'ok','id':config_id,'deleted':True}

    def save_indicator_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        indicator = _predicate(payload.get("indicator_code"))
        if indicator not in {"HEK", "VERKOM", "GRADUASI", "P2K2"}:
            raise ValueError("Indikator harus HEK, VERKOM, GRADUASI, atau P2K2")
        effective_from = _period(payload.get("effective_from"))
        effective_to = _text(payload.get("effective_to"))
        if effective_to:
            effective_to = _period(effective_to)
            if effective_to < effective_from:
                raise ValueError("Periode akhir tidak boleh sebelum periode mulai")
        target_mode = _predicate(payload.get("target_mode") or "FIXED").replace(" ", "_")
        if target_mode not in {"FIXED", "WORKDAYS", "FROM_IMPORT"}:
            raise ValueError("Mode target tidak valid")
        target_value = _number(payload.get("target_value"))
        if target_mode == "FIXED" and (target_value is None or target_value < 0):
            raise ValueError("Target tetap wajib berupa angka nol atau lebih")
        threshold = _number(payload.get("reaches_min_percent"))
        if threshold is None or threshold <= 0:
            raise ValueError("Ambang mencapai wajib lebih dari nol")
        scope_type = _predicate(payload.get("scope_type") or "ALL").replace(" ", "_")
        if scope_type not in {"ALL", "UNIT", "JABATAN", "WILAYAH_3T", "JENIS_SDM"}:
            raise ValueError("Lingkup konfigurasi tidak valid")
        scope_value = _text(payload.get("scope_value"))
        if scope_type != "ALL" and not scope_value:
            raise ValueError("Nilai lingkup wajib diisi")
        requested_status = _predicate(payload.get("status") or "DRAFT")
        if requested_status not in {"DRAFT", "APPROVED"}:
            raise ValueError("Status konfigurasi harus DRAFT atau APPROVED")
        actor = _text(payload.get("created_by")) or "EVKIN"
        code = f"{indicator}-{scope_type}-{_header(scope_value) or 'all'}-{effective_from}"
        config_id = str(uuid.uuid4())
        with self.connect() as conn:
            version = int(conn.execute(
                "SELECT coalesce(max(version),0)+1 FROM skp_indicator_config WHERE indicator_code=? AND scope_type=? AND coalesce(scope_value,'')=?",
                [indicator, scope_type, scope_value],
            ).fetchone()[0])
            conn.execute(
                """INSERT INTO skp_indicator_config
                   (id,config_code,version,indicator_code,display_name,unit,target_mode,target_value,
                    reaches_min_percent,zero_status,blank_status,scope_type,scope_value,effective_from,
                    effective_to,legal_basis,meeting_document,status,created_by,approved_by,approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CASE WHEN ?='APPROVED' THEN now() ELSE NULL END)""",
                [config_id, code, version, indicator, _text(payload.get("display_name")) or indicator,
                 _text(payload.get("unit")), target_mode, target_value, threshold,
                 _text(payload.get("zero_status")) or "TIDAK_ADA",
                 _text(payload.get("blank_status")) or "BELUM_DINILAI", scope_type, scope_value,
                 effective_from, effective_to or None, _text(payload.get("legal_basis")),
                 _text(payload.get("meeting_document")), requested_status, actor,
                 actor if requested_status == "APPROVED" else None, requested_status],
            )
            self._audit_config(conn, config_id, "CREATE_AND_APPROVE" if requested_status == "APPROVED" else "CREATE_DRAFT", "", json.dumps(dict(payload), default=str), actor)
        return {"status": "ok", "id": config_id, "version": version, "config_status": requested_status}

    @staticmethod
    def _audit_config(conn, config_id: str, action: str, old: str, new: str, actor: str) -> None:
        conn.execute(
            "INSERT INTO skp_indicator_config_audit(id,config_id,action,old_value,new_value,actor) VALUES (?,?,?,?,?,?)",
            [str(uuid.uuid4()), config_id, action, old, new, actor],
        )

    def save_exception(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        period = _period(payload.get("assessment_period"))
        self._ensure_period_open(period)
        nips = list(dict.fromkeys(_text(nip) for nip in (payload.get("nips") or []) if _text(nip)))
        if not nips:
            raise ValueError("Pilih minimal satu SDM")
        code = _predicate(payload.get("exception_code")).replace(" ", "_")
        if code not in {"CUTI_MELAHIRKAN", "TUGAS_BELAJAR", "MENINGGAL", "LAINNYA_RESMI"}:
            raise ValueError("Jenis pengecualian tidak valid")
        reason = _text(payload.get("reason"))
        evidence = _text(payload.get("evidence_ref"))
        actor = _text(payload.get("approved_by")) or "EVKIN"
        if not reason or not evidence:
            raise ValueError("Alasan dan referensi eviden pengecualian wajib diisi")
        start_date = _text(payload.get("start_date"))
        end_date = _text(payload.get("end_date"))
        if code == "CUTI_MELAHIRKAN" and (not start_date or not end_date):
            raise ValueError("Tanggal mulai dan selesai wajib untuk cuti melahirkan")
        if code == "MENINGGAL":
            if len(nips) != 1:
                raise ValueError("Kondisi meninggal dicatat satu SDM per proses")
            if not start_date:
                raise ValueError("Tanggal meninggal wajib diisi")
            if start_date[:7] != period:
                raise ValueError("Tanggal meninggal harus berada pada periode penilaian yang dipilih")
        if start_date and end_date and start_date > end_date:
            raise ValueError("Tanggal mulai tidak boleh setelah tanggal selesai")
        status_value = (
            "EXEMPT_MATERNITY" if code == "CUTI_MELAHIRKAN"
            else "EXEMPT_DECEASED" if code == "MENINGGAL"
            else "EXEMPT_OTHER"
        )
        pay_to_heir = code == "MENINGGAL" and payload.get("pay_to_heir") is True
        payment_decision = ""
        if code == "MENINGGAL":
            payment_decision = _predicate(payload.get("payment_decision") or "HOLD_REVIEW").replace(" ", "_")
            if pay_to_heir:
                payment_decision = "HEIR"
                required_heir = {
                    "nama ahli waris": _text(payload.get("heir_name")),
                    "hubungan ahli waris": _text(payload.get("heir_relationship")),
                    "bank ahli waris": _text(payload.get("heir_bank_name")),
                    "rekening ahli waris": _text(payload.get("heir_account_number")),
                    "dokumen ahli waris": _text(payload.get("heir_document_ref")),
                }
                missing = [label for label, value in required_heir.items() if not value]
                if missing:
                    raise ValueError("Data pembayaran ahli waris belum lengkap: " + ", ".join(missing))
            elif payment_decision == "HEIR":
                raise ValueError("Aktifkan pilihan pembayaran kepada ahli waris terlebih dahulu")
            if payment_decision not in {"HOLD_REVIEW", "NORMAL_ACCOUNT", "HEIR", "UNPAID"}:
                raise ValueError("Keputusan pembayaran meninggal tidak valid")
        death_record_id = ""
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                if code == "MENINGGAL":
                    nip = nips[0]
                    master = conn.execute(
                        "SELECT active,employment_status FROM sdm_master WHERE nip=?", [nip]
                    ).fetchone()
                    if not master:
                        raise ValueError("NIP tidak ditemukan di Master SDM")
                    existing_frame = conn.execute(
                        "SELECT * FROM sdm_death_record WHERE nip=?", [nip]
                    ).fetchdf()
                    existing = self._records(existing_frame)
                    death_record_id = _text(existing[0].get("id")) if existing else str(uuid.uuid4())
                    old_death = json.dumps(existing[0], ensure_ascii=False, default=str) if existing else ""
                    year, month = map(int, period.split("-"))
                    stop_period = f"{year + (1 if month == 12 else 0):04d}-{1 if month == 12 else month + 1:02d}"
                    conn.execute("DELETE FROM sdm_death_record WHERE nip=?", [nip])
                    conn.execute(
                        """INSERT INTO sdm_death_record
                           (id,nip,death_date,assessment_period,stop_effective_period,document_ref,
                            reason,verified_by,status,payment_decision,pay_to_heir,heir_name,
                            heir_relationship,heir_bank_name,heir_account_number,heir_account_holder,
                            heir_document_ref,payment_notes)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [death_record_id, nip, start_date, period, stop_period, evidence, reason, actor,
                         "VERIFIED", payment_decision, pay_to_heir, _text(payload.get("heir_name")),
                         _text(payload.get("heir_relationship")), _text(payload.get("heir_bank_name")),
                         _text(payload.get("heir_account_number")), _text(payload.get("heir_account_holder")),
                         _text(payload.get("heir_document_ref")), _text(payload.get("payment_notes"))],
                    )
                    conn.execute(
                        """INSERT INTO sdm_death_audit(id,death_record_id,nip,action,old_value,new_value,actor)
                           VALUES (?,?,?,?,?,?,?)""",
                        [str(uuid.uuid4()), death_record_id, nip, "UPDATE" if existing else "CREATE",
                         old_death, json.dumps(dict(payload), ensure_ascii=False, default=str), actor],
                    )
                    conn.execute(
                        "UPDATE sdm_master SET active=false,employment_status='MENINGGAL',valid_to=?,master_version=master_version+1,updated_at=now() WHERE nip=?",
                        [start_date, nip],
                    )
                    batch_id = f"DEATH-{death_record_id}"
                    conn.execute("DELETE FROM sdm_change_request WHERE batch_id=? AND field_name='active'", [batch_id])
                    conn.execute(
                        """INSERT INTO sdm_change_request
                           (id,batch_id,nip,field_name,old_value,new_value,effective_date,status,
                            source_file,reason,reviewed_by,reviewed_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,now())""",
                        [str(uuid.uuid4()), batch_id, nip, "active", str(bool(master[0])).lower(),
                         "false", f"{stop_period}-01", "APPROVED", evidence, reason, actor],
                    )
                for nip in nips:
                    conn.execute(
                        "DELETE FROM skp_assessment_exception WHERE assessment_period=? AND nip=? AND exception_code=?",
                        [period, nip, code],
                    )
                    conn.execute(
                        """INSERT INTO skp_assessment_exception
                           (id,assessment_period,nip,exception_code,effect_type,start_date,end_date,reason,evidence_ref,status,approved_by)
                           VALUES (?,?,?,?,?,?,?,?,?,'APPROVED',?)""",
                        [str(uuid.uuid4()), period, nip, code, "EXEMPT_SKP",
                         start_date or None, end_date or None,
                         reason, evidence, actor],
                    )
                    conn.execute(
                        """UPDATE skp_assessment_monthly SET report_status=?,recommendation_reason=?,evidence_ref=?,
                           review_status='PENDING_REVIEW',final_predicate=NULL,updated_at=now()
                           WHERE assessment_period=? AND nip=?""",
                        [status_value, reason, evidence, period, nip],
                    )
                    self._audit(conn, period, nip, "EXCEPTION", "", code, reason, evidence, actor)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        if code == "MENINGGAL":
            annual = importlib.import_module("backend.tukin_annual")
            annual.TukinAnnualService(self.db_path).apply_death_controls(period, nips[0])
        return {"status": "ok", "updated": len(nips), "death_record_id": death_record_id or None,
                "payment_decision": payment_decision if code == "MENINGGAL" else None}

    def list_exceptions(self, period: str) -> dict[str, Any]:
        period = _period(period)
        with self.connect() as conn:
            frame = conn.execute(
                """SELECT e.*,d.death_date,d.stop_effective_period,d.payment_decision,d.pay_to_heir,
                          d.heir_name,d.heir_relationship,d.heir_bank_name,d.heir_account_number,
                          d.heir_account_holder,d.heir_document_ref,d.payment_notes
                   FROM skp_assessment_exception e LEFT JOIN sdm_death_record d
                     ON d.nip=e.nip AND e.exception_code='MENINGGAL'
                   WHERE e.assessment_period=? ORDER BY e.created_at DESC""", [period]
            ).fetchdf()
        return {"status": "ok", "assessment_period": period, "rows": self._records(frame)}

    def save_condition_decision(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Record a governed condition once; Tukin only consumes the approved effect."""
        period = _period(payload.get("assessment_period"))
        self._ensure_period_open(period)
        nips = list(dict.fromkeys(_text(nip) for nip in (payload.get("nips") or []) if _text(nip)))
        if not nips:
            raise ValueError("Pilih minimal satu SDM")
        code = _predicate(payload.get("condition_code")).replace(" ", "_")
        if code not in {"HUKDIS", "LAINNYA"}:
            raise ValueError("Kondisi keputusan harus HUKDIS atau LAINNYA")
        skp_effect = _predicate(payload.get("skp_effect") or "NONE").replace(" ", "_")
        if skp_effect not in {"NONE", "RECOMMEND_PREDICATE"}:
            raise ValueError("Efek SKP harus tanpa perubahan atau rekomendasi predikat")
        recommended = _predicate(payload.get("recommended_predicate"))
        if skp_effect == "RECOMMEND_PREDICATE" and recommended not in VALID_PREDICATES:
            raise ValueError("Predikat rekomendasi Hukdis belum valid")
        payment_effect = _predicate(payload.get("payment_effect") or "HOLD").replace(" ", "_")
        if payment_effect not in {"NONE", "HOLD", "UNPAID"}:
            raise ValueError("Efek pembayaran harus NONE, HOLD, atau UNPAID")
        reason = _text(payload.get("reason")); evidence = _text(payload.get("evidence_ref"))
        document = _text(payload.get("document_number")); actor = _text(payload.get("approved_by"))
        if not all((reason, evidence, document, actor)):
            raise ValueError("Alasan, eviden, nomor dokumen, dan penyetuju wajib diisi")
        start_date = _text(payload.get("start_date")); end_date = _text(payload.get("end_date"))
        if start_date and end_date and start_date > end_date:
            raise ValueError("Tanggal mulai tidak boleh setelah tanggal selesai")
        updated = 0
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                if skp_effect == "RECOMMEND_PREDICATE":
                    conn.execute("DELETE FROM skp_period_finalization WHERE assessment_period=?", [period])
                for nip in nips:
                    assessment = conn.execute(
                        "SELECT recommended_predicate,review_status FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?",
                        [period, nip],
                    ).fetchone()
                    if not assessment:
                        continue
                    previous_frame = conn.execute(
                        "SELECT * FROM skp_condition_decision WHERE assessment_period=? AND nip=? AND condition_code=?",
                        [period, nip, code],
                    ).fetchdf()
                    previous = self._records(previous_frame)
                    decision_id = _text(previous[0].get("id")) if previous else str(uuid.uuid4())
                    conn.execute("DELETE FROM skp_condition_decision WHERE id=?", [decision_id])
                    conn.execute(
                        """INSERT INTO skp_condition_decision
                           (id,assessment_period,nip,condition_code,start_date,end_date,skp_effect,
                            recommended_predicate,payment_effect,reason,evidence_ref,document_number,
                            status,approved_by,approved_at,synced_to_tukin)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'APPROVED',?,now(),false)""",
                        [decision_id, period, nip, code, start_date or None, end_date or None,
                         skp_effect, recommended.title() if recommended else None, payment_effect,
                         reason, evidence, document, actor],
                    )
                    new_value = {
                        "condition_code": code, "skp_effect": skp_effect,
                        "recommended_predicate": recommended.title() if recommended else "",
                        "payment_effect": payment_effect, "reason": reason,
                        "evidence_ref": evidence, "document_number": document,
                    }
                    conn.execute(
                        """INSERT INTO skp_condition_decision_audit
                           (id,decision_id,assessment_period,nip,action,old_value,new_value,actor)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        [str(uuid.uuid4()), decision_id, period, nip,
                         "UPDATE" if previous else "CREATE",
                         json.dumps(previous[0], ensure_ascii=False, default=str) if previous else "",
                         json.dumps(new_value, ensure_ascii=False), actor],
                    )
                    if skp_effect == "RECOMMEND_PREDICATE":
                        conn.execute(
                            """UPDATE skp_assessment_monthly SET recommended_predicate=?,
                               recommended_reduction_rate=?,
                               recommendation_reason=?,evidence_ref=?,review_status='RECOMMENDED',
                               reviewed_by=?,reviewed_at=now(),final_predicate=NULL,
                               approved_by=NULL,approved_at=NULL,updated_at=now()
                               WHERE assessment_period=? AND nip=?""",
                            [recommended.title(), VALID_PREDICATES[recommended], reason, evidence, actor, period, nip],
                        )
                        self._audit(conn, period, nip, "CONDITION_RECOMMENDATION",
                                    _text(assessment[0]), recommended.title(), reason, evidence, actor)
                    else:
                        self._audit(conn, period, nip, "CONDITION_DECISION",
                                    "", code, reason, evidence, actor)
                    updated += 1
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        annual = importlib.import_module("backend.tukin_annual")
        if not updated:
            raise ValueError("SDM terpilih belum memiliki data penilaian SKP pada periode ini")
        sync = annual.TukinAnnualService(self.db_path).sync_skp_condition_decisions(period)
        return {"status": "ok", "assessment_period": period, "updated": updated,
                "synced_to_tukin": sync.get("synced", 0)}

    def list_condition_decisions(self, period: str) -> dict[str, Any]:
        period = _period(period)
        with self.connect() as conn:
            frame = conn.execute(
                """SELECT d.*,a.nama,a.final_predicate,a.review_status
                   FROM skp_condition_decision d
                   LEFT JOIN skp_assessment_monthly a
                     ON a.assessment_period=d.assessment_period AND a.nip=d.nip
                   WHERE d.assessment_period=? ORDER BY d.updated_at DESC,d.nip""",
                [period],
            ).fetchdf()
        return {"status": "ok", "assessment_period": period, "rows": self._records(frame)}

    def bulk_recommend(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        period = _period(payload.get("assessment_period"))
        self._ensure_period_open(period)
        nips = list(dict.fromkeys(_text(nip) for nip in (payload.get("nips") or []) if _text(nip)))
        if not nips:
            raise ValueError("Pilih minimal satu SDM")
        predicate = _predicate(payload.get("recommended_predicate"))
        if predicate not in VALID_PREDICATES:
            raise ValueError("Predikat rekomendasi tidak valid")
        reason = _text(payload.get("reason"))
        if not reason:
            raise ValueError("Alasan rekomendasi wajib diisi")
        actor = _text(payload.get("reviewed_by")) or "EVKIN"
        evidence = _text(payload.get("evidence_ref"))
        notes = _text(payload.get("reviewer_notes"))
        meeting_date = _text(payload.get("meeting_date"))
        document_number = _text(payload.get("document_number"))
        meeting_id = str(uuid.uuid4())
        batch_code = f"RAPAT-{period}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{meeting_id[:6].upper()}"
        indicators = {
            key: _indicator(payload.get(key)) for key in
            ("hek_status", "verkom_status", "graduasi_status", "p2k2_status")
            if _text(payload.get(key))
        }
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM skp_period_finalization WHERE assessment_period=?", [period])
                conn.execute(
                    """INSERT INTO skp_meeting_batch
                       (id,batch_code,assessment_period,meeting_date,document_number,recommended_predicate,
                        reason,evidence_ref,criteria_json,status,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [meeting_id, batch_code, period, meeting_date or None, document_number,
                     predicate.title(), reason, evidence, json.dumps(indicators, ensure_ascii=False),
                     "RECORDED" if meeting_date and document_number else "NEEDS_DOCUMENT", actor],
                )
                count = 0
                for nip in nips:
                    current = conn.execute(
                        "SELECT recommended_predicate FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?",
                        [period, nip],
                    ).fetchone()
                    if not current:
                        continue
                    sets = ["recommended_predicate=?", "recommended_reduction_rate=?", "recommendation_reason=?", "reviewer_notes=?",
                            "evidence_ref=?", "review_status='RECOMMENDED'", "reviewed_by=?",
                            "reviewed_at=now()", "final_predicate=NULL", "approved_by=NULL",
                            "approved_at=NULL", "meeting_batch_id=?", "updated_at=now()"]
                    values: list[Any] = [predicate.title(), VALID_PREDICATES[predicate], reason, notes, evidence, actor, meeting_id]
                    for field, value in indicators.items():
                        sets.append(f"{field}=?"); values.append(value)
                    conn.execute(
                        f"UPDATE skp_assessment_monthly SET {','.join(sets)} WHERE assessment_period=? AND nip=?",
                        values + [period, nip],
                    )
                    self._audit(conn, period, nip, "RECOMMEND", _text(current[0]), predicate.title(), reason, evidence, actor)
                    conn.execute(
                        """INSERT INTO skp_meeting_member
                           (batch_id,assessment_period,nip,predicate_before,predicate_after,reason)
                           VALUES (?,?,?,?,?,?)""",
                        [meeting_id, period, nip, _text(current[0]), predicate.title(), reason],
                    )
                    count += 1
                conn.execute("UPDATE skp_meeting_batch SET affected_count=? WHERE id=?", [count, meeting_id])
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK"); raise
        return {"status": "ok", "updated": count, "assessment_period": period,
                "meeting_batch_id": meeting_id, "batch_code": batch_code}

    def review(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        period = _period(payload.get("assessment_period"))
        self._ensure_period_open(period)
        nips = list(dict.fromkeys(_text(nip) for nip in (payload.get("nips") or []) if _text(nip)))
        action = _predicate(payload.get("action")).replace(" ", "_")
        if action not in {"APPROVE", "RETURN"}:
            raise ValueError("Aksi review harus APPROVE atau RETURN")
        if not nips:
            raise ValueError("Pilih minimal satu SDM")
        actor = _text(payload.get("approved_by")) or "EVKIN"
        notes = _text(payload.get("notes"))
        approved_rows = []
        with self.connect() as conn:
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("DELETE FROM skp_period_finalization WHERE assessment_period=?", [period])
                for nip in nips:
                    row = conn.execute(
                        """SELECT nama,penilai,jabatan,source_predicate,recommended_predicate,
                                  report_status,source_file,source_row,import_batch_id,review_status,
                                  recommended_reduction_rate,final_reduction_rate
                           FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?""",
                        [period, nip],
                    ).fetchone()
                    if not row:
                        continue
                    if action == "RETURN":
                        if not notes:
                            raise ValueError("Catatan pengembalian wajib diisi")
                        conn.execute(
                            """UPDATE skp_assessment_monthly SET review_status='RETURNED',reviewer_notes=?,
                               final_predicate=NULL,approved_by=NULL,approved_at=NULL,updated_at=now()
                               WHERE assessment_period=? AND nip=?""", [notes, period, nip]
                        )
                        self._audit(conn, period, nip, "RETURN", row[9], "RETURNED", notes, "", actor)
                        continue
                    report_status = _text(row[5])
                    final_predicate = _predicate(payload.get("final_predicate") or row[4] or row[3])
                    if report_status == "SUBMITTED" and final_predicate not in VALID_PREDICATES:
                        raise ValueError(f"Predikat final NIP {nip} belum valid")
                    base_predicate = _predicate(row[4] or row[3])
                    requested_rate = _number(payload.get("final_reduction_rate"))
                    final_rate = requested_rate if requested_rate is not None else (
                        float(row[10]) if row[10] is not None else VALID_PREDICATES.get(final_predicate, 0)
                    )
                    manual_override = final_predicate != base_predicate or (
                        requested_rate is not None and row[10] is not None
                        and float(requested_rate) != float(row[10])
                    )
                    if manual_override and not notes:
                        raise ValueError("Alasan manual override wajib diisi")
                    conn.execute(
                        """UPDATE skp_assessment_monthly SET final_predicate=?,review_status='APPROVED',
                           final_reduction_rate=?,manual_override_reason=?,manual_override_by=?,
                           manual_override_at=CASE WHEN ? THEN now() ELSE NULL END,
                           reviewer_notes=CASE WHEN ?<>'' THEN ? ELSE reviewer_notes END,
                           approved_by=?,approved_at=now(),updated_at=now()
                           WHERE assessment_period=? AND nip=?""",
                        [final_predicate.title() if final_predicate in VALID_PREDICATES else "", final_rate,
                         notes if manual_override else None, actor if manual_override else None, manual_override,
                         notes, notes, actor, period, nip],
                    )
                    before = json.dumps({"predicate": _text(row[4] or row[3]), "reduction_rate": row[10]}, default=str)
                    after = json.dumps({"predicate": final_predicate.title(), "reduction_rate": final_rate}, default=str)
                    self._audit(conn, period, nip, "MANUAL_OVERRIDE" if manual_override else "APPROVE",
                                before, after, notes, "", actor)
                    approved_rows.append({
                        "assessment_period": period, "nip": nip, "nama": _text(row[0]),
                        "penilai": _text(row[1]), "jabatan": _text(row[2]), "tahap": "",
                        "predicate_raw": _text(row[3]),
                        "predicate_normalized": final_predicate.title() if final_predicate in VALID_PREDICATES else "",
                        "report_status": report_status, "consecutive_missing": 0,
                        "skp_reduction_rate": final_rate,
                        "payment_eligible": True, "exception_code": None,
                        "source_file": _text(row[6]), "source_row": row[7], "import_batch_id": _text(row[8]),
                    })
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK"); raise
        self._sync_approved(period, approved_rows)
        return {"status": "ok", "action": action, "updated": len(approved_rows) if action == "APPROVE" else len(nips)}

    def _sync_approved(self, period, approved_rows):
        if approved_rows:
            annual = importlib.import_module("backend.tukin_annual")
            service = annual.TukinAnnualService(self.db_path)
            service._upsert_skp(period, approved_rows, replace_missing_only=False)
            service.recompute_skp_streaks(int(period[:4]))
            service._apply_skp_to_unlocked_final(period)
            service.sync_skp_condition_decisions(period)
            service.apply_death_controls(period)

    def _ensure_period_open(self, period: str, conn=None) -> None:
        """Prevent assessment decisions from changing a locked or paid period."""
        if conn is not None:
            try:
                row = conn.execute(
                    "SELECT status FROM tukin_period WHERE assessment_period=?", [period]
                ).fetchone()
            except duckdb.CatalogException:
                row = None
        else:
            with self.connect() as own_conn:
                try:
                    row = own_conn.execute(
                        "SELECT status FROM tukin_period WHERE assessment_period=?", [period]
                    ).fetchone()
                except duckdb.CatalogException:
                    row = None
        if row and _predicate(row[0]).replace(" ", "_") in {"LOCKED", "PAID", "HISTORICAL_LOCKED"}:
            raise ValueError("Periode Tukin sudah dikunci/dibayar dan tidak dapat mengubah penilaian SKP")

    def period_summary(self, period: str) -> dict[str, Any]:
        period = _period(period)
        with self.connect() as conn:
            stats = conn.execute(
                """SELECT count(*) total_sdm,
                          count(*) FILTER (WHERE review_status IN ('APPROVED','FINAL_IMPORTED')) final_count,
                          count(*) FILTER (WHERE review_status='APPROVED') internal_approved_count,
                          count(*) FILTER (WHERE review_status='FINAL_IMPORTED') direct_final_count,
                          count(*) FILTER (WHERE review_status NOT IN ('APPROVED','FINAL_IMPORTED')) review_count,
                          count(*) FILTER (WHERE validation_status<>'VALID' OR report_status IN ('DATA_MISSING','INVALID_PREDICATE')) incomplete_count,
                          count(*) FILTER (WHERE report_status='NOT_SUBMITTED_VERIFIED') not_submitted_count
                   FROM skp_assessment_monthly WHERE assessment_period=?""", [period]
            ).fetchone()
            hukdis = conn.execute(
                """SELECT count(*) FROM skp_condition_decision
                   WHERE assessment_period=? AND status='APPROVED' AND condition_code='HUKDIS'""", [period]
            ).fetchone()[0]
            row = conn.execute(
                "SELECT status,finalized_by,finalized_at FROM skp_period_finalization WHERE assessment_period=?",
                [period],
            ).fetchone()
            latest_rejected = conn.execute(
                """SELECT coalesce(rejected_count,0) FROM skp_import_batch
                   WHERE assessment_period=? AND status='COMPLETED' ORDER BY created_at DESC LIMIT 1""",
                [period],
            ).fetchone()
        keys = ["total_sdm", "final_count", "internal_approved_count", "direct_final_count",
                "review_count", "incomplete_count", "not_submitted_count"]
        summary = dict(zip(keys, map(int, stats)))
        summary["incomplete_count"] += int(latest_rejected[0]) if latest_rejected else 0
        summary["hukdis_count"] = int(hukdis)
        summary["ready_to_finalize"] = bool(summary["total_sdm"] and not summary["review_count"] and not summary["incomplete_count"])
        summary["requires_internal_finalization"] = bool(summary["internal_approved_count"])
        summary["status"] = row[0] if row else (
            "FINAL_IMPORTED" if summary["ready_to_finalize"] and summary["direct_final_count"] == summary["total_sdm"]
            else "READY" if summary["ready_to_finalize"] else "IN_PROGRESS"
        )
        summary["finalized_by"] = row[1] if row else None
        summary["finalized_at"] = str(row[2]) if row and row[2] else None
        return {"status": "ok", "assessment_period": period, "summary": summary}

    def finalize_period(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        period = _period(payload.get("assessment_period"))
        actor = _text(payload.get("finalized_by"))
        reason = _text(payload.get("reason"))
        if not actor or not reason:
            raise ValueError("Petugas dan alasan Final SKP wajib diisi")
        self._ensure_period_open(period)
        current = self.period_summary(period)
        summary = current["summary"]
        if not summary["ready_to_finalize"]:
            raise ValueError(
                f"Final SKP diblokir: {summary['review_count']} perlu verifikasi dan "
                f"{summary['incomplete_count']} data tidak lengkap"
            )
        snapshot = json.dumps({**summary, "reason": reason}, ensure_ascii=False, default=str)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO skp_period_finalization
                   (assessment_period,status,total_sdm,approved_count,incomplete_count,
                    summary_snapshot,finalized_by,finalized_at)
                   VALUES (?,'FINAL',?,?,?,?,?,now())
                   ON CONFLICT (assessment_period) DO UPDATE SET status='FINAL',
                    total_sdm=excluded.total_sdm,approved_count=excluded.approved_count,
                    incomplete_count=excluded.incomplete_count,summary_snapshot=excluded.summary_snapshot,
                    finalized_by=excluded.finalized_by,finalized_at=now()""",
                [period, summary["total_sdm"], summary["final_count"], summary["incomplete_count"], snapshot, actor],
            )
            self._audit(conn, period, "", "FINALIZE_PERIOD", "", "FINAL", reason, "", actor)
        return self.period_summary(period)

    def annual(self, year: int, q: str = "") -> dict[str, Any]:
        with self.connect() as conn:
            params: list[Any] = [f"{year}-01", f"{year}-12"]
            where = "assessment_period BETWEEN ? AND ?"
            if q:
                where += " AND (nip ILIKE '%' || ? || '%' OR nama ILIKE '%' || ? || '%')"
                params.extend([q, q])
            frame = conn.execute(
                f"SELECT * FROM skp_assessment_monthly WHERE {where} ORDER BY nama,nip,assessment_period", params
            ).fetchdf()
        people: dict[str, dict[str, Any]] = {}
        for row in self._records(frame):
            nip = _text(row["nip"])
            person = people.setdefault(nip, {
                "nip": nip, "nama": _text(row.get("nama")),
                "months": [{"month": month, "period": f"{year}-{month:02d}"} for month in range(1, 13)],
            })
            month = int(_text(row["assessment_period"])[5:7])
            person["months"][month - 1].update({
                "predicate": _text(row.get("final_predicate") or row.get("recommended_predicate") or row.get("source_predicate")),
                "review_status": _text(row.get("review_status")), "report_status": _text(row.get("report_status")),
                "reason": _text(row.get("recommendation_reason")), "evidence_ref": _text(row.get("evidence_ref")),
                "meeting_batch_id": _text(row.get("meeting_batch_id")),
                "approved_by": _text(row.get("approved_by")), "approved_at": row.get("approved_at"),
                "hek_status": _text(row.get("hek_status")), "hek_target": row.get("hek_target"), "hek_actual": row.get("hek_actual"),
                "verkom_status": _text(row.get("verkom_status")), "verkom_target": row.get("verkom_target"), "verkom_actual": row.get("verkom_actual"),
                "graduasi_status": _text(row.get("graduasi_status")), "graduasi_target": row.get("graduasi_target"), "graduasi_actual": row.get("graduasi_actual"),
                "p2k2_status": _text(row.get("p2k2_status")), "p2k2_target": row.get("p2k2_target"), "p2k2_actual": row.get("p2k2_actual"),
            })
        for person in people.values():
            months = person["months"]
            person["semester_1"] = self._semester_summary(months[:6])
            person["semester_2"] = self._semester_summary(months[6:])
            person["not_submitted_months"] = [m["period"] for m in months if m.get("report_status") == "NOT_SUBMITTED_VERIFIED"]
        return {"status": "ok", "year": year, "total": len(people), "rows": list(people.values())}

    @staticmethod
    def _semester_summary(months):
        filled = [m for m in months if m.get("predicate") or m.get("report_status") == "NOT_SUBMITTED_VERIFIED"]
        return {
            "months_available": len(filled),
            "approved": sum(m.get("review_status") == "APPROVED" for m in filled),
            "not_submitted": sum(m.get("report_status") == "NOT_SUBMITTED_VERIFIED" for m in filled),
            "low": sum(_predicate(m.get("predicate")) in {"KURANG", "SANGAT KURANG"} for m in filled),
        }

    def audit_detail(self, period: str, nip: str) -> dict[str, Any]:
        period = _period(period)
        with self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM skp_assessment_monthly WHERE assessment_period=? AND nip=?", [period, nip]
            ).fetchdf()
            audit = conn.execute(
                "SELECT * FROM skp_assessment_audit WHERE assessment_period=? AND nip=? ORDER BY created_at",
                [period, nip],
            ).fetchdf()
        if current.empty and audit.empty:
            raise KeyError("Penilaian SKP tidak ditemukan")
        return {"status": "ok", "assessment": self._records(current)[0] if not current.empty else None, "audit": self._records(audit)}

    def get_config(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM skp_rule_config WHERE id='DEFAULT'").fetchdf()
        return {"status": "ok", "config": self._records(row)[0]}

    def update_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = _predicate(payload.get("third_month_action")).replace(" ", "_")
        if action != "UNPAID":
            raise ValueError("Mulai bulan ketiga berturut-turut tidak membuat SKP, Tukin wajib tidak dibayarkan")
        actor = _text(payload.get("updated_by")) or "EVKIN"
        with self.connect() as conn:
            conn.execute(
                "UPDATE skp_rule_config SET third_month_action=?,third_month_rate=100,updated_by=?,updated_at=now() WHERE id='DEFAULT'",
                [action, actor],
            )
            try:
                years = [int(str(row[0])[:4]) for row in conn.execute(
                    "SELECT DISTINCT assessment_period FROM tukin_skp_monthly WHERE report_status='NOT_SUBMITTED_VERIFIED'"
                ).fetchall()]
            except duckdb.CatalogException:
                years = []
        if years:
            annual = importlib.import_module("backend.tukin_annual")
            annual_service = annual.TukinAnnualService(self.db_path)
            for year in years:
                annual_service.recompute_skp_streaks(year)
        return self.get_config()

    def export_annual(self, year: int, scope: str = "results", sheet_keys=None,
                      output_path: Optional[Path] = None):
        scope = _text(scope).lower() or "results"
        presets = {
            "summary": ["summary"],
            "results": ["summary", "detail"],
            "full": list(SKP_EXPORT_SHEETS),
            "approved": ["detail"],
        }
        selected = list(dict.fromkeys(sheet_keys or presets.get(scope, [])))
        invalid = [key for key in selected if key not in SKP_EXPORT_SHEETS]
        if invalid or not selected:
            raise ValueError("Pilih minimal satu sheet yang valid")
        data = self.annual(year)
        approved_only = scope == "approved"
        with self.connect() as conn:
            condition_frame = conn.execute(
                """SELECT * FROM skp_condition_decision
                   WHERE assessment_period BETWEEN ? AND ?
                   ORDER BY assessment_period,nip,condition_code""",
                [f"{year}-01", f"{year}-12"],
            ).fetchdf()
        condition_rows = self._records(condition_frame)
        conditions_by_person = {}
        for item in condition_rows:
            conditions_by_person.setdefault(
                (_text(item.get("assessment_period")), _text(item.get("nip"))), []
            ).append(item)
        summary, detail = [], []
        for person in data["rows"]:
            if "summary" in selected:
                summary.append({
                    "NIP": person["nip"], "Nama": person["nama"],
                    "Bulan Tidak Membuat SKP": ", ".join(person["not_submitted_months"]),
                    "Jumlah Tidak Membuat": len(person["not_submitted_months"]),
                    "Semester I Disetujui": person["semester_1"]["approved"],
                    "Semester I Nilai Rendah": person["semester_1"]["low"],
                    "Semester II Disetujui": person["semester_2"]["approved"],
                    "Semester II Nilai Rendah": person["semester_2"]["low"],
                })
            if "detail" in selected:
                for month in person["months"]:
                    if approved_only and month.get("review_status") != "APPROVED":
                        continue
                    if month.get("predicate") or month.get("report_status"):
                        conditions = conditions_by_person.get((month["period"], person["nip"]), [])
                        detail.append({"NIP": person["nip"], "Nama": person["nama"], "Periode": month["period"],
                                   "Predikat Final": month.get("predicate"),
                                   "Potongan SKP (%)": VALID_PREDICATES.get(_predicate(month.get("predicate")), 0),
                                   "Status Review": month.get("review_status"),
                                   "Status Laporan": month.get("report_status"),
                                   "HEK": month.get("hek_status"), "Target HEK": month.get("hek_target"), "Realisasi HEK": month.get("hek_actual"),
                                   "Verkom": month.get("verkom_status"), "Target Verkom": month.get("verkom_target"), "Realisasi Verkom": month.get("verkom_actual"),
                                   "Graduasi": month.get("graduasi_status"), "Target Graduasi": month.get("graduasi_target"), "Realisasi Graduasi": month.get("graduasi_actual"),
                                   "P2K2": month.get("p2k2_status"), "Target P2K2": month.get("p2k2_target"), "Realisasi P2K2": month.get("p2k2_actual"),
                                       "Alasan": month.get("reason"), "Eviden": month.get("evidence_ref"),
                                       "Batch Rapat": month.get("meeting_batch_id"),
                                       "Kondisi Khusus": ", ".join(_text(c.get("condition_code")) for c in conditions),
                                       "Efek Pembayaran": ", ".join(_text(c.get("payment_effect")) for c in conditions),
                                       "Dokumen Kondisi": ", ".join(_text(c.get("document_number")) for c in conditions),
                                       "Disetujui Oleh": month.get("approved_by"),
                                       "Waktu Persetujuan": month.get("approved_at")})
        extra_sheets = []
        if any(key in selected for key in ("meetings", "exceptions", "conditions", "configs")):
            with self.connect() as conn:
                if "meetings" in selected:
                    extra_sheets.append(("Keputusan Rapat", conn.execute(
                        "SELECT * FROM skp_meeting_batch WHERE assessment_period BETWEEN ? AND ? ORDER BY assessment_period,created_at",
                        [f"{year}-01", f"{year}-12"],
                    ).fetchdf()))
                if "exceptions" in selected:
                    extra_sheets.append(("Pengecualian", conn.execute(
                        "SELECT * FROM skp_assessment_exception WHERE assessment_period BETWEEN ? AND ? ORDER BY assessment_period,nip",
                        [f"{year}-01", f"{year}-12"],
                    ).fetchdf()))
                if "conditions" in selected:
                    extra_sheets.append(("Kondisi dan Hukdis", condition_frame))
                if "configs" in selected:
                    extra_sheets.append(("Versi Konfigurasi", conn.execute(
                        "SELECT * FROM skp_indicator_config WHERE effective_from<=? AND (effective_to IS NULL OR effective_to='' OR effective_to>=?) ORDER BY indicator_code,version",
                        [f"{year}-12", f"{year}-01"],
                    ).fetchdf()))
        output = output_path or io.BytesIO()
        # constant_memory writes rows sequentially and prevents large exports from
        # keeping a second full worksheet representation in server memory.
        with pd.ExcelWriter(output, engine="xlsxwriter",
                            engine_kwargs={"options": {"constant_memory": True}}) as writer:
            frames = []
            if "summary" in selected:
                frames.append(("Rekap Tahunan", pd.DataFrame(summary)))
            if "detail" in selected:
                frames.append(("Hasil Approved" if approved_only else "Detail Bulanan", pd.DataFrame(detail)))
            frames.extend(extra_sheets)
            for name, frame in frames:
                frame.to_excel(writer, sheet_name=name, index=False)
                sheet = writer.sheets[name]
                last_col = max(len(frame.columns) - 1, 0)
                sheet.freeze_panes(1, 1)
                sheet.autofilter(0, 0, max(len(frame), 1), last_col)
                sheet.set_column(0, 1, 24); sheet.set_column(2, 20, 22)
        if hasattr(output, "seek"):
            output.seek(0)
        return output


def _set_export_job(job_id: str, **values) -> None:
    with _EXPORT_JOBS_LOCK:
        if job_id in _EXPORT_JOBS:
            _EXPORT_JOBS[job_id].update(values)


from backend.runtime_guard import database_job


@database_job
def _run_export_job(job_id: str, db_path: str, year: int, sheets: list[str], result_path: Path) -> None:
    try:
        _set_export_job(job_id, status="running", progress=10, message="Menyiapkan data SKP")
        SkpAssessmentService(db_path).export_annual(year, sheet_keys=sheets, output_path=result_path)
        _set_export_job(job_id, status="finished", progress=100,
                        message="File siap diunduh", finished_at=datetime.now().isoformat())
    except Exception as exc:
        result_path.unlink(missing_ok=True)
        _set_export_job(job_id, status="failed", progress=0, message=str(exc),
                        finished_at=datetime.now().isoformat())


def create_router(db_path_getter: Callable[[], str]) -> APIRouter:
    router = APIRouter(prefix="/api/skp-assessment", tags=["skp-assessment"])
    service = lambda: SkpAssessmentService(db_path_getter())

    @router.post("/preview")
    def preview(payload: dict[str, Any]):
        try: return service().preview(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/import")
    def import_rows(payload: dict[str, Any]):
        try: return service().import_rows(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/rows")
    def rows(assessment_period: str, q: str = "", review_status: str = "", indicator: str = "",
             indicator_status: str = "", page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=500)):
        return service().list_rows(assessment_period, q, review_status, indicator, indicator_status, page, per_page)

    @router.get('/import-batches')
    def import_batches(assessment_period: str):
        try: return service().list_import_batches(assessment_period)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @router.post('/removal/preview')
    def preview_removal(payload: dict[str, Any]):
        try: return service().preview_removal(payload)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @router.post('/removal/confirm')
    def confirm_removal(payload: dict[str, Any]):
        try: return service().remove_assessments(payload)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @router.post("/recommend")
    def recommend(payload: dict[str, Any]):
        try: return service().bulk_recommend(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/indicator-config")
    def indicator_config(period: str = ""):
        try: return service().list_indicator_configs(period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/indicator-config")
    def save_indicator_config(payload: dict[str, Any]):
        try: return service().save_indicator_config(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/rules")
    def assessment_rules(period: str = ""):
        try: return service().list_assessment_rules(period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/rules")
    def save_assessment_rule(payload: dict[str, Any]):
        try: return service().save_assessment_rule(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/non-submission-rules")
    def non_submission_rules(period: str = ""):
        try: return service().non_submission_rules(period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/non-submission-rules")
    def save_non_submission_rules(payload: dict[str, Any]):
        try: return service().save_non_submission_rules(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete('/indicator-config/{config_id}')
    def delete_indicator_config(config_id: str, payload: dict[str, Any]):
        try: return service().delete_indicator_config(config_id, payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/exceptions")
    def exceptions(assessment_period: str):
        try: return service().list_exceptions(assessment_period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/exceptions")
    def save_exception(payload: dict[str, Any]):
        try: return service().save_exception(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/conditions")
    def conditions(assessment_period: str):
        try: return service().list_condition_decisions(assessment_period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/conditions")
    def save_condition(payload: dict[str, Any]):
        try: return service().save_condition_decision(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/review")
    def review(payload: dict[str, Any]):
        try: return service().review(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/summary")
    def summary(assessment_period: str):
        try: return service().period_summary(assessment_period)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/finalize")
    def finalize(payload: dict[str, Any]):
        try: return service().finalize_period(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/annual")
    def annual(year: int = Query(2026, ge=2000, le=2100), q: str = ""):
        return service().annual(year, q)

    @router.get("/audit/{assessment_period}/{nip}")
    def audit(assessment_period: str, nip: str):
        try: return service().audit_detail(assessment_period, nip)
        except KeyError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/config")
    def config(): return service().get_config()

    @router.post("/config")
    def update_config(payload: dict[str, Any]):
        try: return service().update_config(payload)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/export/annual")
    def export_annual(year: int = Query(2026, ge=2000, le=2100),
                      scope: str = Query("results")):
        try: stream = service().export_annual(year, scope)
        except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
        suffix = {"summary": "RINGKASAN", "results": "HASIL", "full": "LENGKAP",
                  "approved": "APPROVED"}.get(scope, "HASIL")
        return StreamingResponse(stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="REKAP_SKP_{year}_{suffix}.xlsx"'})

    @router.post("/export/jobs")
    def create_export_job(payload: dict[str, Any]):
        year = int(payload.get("year") or 2026)
        if year < 2000 or year > 2100:
            raise HTTPException(status_code=400, detail="Tahun tidak valid")
        sheets = list(dict.fromkeys(payload.get("sheets") or []))
        if not sheets or any(key not in SKP_EXPORT_SHEETS for key in sheets):
            raise HTTPException(status_code=400, detail="Pilih minimal satu sheet yang valid")
        job_id = uuid.uuid4().hex
        export_dir = Path(db_path_getter()).resolve().parent / "exports" / "skp"
        export_dir.mkdir(parents=True, exist_ok=True)
        result_path = export_dir / f"{job_id}.xlsx"
        filename = f"REKAP_SKP_{year}_{len(sheets)}_SHEET.xlsx"
        with _EXPORT_JOBS_LOCK:
            _EXPORT_JOBS[job_id] = {
                "job_id": job_id, "status": "queued", "progress": 0,
                "message": "Menunggu proses", "year": year, "sheets": sheets,
                "filename": filename, "result_path": str(result_path),
                "created_at": datetime.now().isoformat(),
            }
        _EXPORT_EXECUTOR.submit(_run_export_job, job_id, db_path_getter(), year, sheets, result_path)
        return {"status": "queued", "job_id": job_id}

    @router.get("/export/jobs/{job_id}")
    def export_job_status(job_id: str):
        with _EXPORT_JOBS_LOCK:
            job = dict(_EXPORT_JOBS.get(job_id) or {})
        if not job:
            raise HTTPException(status_code=404, detail="Job ekspor tidak ditemukan")
        job.pop("result_path", None)
        if job["status"] == "finished":
            job["download_url"] = f"/api/skp-assessment/export/jobs/{job_id}/download"
        return job

    @router.get("/export/jobs/{job_id}/download")
    def download_export_job(job_id: str):
        with _EXPORT_JOBS_LOCK:
            job = dict(_EXPORT_JOBS.get(job_id) or {})
        if not job:
            raise HTTPException(status_code=404, detail="Job ekspor tidak ditemukan")
        if job["status"] != "finished" or not Path(job["result_path"]).is_file():
            raise HTTPException(status_code=409, detail="File belum siap diunduh")
        return FileResponse(job["result_path"], filename=job["filename"],
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return router
