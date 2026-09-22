"""Append-only archive and comparison service for Master Pengembalian.

This module is intentionally independent of the legacy RETURN workflow.  It
stores immutable source rows in DATA_AWAL and DATA_PENYESUAIAN and keeps
comparison output (including duplicate records) auditable.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from contextlib import contextmanager
import time
import uuid
import hashlib
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import duckdb
import pandas as pd

try:
    from .duckdb_maintenance import (clear_tables_without_secondary_indexes,
        delete_where_without_secondary_indexes, is_invalidated_duckdb_error)
except ImportError:  # pragma: no cover - direct module execution compatibility
    from duckdb_maintenance import (clear_tables_without_secondary_indexes,
        delete_where_without_secondary_indexes, is_invalidated_duckdb_error)


SOURCE_AWAL = "DATA_AWAL"
SOURCE_PENYESUAIAN = "DATA_PENYESUAIAN"
SOURCE_FINAL = "DATA_FINAL"
SOURCES = (SOURCE_AWAL, SOURCE_PENYESUAIAN)
COMPONENTS = (
    "total_tukin",
    "tukin_absen_30",
    "tukin_skp_70",
    "potongan_skp",
    "esdm",
    "e_absensi",
    "tendik",
    "total_potongan_absen",
    "total_potongan_tukin",
)
BNBA_EXTENDED_COLUMNS = (
    "nama_sdm", "kode_anak_satker", "tahun_sp2d_sebelumnya", "tahun_sp2d_update",
    "status_sp2d", "tukin_pengembalian_oktober", "tukin_pengembalian_november",
    "tukin_pengembalian_desember", "total_awal_tukin",
    "final_pengembalian_tukin_oktober", "final_pengembalian_tukin_november",
    "final_pengembalian_tukin_desember", "final_total_pengembalian_tukin",
    "pengembalian_uang_makan_oktober", "pengembalian_uang_makan_november",
    "pengembalian_uang_makan_desember", "final_total_pengembalian_uang_makan",
    "final_total_pengembalian_tukin_uang_makan", "batas_usia_pensiun",
    "status_pengembalian_tukin_uang_makan", "cluster_tukin", "cluster_uang_makan",
    "cluster_total", "batch_oktober_raw", "batch_november_raw", "batch_desember_raw",
    "final_batch_raw", "nama_bank", "nama_direk", "selisih_oktober",
    "flag_perubahan_oktober", "selisih_november", "flag_perubahan_november",
    "selisih_desember", "flag_perubahan_desember", "selisih_total_tukin",
    "flag_perubahan_total", "flag_ada_perubahan", "arah_perubahan",
    "batch_oktober_normalized", "batch_november_normalized",
    "batch_desember_normalized", "final_batch_normalized",
)
# Public contract for BNBA consumers: these source fields are normalized into
# stable keys and the complete original row is retained in ``raw_data``.
BNBA_SOURCE_COLUMNS = (
    "nip", "nama", "tahun_sp2d", "nomor_sp2d", "tahun", "bulan", "periode",
    "batch", "komponen", "total_tukin", "total_potongan_absen",
    "total_potongan_tukin", "source_record_id", "source_file", "source_sheet",
    "provinsi", "kabupaten_kota", "kdanaksatker", "jabatan",
    "golongan", "status", "npwp",
)
VALIDATION_VALID = "VALID"
VALIDATION_INVALID = "TIDAK SESUAI"
VALIDATION_UNKNOWN = "TIDAK DAPAT DIVALIDASI"
SOURCE_UNKNOWN = "SUMBER PERUBAHAN TIDAK TERIDENTIFIKASI"
DATASET_TYPES = {"DATA_AWAL", "DATA_PENYESUAIAN", "DATA_FINAL", "DATA_DASAR_PERHITUNGAN"}
BPK_STATUSES = {"BELUM SEND BPK", "SEND BPK BATCH 1", "SEND BPK BATCH 2",
                "SEND BPK BATCH LAINNYA"}

_ALIASES = {
    "nip": ("nip", "no_nip", "nomor_nip", "no_pegawai", "nomor_pegawai"),
    "nama": ("nama", "nama_pegawai", "nama_lengkap", "nama_sk"),
    "periode_id": ("periode_id", "period_id", "id_periode"),
    "nama_sdm": ("nama_sdm", "nama_sk", "nama", "nama_pegawai"),
    "kode_anak_satker": ("kode_anak_satker", "kdanak_satker", "kd_anak_satker", "kode_satker"),
    "tahun_sp2d_sebelumnya": ("tahun_sp2d_sebelumnya", "tahun_sp2d_seblumnya", "tahun_sp2d_lama"),
    "tahun_sp2d_update": ("tahun_sp2d_update", "tahun_sp2d", "tahunsp2d"),
    "status_sp2d": ("status_sp2d", "status_sp2d_update"),
    "tahun_sp2d": ("tahun_sp2d", "tahunsp2d", "sp2d_tahun", "thn_sp2d"),
    "nomor_sp2d": ("nomor_sp2d", "nomorsp2d", "no_sp2d", "sp2d"),
    "tahun": ("tahun", "thn", "year"),
    "bulan": ("bulan", "bln", "month"),
    "periode": ("periode", "period", "tahun_bulan", "tahunbulan", "year_month"),
    # ``batch`` is the single source of truth for Batch BPK. Header variants
    # are aliases only; no parallel batch_bpk field is persisted.
    "batch": ("batch", "batch_bpk", "batch_id", "no_batch", "nomor_batch", "batch_number"),
    "komponen": ("komponen", "component", "komponen_tukin", "jenis_komponen", "jenis"),
    "total_tukin": (
        "total_tukin", "nominal_tukin", "tukin_total", "total", "nominal_awal",
        "nominal_penyesuaian", "nilai_tukin", "nominal",
    ),
    "tukin_pengembalian_oktober": ("tukin_pengembalian_oktober", "tukin_pengembalian_okt"),
    "tukin_pengembalian_november": ("tukin_pengembalian_november", "tukin_pengembalian_nov"),
    "tukin_pengembalian_desember": ("tukin_pengembalian_desember", "tukin_pengembalian_des"),
    "total_awal_tukin": ("total_awal_tukin", "total_awal"),
    "final_pengembalian_tukin_oktober": ("final_pengembalian_tukin_oktober", "final_pengembalian_tukin_okt"),
    "final_pengembalian_tukin_november": ("final_pengembalian_tukin_november", "final_pengembalian_tukin_nov"),
    "final_pengembalian_tukin_desember": ("final_pengembalian_tukin_desember", "final_pengembalian_tukin_des"),
    "final_total_pengembalian_tukin": ("final_total_pengembalian_tukin", "final_total_tukin"),
    "pengembalian_uang_makan_oktober": ("pengembalian_uang_makan_oktober", "uang_makan_oktober"),
    "pengembalian_uang_makan_november": ("pengembalian_uang_makan_november", "uang_makan_november"),
    "pengembalian_uang_makan_desember": ("pengembalian_uang_makan_desember", "uang_makan_desember"),
    "final_total_pengembalian_uang_makan": ("final_total_pengembalian_uang_makan", "total_uang_makan"),
    "final_total_pengembalian_tukin_uang_makan": ("final_total_pengembalian_tukin_uang_makan", "total_pengembalian_tukin_uang_makan"),
    "batas_usia_pensiun": ("batas_usia_pensiun", "batas_usia_pensiun"),
    "status_pengembalian_tukin_uang_makan": ("status_pengembalian_tukin_uang_makan", "status_pengembalian"),
    "cluster_tukin": ("cluster_tukin",),
    "cluster_uang_makan": ("cluster_uang_makan",),
    "cluster_total": ("cluster_total",),
    "batch_oktober_raw": ("kroscek_send_bpk_oktober_tukin", "batch_oktober_raw"),
    "batch_november_raw": ("kroscek_send_bpk_november_tukin", "batch_november_raw"),
    "batch_desember_raw": ("kroscek_send_bpk_desember_tukin", "batch_desember_raw"),
    "final_batch_raw": ("final_bacth_tahap_1", "final_batch_raw", "final_batch_tahap_1"),
    # The source workbook intentionally spells this column ``Flaging``.
    # Keep common spelling variants so the final dashboard can use that
    # business classification instead of re-inferring it from nominal deltas.
    "flag_ada_perubahan": (
        "flaging", "flagging", "flag_ada_perubahan", "ada_perubahan",
        "status_perubahan",
    ),
    "nama_bank": ("nama_bank", "bank", "nama_bank"),
    "nomor_rekening": ("nomor_rekening", "nomer_rekening", "no_rekening", "rekening"),
    "nama_direk": ("nama_direk", "direk"),
    "tukin_absen_30": (
        "tukin_absen_30", "tukin_absen_30_persen", "tukin_absen_30%", "absen_30",
        "tukin_absensi_30", "tukin_absensi_30_persen",
    ),
    "tukin_skp_70": (
        "tukin_skp_70", "tukin_skp_70_persen", "skp_70", "tukin_skp_70%",
        "tukin_skp_70_persen",
    ),
    "potongan_skp": ("potongan_skp", "potongan_skp_70", "skp_potongan", "pot_skp"),
    "esdm": ("esdm", "potongan_esdm"),
    "e_absensi": ("e_absensi", "e-absensi", "eabsensi", "potongan_e_absensi", "potongan_eabsensi"),
    "tendik": ("tendik", "potongan_tendik"),
    "total_potongan_absen": (
        "total_potongan_absen", "potongan_absen_total", "total_potongan_absensi",
    ),
    "total_potongan_tukin": (
        "total_potongan_tukin", "potongan_tukin_total", "total_pengembalian",
        "total_pengembalian_awal", "total_pengembalian_final",
        "nilai_pengembalian", "nominal_pengembalian", "pengembalian",
    ),
    "daily_ref": ("daily_ref", "harian_ref", "daily_id", "hitung_harian_id", "hitung_harian", "daily"),
    "monthly_ref": ("monthly_ref", "bulanan_ref", "monthly_id", "rekap_bulanan_id", "rekap_bulanan", "monthly"),
    "absence_ref": ("absence_ref", "absensi_ref", "absence_id", "final_absensi_id", "final_absensi", "absence"),
    "total_tukin_ref": ("total_tukin_ref", "tukin_ref", "total_tukin_id", "total_tukin_record_id"),
    "source_record_id": ("source_record_id", "record_id", "id", "source_id"),
    "source_file": ("source_file", "filename", "file_name", "nama_file"),
    "source_sheet": ("source_sheet", "sheet", "sheet_name"),
    "provinsi": ("provinsi", "province", "propinsi"),
    "kabupaten_kota": ("kabupaten_kota", "kabupaten", "kota", "kab_kota"),
    "kdanaksatker": ("kdanaksatker", "kd_anak_satker", "kode_anak_satker", "kode_satker"),
    "unit_kerja": ("unit_kerja", "unit", "satuan_kerja", "satker"),
    "jabatan": ("jabatan", "position"),
    "golongan": ("golongan", "pangkat_golongan"),
    "status": ("status", "status_pegawai", "status_kepegawaian"),
    "npwp": ("npwp", "nomor_npwp"),
    "nomor_rekening": ("nomor_rekening", "no_rekening", "rekening"),
    "kode_bank": ("kode_bank", "bank_code"),
    "keterangan": ("keterangan", "catatan", "remarks"),
}
IMPORT_MODES = {"APPEND", "UPSERT"}
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY = set()


@contextmanager
def _schema_file_lock(db_path: str):
    """Serialize migrations across multiple uvicorn worker processes."""
    if os.name != "nt":
        yield
        return
    import msvcrt
    lock_path = f"{db_path}.schema.lock"
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.1)
        yield
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()

_NUMERIC = {
    "tahun_sp2d", "tahun", "bulan", "tahun_sp2d_sebelumnya", "tahun_sp2d_update",
    "batas_usia_pensiun", *COMPONENTS,
    "tukin_pengembalian_oktober", "tukin_pengembalian_november",
    "tukin_pengembalian_desember", "total_awal_tukin",
    "final_pengembalian_tukin_oktober", "final_pengembalian_tukin_november",
    "final_pengembalian_tukin_desember", "final_total_pengembalian_tukin",
    "pengembalian_uang_makan_oktober", "pengembalian_uang_makan_november",
    "pengembalian_uang_makan_desember", "final_total_pengembalian_uang_makan",
    "final_total_pengembalian_tukin_uang_makan",
}

# Only leaf/source amounts are rounded independently. Aggregate columns are
# rebuilt from their rounded details below, so downstream consumers never
# perform a second rounding pass.
ROUNDING_DETAIL_FIELDS = (
    *COMPONENTS,
    "tukin_pengembalian_oktober", "tukin_pengembalian_november",
    "tukin_pengembalian_desember", "final_pengembalian_tukin_oktober",
    "final_pengembalian_tukin_november", "final_pengembalian_tukin_desember",
    "pengembalian_uang_makan_oktober", "pengembalian_uang_makan_november",
    "pengembalian_uang_makan_desember",
)
ROUNDING_DERIVED_FIELDS = (
    "total_awal_tukin", "final_total_pengembalian_tukin",
    "final_total_pengembalian_uang_makan",
    "final_total_pengembalian_tukin_uang_makan",
)


def _decimal_number(value: Any) -> Optional[Decimal]:
    """Parse source money without binary floating-point arithmetic."""
    cleaned = _clean(value)
    if cleaned is None or isinstance(cleaned, bool):
        return None
    if isinstance(cleaned, Decimal):
        number = cleaned
    elif isinstance(cleaned, (int, float)):
        if isinstance(cleaned, float) and not math.isfinite(cleaned):
            return None
        number = Decimal(str(cleaned))
    else:
        text = re.sub(r"[^0-9,.+\-]", "", str(cleaned).strip().replace(" ", ""))
        if not text:
            return None
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        elif re.fullmatch(r"[+\-]?\d{1,3}(?:\.\d{3})+", text):
            text = text.replace(".", "")
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
    return number if number.is_finite() else None


def sum_preserving_round(values: Sequence[Any], stable_keys: Optional[Sequence[Any]] = None,
                         target_total: Optional[int] = None) -> Dict[str, Any]:
    """Largest-remainder rounding with hard zero/null/integer constraints."""
    decimals = [_decimal_number(value) for value in values]
    keys = list(stable_keys or range(len(values)))
    if len(keys) != len(values):
        raise ValueError("stable_keys harus sama panjang dengan values")
    raw_total = sum((value for value in decimals if value is not None), Decimal(0))
    target = (int(raw_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
              if target_total is None else int(target_total))
    rounded = [None if value is None else int(value.to_integral_value(rounding=ROUND_FLOOR))
               for value in decimals]
    eligible = [index for index, value in enumerate(decimals)
                if value is not None and value != 0 and value != value.to_integral_value()]
    difference = target - sum(value for value in rounded if value is not None)
    if abs(difference) > len(eligible):
        raise ValueError("ROUNDING_RECONCILIATION_FAILED: kandidat desimal tidak mencukupi")
    if difference > 0:
        order = sorted(eligible, key=lambda i: (-(decimals[i] - Decimal(rounded[i])), str(keys[i])))
        for index in order[:difference]:
            rounded[index] += 1
    elif difference < 0:
        order = sorted(eligible, key=lambda i: ((decimals[i] - Decimal(rounded[i])), str(keys[i])))
        for index in order[:abs(difference)]:
            rounded[index] -= 1
    rounded_total = sum(value for value in rounded if value is not None)
    zero_modified = sum(1 for raw, value in zip(decimals, rounded) if raw == 0 and value != 0)
    if rounded_total != target:
        raise ValueError("ROUNDING_RECONCILIATION_FAILED")
    if zero_modified:
        raise ValueError("ROUNDING_ZERO_VALUE_VIOLATION")
    return {
        "values": rounded, "raw_total": raw_total, "target_total": target,
        "rounded_total": rounded_total, "difference": target - rounded_total,
        "decimal_record_count": len(eligible),
        "adjusted_record_count": sum(
            1 for index in eligible if rounded[index] != int(decimals[index].to_integral_value(rounding=ROUND_FLOOR))
        ),
        "zero_modified_count": zero_modified,
    }
def _key_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    # DuckDB/pandas may return numpy scalar values, which the JSON encoder
    # cannot serialize even though their Python counterparts are serializable.
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _number(value: Any) -> Optional[float]:
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = re.sub(r"[^0-9,.+\-]", "", text)
    # Accept both Indonesian 1.234,56 and ordinary 1234.56 notation.
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif re.fullmatch(r"[+\-]?\d{1,3}(?:\.\d{3})+", text):
        # Indonesian thousands separator without a decimal comma.
        text = text.replace(".", "")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _rupiah(value: Any) -> Optional[int]:
    """Normalize a monetary value to integer Rupiah for stable comparison."""
    number = _number(value)
    return None if number is None else int(round(number))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_load(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _normalize_bnba_batch(value: Any) -> Optional[str]:
    text = _key_name(value)
    if not text:
        return None
    if "tahap_2" in text:
        return "TAHAP 2"
    batch_match = re.fullmatch(r"(?:batch_?|b)?(\d+)", text)
    if batch_match:
        return f"BATCH {int(batch_match.group(1))}"
    if "tidak_pengembalian" in text:
        return "TIDAK PENGEMBALIAN"
    return str(value).strip().upper()


def _normalize_change_flag(value: Any) -> Optional[str]:
    """Normalize the workbook's Flaging value to the dashboard contract."""
    text = re.sub(r"\s+", " ", str(value or "").strip().upper().replace("_", " "))
    if not text:
        return None
    if text in {"YA", "Y", "YES", "1", "TRUE", "ADA PERUBAHAN", "BERUBAH"}:
        return "BERUBAH"
    if text in {
        "TIDAK", "TIDAK ADA", "TIDAK ADA PERUBAHAN", "TIDAK BERUBAH",
        "N", "NO", "0", "FALSE",
    }:
        return "TIDAK BERUBAH"
    return None


def _source_change_flag(row: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Read an explicitly supplied Flaging value, including archived raw rows."""
    if not row:
        return None
    direct = _normalize_change_flag(row.get("_source_flag_ada_perubahan"))
    if direct:
        return direct
    normalized_projection = _json_load(row.get("bnba_normalized"))
    if isinstance(normalized_projection, Mapping):
        projected = _normalize_change_flag(normalized_projection.get("flag_ada_perubahan"))
        if projected:
            return projected
    raw = row.get("raw_data") or row.get("_raw_data") or {}
    if not isinstance(raw, Mapping):
        return None
    normalized = {_key_name(key): value for key, value in raw.items()}
    for alias in _ALIASES["flag_ada_perubahan"]:
        key = _key_name(alias)
        if key in normalized:
            flag = _normalize_change_flag(normalized[key])
            if flag:
                return flag
    return None


_MONTH_NAME_MAP = {
    "jan": "01", "januari": "01", "january": "01",
    "feb": "02", "februari": "02", "february": "02",
    "mar": "03", "maret": "03", "march": "03",
    "apr": "04", "april": "04",
    "mei": "05", "may": "05",
    "jun": "06", "juni": "06", "june": "06",
    "jul": "07", "juli": "07", "july": "07",
    "aug": "08", "agustus": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "okt": "10", "oktober": "10", "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "des": "12", "desember": "12", "dec": "12", "december": "12",
}


def _normalize_period(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    match = re.search(r"(\d{4})\D*(\d{1,2})(?:\D*(\d{1,2}))?", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12:
            return f"{year}-{month:02d}"
    year_match = re.search(r"(\d{4})", text)
    if year_match:
        year = int(year_match.group(1))
        lower = text.lower().replace(" ", "")
        for month_name, month_num in sorted(_MONTH_NAME_MAP.items(), key=lambda item: len(item[0]), reverse=True):
            if month_name in lower:
                return f"{year}-{month_num}"
    lower = text.lower().replace(" ", "")
    for month_name, month_num in _MONTH_NAME_MAP.items():
        if lower == month_name or month_name in lower:
            return text
    return text


def _infer_period_id_from_rows(rows: Iterable[Mapping[str, Any]]) -> Optional[str]:
    candidates = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        lookup = {_key_name(k): v for k, v in row.items()}
        for key in ("periode_id", "period_id", "id_periode"):
            value = lookup.get(key)
            if value:
                candidates.append(str(value).strip())
                break
        else:
            period = lookup.get("periode") or lookup.get("period") or lookup.get("tahun_bulan") or lookup.get("year_month")
            if period:
                candidates.append(str(period).strip())
                continue
            year = lookup.get("tahun") or lookup.get("tahun_sp2d")
            month = lookup.get("bulan") or lookup.get("month")
            if year is not None and month is not None:
                try:
                    month_int = int(month)
                    year_int = int(year)
                except (TypeError, ValueError):
                    continue
                if 1 <= month_int <= 12:
                    candidates.append(f"{year_int}-{month_int:02d}")
    if not candidates:
        return None
    counts = {}
    for value in candidates:
        normalized = _normalize_period(value)
        if not normalized:
            continue
        if normalized.startswith("RET-"):
            counts[normalized] = counts.get(normalized, 0) + 1
        elif re.fullmatch(r"\d{4}-\d{2}", str(normalized)):
            period_id = f"RET-{normalized}-{normalized.split('-')[1]}"
            counts[period_id] = counts.get(period_id, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _is_valid_period(value: Any) -> bool:
    normalized = _normalize_period(value)
    if normalized is None:
        return False
    return bool(re.fullmatch(r"\d{4}[-/\s]\d{1,2}", str(normalized)))


def _canonical_source(source: str) -> str:
    value = _key_name(source).upper()
    if value in {"AWAL", "DATA_AWAL", "DATAAWAL"}:
        return SOURCE_AWAL
    if value in {"PENYESUAIAN", "DATA_PENYESUAIAN", "DATAPENYESUAIAN", "ADJUSTMENT"}:
        return SOURCE_PENYESUAIAN
    if value in {"FINAL", "DATA_FINAL", "DATAFINAL"}:
        return "DATA_FINAL"
    raise ValueError("source harus DATA_AWAL atau DATA_PENYESUAIAN")


def _filter_values(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = str(value).split(",") if isinstance(value, str) else [value]
    return [item.strip() if isinstance(item, str) else item
            for item in values if item not in (None, "")]


_MONTH_NUMBERS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "agu": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
}


def _month_number(*values: Any) -> Optional[int]:
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = int(value)
            if 1 <= number <= 12:
                return number
        except (TypeError, ValueError):
            pass
        normalized = _key_name(value)
        for token, number in _MONTH_NUMBERS.items():
            if token in normalized.split("_") or token in normalized:
                return number
    return None


class ArchiveRepository:
    """Small DuckDB repository.  It never issues UPDATE/DELETE on source rows."""

    def __init__(self, db_path: Optional[str] = None, connection=None):
        self.db_path = str(db_path or os.environ.get("EVKIN_DUCKDB_PATH") or
                           Path(__file__).resolve().parent / "data" / "EVKIN_MASTER.duckdb")
        self._connection = connection
        self._owns_connection = connection is None

    def connect(self):
        if self._connection is not None:
            try:
                self._connection.execute("SELECT 1").fetchone()
                return self._connection
            except Exception as exc:
                if not is_invalidated_duckdb_error(exc):
                    raise
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None
        conn = duckdb.connect(self.db_path)
        if self._owns_connection:
            self._connection = conn
        return conn

    def close(self, conn):
        if self._owns_connection and conn is not None:
            try:
                conn.close()
            finally:
                self._connection = None

    def clear_database(self) -> Dict[str, Any]:
        """Clear Master imports, periods, derived final data, and repayment progress.

        Progress is derived from the imported master/final rows.  Keeping it when the
        master is reset would leave orphaned obligations and debit history that no
        longer has a valid source.  The shared maintenance helper performs the row
        deletion in one transaction and restores every secondary index afterwards.
        """
        self.ensure_schema()
        conn = self.connect()
        tables = [
            # Progress children must be emptied before their batch/obligation source.
            "pengembalian_progress_staging",
            "pengembalian_progress_transaction",
            "pengembalian_progress_import_batch",
            "pengembalian_progress_bulanan",
            "pengembalian_payment_transaction",
            "pengembalian_sp2d_lineage",
            "pengembalian_master_obligation",
            "pengembalian_obligation",
            # Final and archive data imported into Master Pengembalian.
            "pengembalian_final",
            "pengembalian_archive_dataset_row",
            "pengembalian_archive_dataset",
            "pengembalian_dasar_kalkulasi_absensi",
            "pengembalian_dasar_rekap_absensi",
            "pengembalian_archive_compare_detail",
            "pengembalian_archive_compare",
            "pengembalian_archive_bpk_history",
            "pengembalian_archive_data_awal",
            "pengembalian_archive_data_penyesuaian",
            "pengembalian_archive_import",
            # Canonical monthly Master Pengembalian source history.
            "pengembalian_monthly_source_row",
            "pengembalian_monthly_master",
            "pengembalian_monthly_import",
            "pengembalian_dasar_harian_compare",
            "pengembalian_dasar_harian_awal",
            "pengembalian_dasar_harian_penyesuaian",
            "pengembalian_tukin_history",
            "pengembalian_tukin_case",
            # Period configuration belongs to Master Pengembalian and must not
            # survive a full Master reset. Keep it last for future FK safety.
            "pengembalian_period",
        ]
        try:
            return clear_tables_without_secondary_indexes(conn, tables)
        finally:
            self.close(conn)

    def ensure_schema(self):
        with _SCHEMA_LOCK, _schema_file_lock(self.db_path):
            if self.db_path in _SCHEMA_READY:
                return
            # Import migrations without relying on their module import names.
            import importlib.util
            migrations = (
                ("023_create_pengembalian_archive_compare.py", "pengembalian_archive_migration"),
                ("028_create_pengembalian_progress.py", "pengembalian_progress_migration"),
                ("026_extend_pengembalian_bnba_schema.py", "bnba_archive_migration"),
                ("029_create_pengembalian_archive_v2.py", "pengembalian_archive_v2_migration"),
                ("030_create_pengembalian_progress_v2.py", "pengembalian_progress_v2_migration"),
                ("031_optimize_pengembalian_progress_import.py", "pengembalian_progress_import_migration"),
                ("032_add_pengembalian_batch_dashboard_indexes.py", "pengembalian_batch_dashboard_migration"),
                ("033_create_multi_period_master.py", "pengembalian_multi_period_migration"),
                ("040_create_pengembalian_dasar_rekap.py", "pengembalian_dasar_rekap_migration"),
            )
            for filename, module_name in migrations:
                migration_path = Path(__file__).resolve().parent / "migrations" / filename
                spec = importlib.util.spec_from_file_location(module_name, migration_path)
                migration = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration)
                migration.main(self.db_path)
            _SCHEMA_READY.add(self.db_path)

    @staticmethod
    def table_for(source: str) -> str:
        source = _canonical_source(source)
        return ("pengembalian_archive_data_awal" if source == SOURCE_AWAL
                else "pengembalian_archive_data_penyesuaian")

    def insert_import(self, metadata: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                      source: str, imported_by: str = "system") -> str:
        source = _canonical_source(source)
        if source == SOURCE_FINAL:
            raise ValueError("DATA_FINAL adalah projection turunan dan tidak dapat diimport")
        self.ensure_schema()
        conn = self.connect()
        import_id = str(uuid.uuid4())
        metadata = dict(metadata)
        dataset_type = str(metadata.get("dataset_type") or source).upper()
        send_bpk_status = str(metadata.get("send_bpk_status") or "BELUM SEND BPK").upper()
        if dataset_type not in DATASET_TYPES:
            raise ValueError("dataset_type tidak dikenal")
        if send_bpk_status not in BPK_STATUSES:
            raise ValueError("send_bpk_status tidak dikenal")
        bpk_batch = metadata.get("bpk_batch")
        if send_bpk_status.startswith("SEND BPK") and send_bpk_status != "SEND BPK BATCH LAINNYA":
            bpk_batch = int(send_bpk_status.rsplit(" ", 1)[-1])
        if send_bpk_status == "BELUM SEND BPK":
            bpk_batch = None
        try:
            existing = conn.execute(
                """SELECT import_id FROM pengembalian_archive_import
                   WHERE source_type = ? AND COALESCE(file_hash, '') = COALESCE(?, '')
                   AND COALESCE(file_hash, '') <> ''
                   AND COALESCE(periode_id,'')=COALESCE(?,'') LIMIT 1""",
                [source, metadata.get("file_hash"), metadata.get("periode_id")],
            ).fetchone()
            if existing:
                raise ValueError(f"IMPORT IDENTIK SUDAH ADA: {existing[0]}")
            conn.execute("BEGIN")
            conn.execute(
                """UPDATE pengembalian_archive_import
                   SET is_active=FALSE, status='INACTIVE'
                   WHERE source_type=? AND COALESCE(periode_id,'')=COALESCE(?,'')""",
                [source, metadata.get("periode_id")],
            )
            conn.execute(
                """INSERT INTO pengembalian_archive_import
                (import_id, source_type, filename, file_hash, metadata, periode_id, imported_at,
                 imported_by, row_count, valid_count, invalid_count, status,
                 dataset_type, send_bpk_status, bpk_batch, tanggal_send_bpk,
                 source_file_name, archive_version, is_active)
                VALUES (?, ?, ?, ?, ?, ?, now(), ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, TRUE)""",
                [import_id, source, metadata.get("filename") or metadata.get("nama_file"),
                 metadata.get("file_hash"), _json(dict(metadata)), metadata.get("periode_id"), imported_by,
                 len(rows), sum(1 for r in rows if not r.get("_schema_invalid")),
                 sum(1 for r in rows if r.get("_schema_invalid")), dataset_type,
                 send_bpk_status, bpk_batch, metadata.get("tanggal_send_bpk"),
                 metadata.get("source_file_name") or metadata.get("filename"),
                 metadata.get("archive_version") or metadata.get("version")],
            )
            table = self.table_for(source)
            columns = [
                "row_id", "import_id", "source_type", "source_row", "nip", "nama",
                "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun", "bulan", "periode", "batch",
                "komponen", *COMPONENTS, "source_record_id", "source_file", "source_sheet",
                "daily_ref", "monthly_ref", "absence_ref", "total_tukin_ref",
                "provinsi", "kabupaten_kota", "kdanaksatker",
                "unit_kerja", "jabatan", "golongan", "status", "npwp", "nomor_rekening",
                "kode_bank", "keterangan", *BNBA_EXTENDED_COLUMNS,
                "validation_flags", "tukin_validation",
                "calculated_total_potongan_absen", "calculated_total_potongan_tukin",
                "normalized_batch", "is_monthly", "is_total", "bnba_normalized", "raw_data",
            ]
            placeholders = ",".join("?" for _ in columns)
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
            for row in rows:
                values = [str(uuid.uuid4()), import_id, source, row.get("_source_row")]
                values.extend(row.get(c) for c in (
                    "nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun",
                    "bulan", "periode", "batch", "komponen",
                ))
                values.extend(row.get(c) for c in COMPONENTS)
                values.extend(row.get(c) for c in (
                    "source_record_id", "source_file", "source_sheet",
                    "daily_ref", "monthly_ref", "absence_ref", "total_tukin_ref",
                    "provinsi", "kabupaten_kota", "kdanaksatker",
                    "unit_kerja", "jabatan", "golongan", "status", "npwp", "nomor_rekening",
                    "kode_bank", "keterangan",
                ))
                values.extend(row.get(c) for c in BNBA_EXTENDED_COLUMNS)
                values.extend([_json(row.get("_validation_flags") or []),
                               _json(row.get("_tukin_validation") or {}),
                               row.get("_calculated_total_potongan_absen"),
                               row.get("_calculated_total_potongan_tukin"),
                               row.get("normalized_batch"), row.get("is_monthly"),
                               row.get("is_total"), _json(row.get("_bnba_normalized") or {}),
                               _json(row.get("_raw_data") or row)])
                conn.execute(sql, values)
            conn.execute("COMMIT")
            return import_id
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.close(conn)

    def rows(self, source: str, filters: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
        self.ensure_schema()
        source = _canonical_source(source)
        filters = dict(filters or {})
        include_inactive = bool(filters.pop("_include_inactive", False))
        conn = self.connect()
        try:
            where, params = [], []
            if not include_inactive:
                where.append("i.is_active=TRUE")
            for col in ("row_id", "nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun",
                        "bulan", "periode", "batch", "komponen", "import_id"):
                val = filters.get(col)
                if val not in (None, ""):
                    values = _filter_values(val)
                    where.append(f"r.{col} IN ({', '.join('?' for _ in values)})")
                    params.extend(values)
            # The UI's global search is intentionally a partial, case-insensitive
            # match rather than an exact NIP filter.
            search = filters.get("search")
            if search not in (None, ""):
                term = "%" + str(search).strip() + "%"
                where.append("(r.nip ILIKE ? OR r.nama ILIKE ?)")
                params.extend([term, term])
            for col in ("normalized_batch", "is_monthly", "is_total"):
                val = filters.get(col)
                if val not in (None, ""):
                    values = _filter_values(val)
                    where.append(f"r.{col} IN ({', '.join('?' for _ in values)})")
                    params.extend(values)
            for raw_field in ("provinsi", "kabupaten_kota", "kdanaksatker", "unit_kerja"):
                val = filters.get(raw_field)
                if val not in (None, ""):
                    values = _filter_values(val)
                    where.append(f"r.{raw_field} IN ({', '.join('?' for _ in values)})")
                    params.extend(values)
            if filters.get("flag"):
                where.append("r.validation_flags ILIKE ?")
                params.append("%" + str(filters["flag"]) + "%")
            limit = min(max(int(filters.get("limit", 500)), 1), 100000)
            offset = max(int(filters.get("offset", 0)), 0)
            projection = "r.*"
            if filters.get("_lightweight"):
                # Keep the compact normalized projection in lightweight reads:
                # it records whether Flaging was explicitly supplied without
                # loading the much larger raw source payload.
                projection = "r.* EXCLUDE (raw_data, tukin_validation)"
            sql = (f"SELECT {projection} FROM {self.table_for(source)} r "
                   "JOIN pengembalian_archive_import i ON i.import_id=r.import_id")
            if where:
                sql += " WHERE " + " AND ".join(where)
            # DuckDB rowid on the import table is the existing monotonic import
            # sequence. It breaks equal timestamps without using lexical UUIDs.
            sql += " ORDER BY i.imported_at, i.rowid, r.source_row, r.rowid LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            records = conn.execute(sql, params).fetchdf().to_dict(orient="records")
            records = [{key: _clean(value) for key, value in record.items()}
                       for record in records]
            for record in records:
                record["raw_data"] = _json_load(record.get("raw_data"))
                record["validation_flags"] = _json_load(record.get("validation_flags")) or []
                record["tukin_validation"] = _json_load(record.get("tukin_validation")) or {}
            return records
        finally:
            self.close(conn)

    def bpk_history(self, comparison_keys: Optional[Sequence[str]] = None,
                    batch: Optional[int] = None) -> List[Dict[str, Any]]:
        self.ensure_schema()
        conn = self.connect()
        try:
            clauses, params = [], []
            if comparison_keys:
                placeholders = ",".join("?" for _ in comparison_keys)
                clauses.append(f"comparison_key IN ({placeholders})")
                params.extend(comparison_keys)
            if batch is not None:
                clauses.append("bpk_batch = ?")
                params.append(batch)
            sql = "SELECT * FROM pengembalian_archive_bpk_history"
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY bpk_batch, tanggal_send_bpk, created_at"
            records = conn.execute(sql, params).fetchdf().to_dict(orient="records")
            return [{key: _clean(value) for key, value in record.items()}
                    for record in records]
        finally:
            self.close(conn)

    def record_bpk_history(self, batch_id: str, items: Sequence[Mapping[str, Any]],
                           created_by: str = "system", bpk_batch: Optional[int] = None) -> Dict[str, Any]:
        """Record BPK send metadata without changing immutable archive rows."""
        self.ensure_schema()
        conn = self.connect()
        try:
            batch_number = bpk_batch
            if batch_number is None:
                batch_number = conn.execute(
                    "SELECT COALESCE(MAX(bpk_batch), 0) + 1 FROM pengembalian_archive_bpk_history"
                ).fetchone()[0]
            batch_number = int(batch_number)
            label = f"SEND BPK BATCH {batch_number}"
            inserted = 0
            conn.execute("BEGIN")
            for item in items:
                source_hint = item.get("source_dataset")
                source = _canonical_source(source_hint or SOURCE_AWAL)
                source_rows = []
                row_id = item.get("archive_row_id") or item.get("row_id")

                def fetch_candidates(candidate_source: str, by_row_id: Optional[str] = None):
                    """Read lineage candidates on the active write connection."""
                    table = self.table_for(candidate_source)
                    clauses, values = [], []
                    if by_row_id:
                        clauses.append("row_id = ?")
                        values.append(by_row_id)
                    else:
                        if item.get("nip"):
                            clauses.append("nip = ?")
                            values.append(item.get("nip"))
                        if item.get("source_version"):
                            clauses.append("import_id = ?")
                            values.append(item.get("source_version"))
                    sql = f"SELECT * FROM {table}"
                    if clauses:
                        sql += " WHERE " + " AND ".join(clauses)
                    sql += " ORDER BY created_at, source_row, row_id LIMIT 10000"
                    records = conn.execute(sql, values).fetchdf().to_dict(orient="records")
                    return [{key: _clean(value) for key, value in record.items()}
                            for record in records]

                if row_id:
                    # Resolve by indexed identity instead of scanning only the
                    # first 5,000 archive rows. If no dataset hint is supplied,
                    # also check adjustment data so large archives remain safe.
                    sources = [source] if source_hint else [SOURCE_AWAL, SOURCE_PENYESUAIAN]
                    for candidate_source in sources:
                        source_rows = fetch_candidates(candidate_source, row_id)
                        if source_rows:
                            source = candidate_source
                            break
                comparison_key = item.get("comparison_key")
                row = source_rows[0] if source_rows else {}
                if not comparison_key:
                    candidate = {
                        "nip": item.get("nip") or row.get("nip"),
                        "periode_id": item.get("periode_id") or row.get("periode_id"),
                        "tahun_sp2d": item.get("tahun_sp2d") or row.get("tahun_sp2d"),
                        "periode": item.get("periode") or row.get("periode"),
                        "bulan": item.get("bulan") or row.get("bulan"),
                        "batch": item.get("batch") or row.get("batch"),
                        "komponen": item.get("komponen") or row.get("komponen"),
                    }
                    comparison_key = ArchiveService.comparison_key(candidate)
                if not source_rows:
                    source_rows = fetch_candidates(source)
                    source_rows = [r for r in source_rows
                                   if ArchiveService.comparison_key(r) == comparison_key]
                row = source_rows[0] if source_rows else row
                nip = item.get("nip") or row.get("nip")
                if not nip:
                    continue
                conn.execute(
                    """INSERT INTO pengembalian_archive_bpk_history
                    (history_id, row_id, comparison_key, nip, bpk_batch, bpk_batch_label,
                     tanggal_send_bpk, bpk_reference, source_dataset, source_version,
                     archive_version, is_current, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, now(), ?, ?, ?, ?, TRUE, now(), now())""",
                    [str(uuid.uuid4()), row.get("row_id") or row_id, comparison_key, nip,
                     batch_number, label, item.get("bpk_reference") or batch_id,
                     source, item.get("source_version") or row.get("import_id"),
                     item.get("archive_version") or row.get("import_id")],
                )
                inserted += 1
            conn.execute("COMMIT")
            return {"status": "ok", "bpk_batch": batch_number,
                    "bpk_batch_label": label, "batch_id": batch_id, "inserted": inserted}
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.close(conn)

    def imports(self, source: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        self.ensure_schema()
        conn = self.connect()
        try:
            params: List[Any] = []
            sql = "SELECT * FROM pengembalian_archive_import"
            if source:
                sql += " WHERE source_type = ?"
                params.append(_canonical_source(source))
            sql += " ORDER BY imported_at DESC LIMIT ?"
            params.append(min(max(int(limit), 1), 1000))
            rows = conn.execute(sql, params).fetchdf().to_dict(orient="records")
            rows = [{key: _clean(value) for key, value in row.items()} for row in rows]
            for row in rows:
                row["metadata"] = _json_load(row.get("metadata")) or {}
            return rows
        finally:
            self.close(conn)

    def set_import_active(self, import_id: str, active: bool) -> Dict[str, Any]:
        """Set one source snapshot active and deactivate its competing snapshot."""
        self.ensure_schema()
        normalized_id = str(import_id or '').strip()
        if not normalized_id:
            raise ValueError('import_id wajib diisi')
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT source_type, periode_id FROM pengembalian_archive_import WHERE import_id=?",
                [normalized_id],
            ).fetchone()
            if not row:
                raise LookupError('Import archive tidak ditemukan')
            source_type, periode_id = row
            conn.execute('BEGIN')
            if active:
                conn.execute(
                    """UPDATE pengembalian_archive_import
                       SET is_active=FALSE, status='INACTIVE'
                       WHERE source_type=? AND COALESCE(periode_id,'')=COALESCE(?,'')""",
                    [source_type, periode_id],
                )
            conn.execute(
                "UPDATE pengembalian_archive_import SET is_active=?, status=? WHERE import_id=?",
                [bool(active), 'ACTIVE' if active else 'INACTIVE', normalized_id],
            )
            conn.execute('COMMIT')
            return {
                'status': 'ok', 'import_id': normalized_id,
                'is_active': bool(active), 'periode_id': periode_id,
            }
        except Exception:
            try:
                conn.execute('ROLLBACK')
            except Exception:
                pass
            raise
        finally:
            self.close(conn)

    def clear_archive_database(self) -> Dict[str, Any]:
        """Delete all Master Pengembalian archive data, including derived rows."""
        self.ensure_schema()
        conn = self.connect()
        tables = [
            'pengembalian_archive_bpk_history', 'pengembalian_archive_compare_detail',
            'pengembalian_archive_compare', 'pengembalian_archive_data_awal',
            'pengembalian_archive_data_penyesuaian', 'pengembalian_archive_import',
            'pengembalian_final', 'pengembalian_archive_dataset_row',
            'pengembalian_archive_dataset',
        ]
        try:
            conn.execute('BEGIN')
            counts = {}
            for table in tables:
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                conn.execute(f'DELETE FROM {table}')
            conn.execute('COMMIT')
            return {'status': 'ok', 'deleted_tables': counts,
                    'deleted_rows': sum(counts.values())}
        except Exception:
            try:
                conn.execute('ROLLBACK')
            except Exception:
                pass
            raise
        finally:
            self.close(conn)

    def compare_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        self.ensure_schema()
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM pengembalian_archive_compare ORDER BY finished_at DESC LIMIT ?",
                [min(max(int(limit), 1), 1000)],
            ).fetchdf().to_dict(orient="records")
            for row in rows:
                for field in ("filters", "flags"):
                    row[field] = _json_load(row.get(field)) or {}
            return rows
        finally:
            self.close(conn)


class ArchiveService:
    def __init__(self, db_path: Optional[str] = None, repository: Optional[ArchiveRepository] = None):
        self.repository = repository or ArchiveRepository(db_path)

    def clear_database(self) -> Dict[str, Any]:
        return self.repository.clear_database()

    def set_import_active(self, import_id: str, active: bool) -> Dict[str, Any]:
        result = self.repository.set_import_active(import_id, active)
        if result.get('periode_id'):
            self.rebuild_final({'periode_id': result['periode_id']})
        return result

    def clear_archive_database(self) -> Dict[str, Any]:
        return self.repository.clear_archive_database()

    def import_progress(self, rows: Iterable[Mapping[str, Any]], imported_by="system",
                        source_file=None) -> Dict[str, Any]:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        inserted = 0
        try:
            for row in rows:
                normalized = {_key_name(k): value for k, value in row.items()}
                nip = _clean(normalized.get("nip"))
                tenor = normalized.get("tenor_bulan") or normalized.get("tenor") or normalized.get("bulan_ke")
                if not nip or tenor in (None, ""):
                    raise ValueError("Setiap baris progres wajib memiliki NIP dan tenor_bulan")
                conn.execute(
                    """INSERT INTO pengembalian_progress_bulanan
                    (progress_id,nip,nama,tenor_bulan,nominal_tagihan,nominal_dikirim,
                     nominal_berhasil,nominal_gagal,status,keterangan,source_file,imported_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [str(uuid.uuid4()), nip, _clean(normalized.get("nama")),
                     int(tenor), float(normalized.get("nominal_tagihan") or normalized.get("piutang") or 0),
                     float(normalized.get("nominal_dikirim") or normalized.get("dikirim") or 0),
                     float(normalized.get("nominal_berhasil") or normalized.get("berhasil_debit") or 0),
                     float(normalized.get("nominal_gagal") or normalized.get("gagal_debit") or 0),
                     _clean(normalized.get("status")), _clean(normalized.get("keterangan")),
                     source_file, imported_by],
                )
                inserted += 1
            conn.commit()
            return {"status": "ok", "inserted": inserted}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.repository.close(conn)

    def repayment_progress(self, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Combine FINAL receivables with sent-bank and debit-result records."""
        filters = dict(filters or {})
        page_limit = filters.get("_page_limit")
        page_offset = int(filters.get("_page_offset") or 0)
        final_result = self.final(filters)
        final_rows = final_result.get("rows", [])
        conn = self.repository.connect()
        try:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
            details = {}
            results = {}
            monthly = {}
            payments = {}
            page_nips = {
                str(row.get("nip") or row.get("identity", {}).get("nip") or "")
                for row in final_rows
            }
            page_keys = {
                str(row.get("comparison_key"))
                for row in final_rows
                if row.get("comparison_key") is not None
            }

            def in_clause(values):
                return ", ".join("?" for _ in values)

            if "pengembalian_payment_transaction" in tables:
                if page_keys:
                    for row in conn.execute(f"""SELECT obligation_key, status_debit,
                        SUM(nominal) AS nominal, COUNT(*) AS jumlah
                        FROM pengembalian_payment_transaction
                        WHERE obligation_key IN ({in_clause(page_keys)})
                        GROUP BY obligation_key, status_debit""", list(page_keys)).fetchall():
                        item = payments.setdefault(str(row[0]), {"success": 0.0, "failed": 0.0,
                                                                 "success_count": 0, "failed_count": 0})
                        if str(row[1]).upper() == "BERHASIL":
                            item["success"] += float(row[2] or 0)
                            item["success_count"] += int(row[3] or 0)
                        else:
                            item["failed"] += float(row[2] or 0)
                            item["failed_count"] += int(row[3] or 0)
            if "pengembalian_progress_bulanan" in tables:
                if page_nips:
                    for row in conn.execute(
                    "SELECT nip, tenor_bulan, nominal_tagihan, nominal_dikirim, "
                    "nominal_berhasil, nominal_gagal, status FROM pengembalian_progress_bulanan"
                    + f" WHERE nip IN ({in_clause(page_nips)})", list(page_nips)).fetchall():
                        monthly.setdefault(str(row[0]), []).append({
                            "tenor_bulan": row[1], "nominal_tagihan": float(row[2] or 0),
                            "nominal_dikirim": float(row[3] or 0), "nominal_berhasil": float(row[4] or 0),
                            "nominal_gagal": float(row[5] or 0), "status": row[6],
                        })
            if "pengembalian_bank_detail" in tables:
                detail_columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info('pengembalian_bank_detail')"
                    ).fetchall()
                }
                detail_amount = "nominal" if "nominal" in detail_columns else (
                    "nominal_request" if "nominal_request" in detail_columns else None
                )
                if detail_amount is None:
                    detail_amount = "0"
                if page_nips:
                    for row in conn.execute(
                        f"SELECT nip, {detail_amount} AS nominal FROM pengembalian_bank_detail "
                        f"WHERE nip IN ({in_clause(page_nips)})", list(page_nips)
                    ).fetchall():
                        details.setdefault(str(row[0]), {"sent": 0.0, "count": 0})
                        details[str(row[0])]["sent"] += float(row[1] or 0)
                        details[str(row[0])]["count"] += 1
            if "pengembalian_bank_result" in tables:
                columns = {
                    row[1] for row in conn.execute(
                        "PRAGMA table_info('pengembalian_bank_result')"
                    ).fetchall()
                }
                amount = "nominal_berhasil" if "nominal_berhasil" in columns else "nominal"
                status = "status_debet" if "status_debet" in columns else "status"
                if page_nips:
                    for row in conn.execute(
                        f"SELECT nip, {amount}, {status} FROM pengembalian_bank_result "
                        f"WHERE nip IN ({in_clause(page_nips)})", list(page_nips)
                    ).fetchall():
                        key = str(row[0])
                        item = results.setdefault(key, {"success": 0.0, "failed": 0.0, "count": 0})
                        value = float(row[1] or 0)
                        state = str(row[2] or "").upper()
                        if state in {"SUCCESS", "BERHASIL", "BERHASIL DEBIT", "SUKSES"}:
                            item["success"] += value
                        else:
                            item["failed"] += value
                        item["count"] += 1
            rows = []
            final_nips = set()
            for final_row in final_rows:
                nip = str(final_row.get("nip") or final_row.get("identity", {}).get("nip") or "")
                final_nips.add(nip)
                sent = details.get(nip, {})
                result = payments.get(str(final_row.get("comparison_key"))) or results.get(nip, {})
                receivable = float(final_row.get("nilai_final") or 0)
                success = float(result.get("success", 0))
                failed_amount = float(result.get("failed", 0))
                if receivable <= 0:
                    payment_status = "TIDAK ADA KEWAJIBAN" if success <= 0 else "LEBIH BAYAR / PERLU REVIEW"
                elif success <= 0:
                    payment_status = "BELUM ADA PENGEMBALIAN"
                elif success < receivable:
                    payment_status = "SEBAGIAN"
                elif success == receivable:
                    payment_status = "LUNAS"
                else:
                    payment_status = "LEBIH BAYAR / PERLU REVIEW"
                rows.append({
                    "obligation_key": final_row.get("comparison_key"),
                    "periode_id": final_row.get("periode_id"),
                    "nip": nip,
                    "nama": final_row.get("nama") or final_row.get("identity", {}).get("nama"),
                    "piutang_pengembalian": receivable,
                    "sudah_dikirim_bank": float(sent.get("sent", 0)),
                    "berhasil_debit": success,
                    "gagal_debit": failed_amount,
                    "sisa_piutang": max(receivable - success, 0),
                    "kelebihan_bayar": max(success - receivable, 0),
                    "status": payment_status,
                    "debit_berhasil_count": result.get("success_count", 0),
                    "debit_gagal_count": result.get("failed_count", 0),
                    "tenor": monthly.get(nip, []),
                })
            # Monthly-only records are appended only for unpaged/legacy requests.
            # This prevents a paged response from being expanded by the full monthly table.
            if page_limit is None:
                for nip, monthly_rows in monthly.items():
                    if nip in final_nips:
                        continue
                    for item in monthly_rows:
                        receivable = item["nominal_tagihan"]
                        success = item["nominal_berhasil"]
                        rows.append({
                            "nip": nip,
                            "nama": None,
                            "piutang_pengembalian": receivable,
                            "sudah_dikirim_bank": item["nominal_dikirim"],
                            "berhasil_debit": success,
                            "gagal_debit": item["nominal_gagal"],
                            "sisa_piutang": max(receivable - success, 0),
                            "status": item["status"] or "BELUM DIPROSES",
                            "tenor": [item],
                        })
            return {"status": "ok", "rows": rows,
                    "count": len(rows) if page_limit is None else int(final_result.get("total", len(rows))),
                    "page": (page_offset // int(page_limit)) + 1 if page_limit else 1,
                    "page_size": int(page_limit) if page_limit else len(rows),
                    "has_more": bool(page_limit and page_offset + len(rows) < final_result.get("total", 0)),
                    "summary": {
                        "total_piutang": sum(r["piutang_pengembalian"] for r in rows),
                        "total_dikirim": sum(r["sudah_dikirim_bank"] for r in rows),
                        "total_berhasil": sum(r["berhasil_debit"] for r in rows),
                        "total_gagal": sum(r["gagal_debit"] for r in rows),
                        "total_sisa": sum(r["sisa_piutang"] for r in rows),
                        "sdm_lunas": sum(1 for r in rows if r["status"] == "LUNAS"),
                        "sdm_sebagian": sum(1 for r in rows if r["status"] == "SEBAGIAN"),
                        "sdm_belum": sum(1 for r in rows if r["status"] == "BELUM ADA PENGEMBALIAN"),
                        "sdm_review": sum(1 for r in rows if "REVIEW" in r["status"]),
                    }}
        finally:
            self.repository.close(conn)

    @staticmethod
    def normalize_row(row: Mapping[str, Any], source_row: Optional[int] = None) -> Dict[str, Any]:
        source = dict(row)
        normalized_keys = {_key_name(k): v for k, v in source.items()}
        result: Dict[str, Any] = {}
        for field, aliases in _ALIASES.items():
            value = None
            for alias in aliases:
                key = _key_name(alias)
                if key in normalized_keys and _clean(normalized_keys[key]) is not None:
                    value = normalized_keys[key]
                    break
            value = _number(value) if field in _NUMERIC else _clean(value)
            if field in {"tahun_sp2d", "tahun", "bulan"} and value is not None:
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    pass
            result[field] = value
        if result.get("periode") is None and result.get("tahun") is not None and result.get("bulan") is not None:
            result["periode"] = f"{int(result['tahun'])}-{int(result['bulan']):02d}"
        if result.get("periode") is not None:
            result["periode"] = _normalize_period(result["periode"])
        source_change_flag = _normalize_change_flag(result.get("flag_ada_perubahan"))
        result["_source_flag_ada_perubahan"] = source_change_flag
        # Keep a stable, machine-readable normalized projection while raw_data
        # retains every original source header/value (including unknown columns).
        result["_bnba_normalized"] = {
            field: result.get(field) for field in _ALIASES
            if result.get(field) is not None
        }
        batch = result.get("batch")
        result["normalized_batch"] = (
            str(batch).strip().upper().replace(" ", "-") if batch is not None else None
        )
        for month in ("oktober", "november", "desember"):
            awal = _number(result.get(f"tukin_pengembalian_{month}"))
            final = _number(result.get(f"final_pengembalian_tukin_{month}"))
            delta = None if awal is None or final is None else final - awal
            result[f"selisih_{month}"] = delta
            result[f"flag_perubahan_{month}"] = (
                "BERUBAH" if delta is not None and delta != 0 else "TIDAK BERUBAH"
            )
        awal_total = _number(result.get("total_awal_tukin"))
        awal_bulanan = [
            _number(result.get(f"tukin_pengembalian_{month}"))
            for month in ("oktober", "november", "desember")
        ]
        # NULL means the source did not provide a value; zero is a real value.
        # Only derive a total when at least one monthly component is present.
        if awal_total is None and any(value is not None for value in awal_bulanan):
            awal_total = sum(value for value in awal_bulanan if value is not None)
        final_total = _number(result.get("final_total_pengembalian_tukin"))
        final_bulanan = [
            _number(result.get(f"final_pengembalian_tukin_{month}"))
            for month in ("oktober", "november", "desember")
        ]
        if final_total is None and any(value is not None for value in final_bulanan):
            final_total = sum(value for value in final_bulanan if value is not None)
        result["total_awal_tukin"] = awal_total
        result["final_total_pengembalian_tukin"] = final_total
        result["selisih_total_tukin"] = (
            final_total - awal_total
            if final_total is not None and awal_total is not None else None
        )
        result["flag_perubahan_total"] = (
            "BERUBAH" if result["selisih_total_tukin"] not in (None, 0)
            else "TIDAK BERUBAH"
        )
        calculated_change = any(result[f"flag_perubahan_{m}"] == "BERUBAH"
                                for m in ("oktober", "november", "desember"))
        result["flag_ada_perubahan"] = (
            "BERUBAH" if source_change_flag == "BERUBAH" or calculated_change
            or result["flag_perubahan_total"] == "BERUBAH" else "TIDAK BERUBAH"
        )
        result["arah_perubahan"] = (
            "NAIK" if result["selisih_total_tukin"] is not None and result["selisih_total_tukin"] > 0
            else "TURUN" if result["selisih_total_tukin"] is not None and result["selisih_total_tukin"] < 0
            else "TETAP"
        )
        result["batch_oktober_normalized"] = _normalize_bnba_batch(result.get("batch_oktober_raw"))
        result["batch_november_normalized"] = _normalize_bnba_batch(result.get("batch_november_raw"))
        result["batch_desember_normalized"] = _normalize_bnba_batch(result.get("batch_desember_raw"))
        result["final_batch_normalized"] = _normalize_bnba_batch(result.get("final_batch_raw"))
        component = str(result.get("komponen") or "").lower()
        result["is_monthly"] = bool(result.get("periode") or "bulan" in component or "monthly" in component)
        result["is_total"] = bool(
            result.get("total_potongan_tukin") is not None
            or "total" in component
            or "pengembalian" in component
        )
        # A year column is a useful fallback when a source omits Tahun SP2D.
        if result["tahun_sp2d"] is None:
            result["tahun_sp2d"] = result["tahun_sp2d_update"] or result["tahun"]
        if result["periode"] is not None and not _is_valid_period(result["periode"]):
            result["periode"] = _normalize_period(result["periode"])
        if result["esdm"] is not None and result["e_absensi"] is not None:
            result["_calculated_total_potongan_absen"] = min(
                result["esdm"], result["e_absensi"]
            )
        if (result["potongan_skp"] is not None
                and result.get("_calculated_total_potongan_absen") is not None):
            result["_calculated_total_potongan_tukin"] = (
                result["potongan_skp"] + result["_calculated_total_potongan_absen"]
            )
        total = result["total_tukin"]
        tukin_validation = {}
        for field, ratio in (("tukin_absen_30", 0.30), ("tukin_skp_70", 0.70)):
            actual = result[field]
            expected = total * ratio if total is not None else None
            difference = actual - expected if actual is not None and expected is not None else None
            status = VALIDATION_UNKNOWN
            if difference is not None:
                status = VALIDATION_VALID if abs(difference) <= 1.0 else VALIDATION_INVALID
            tukin_validation[field] = {
                "source_value": actual,
                "expected_value": expected,
                "difference": difference,
                "status": status,
            }
        flags = []
        if result["nip"] is None:
            flags.append("NIP WAJIB DIISI")
        if result["tahun_sp2d"] is None:
            flags.append("TAHUN SP2D WAJIB DIISI")
        if result["periode"] is not None and not _is_valid_period(result["periode"]):
            flags.append("PERIODE TIDAK VALID")
        if result["bulan"] is not None and not 1 <= result["bulan"] <= 12:
            flags.append("BULAN TIDAK VALID")
        if source_row is not None:
            result["_source_row"] = source_row
        result["_validation_flags"] = flags
        result["_tukin_validation"] = tukin_validation
        result["_schema_invalid"] = bool(flags)
        result["_raw_data"] = source
        return result

    @staticmethod
    def _rounding_key(row: Mapping[str, Any], index: int) -> str:
        return "|".join(str(row.get(field) or "") for field in (
            "nip", "tahun_sp2d", "bulan", "komponen", "source_record_id"
        )) + f"|{int(row.get('_source_row') or index + 1):012d}"

    @classmethod
    def reconcile_nominals(cls, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Round money once, preserving field totals and Tahun SP2D subtotals."""
        summaries = []
        derived_details = {
            "total_awal_tukin": [f"tukin_pengembalian_{m}" for m in ("oktober", "november", "desember")],
            "final_total_pengembalian_tukin": [f"final_pengembalian_tukin_{m}" for m in ("oktober", "november", "desember")],
            "final_total_pengembalian_uang_makan": [f"pengembalian_uang_makan_{m}" for m in ("oktober", "november", "desember")],
            "final_total_pengembalian_tukin_uang_makan": [
                "final_total_pengembalian_tukin", "final_total_pengembalian_uang_makan"
            ],
        }
        standalone_derived = tuple(
            field for field, details in derived_details.items()
            if not any(row.get(detail) is not None for row in rows for detail in details)
        )
        all_fields = (*ROUNDING_DETAIL_FIELDS, *standalone_derived)
        for field in all_fields:
            populated = [i for i, row in enumerate(rows) if _decimal_number(row.get(field)) is not None]
            if not populated:
                continue
            # Allocate the grand target across business groups first. This
            # prevents Rp1 from moving between Tahun SP2D/batch/component.
            groups: Dict[Tuple[str, str, str], List[int]] = {}
            for index in populated:
                row = rows[index]
                group = (str(row.get("tahun_sp2d") or ""),
                         str(row.get("batch") or ""), str(row.get("komponen") or ""))
                groups.setdefault(group, []).append(index)
            ordered_groups = sorted(groups)
            group_raw_totals = [sum((_decimal_number(rows[i].get(field)) or Decimal(0)
                                     for i in groups[group]), Decimal(0))
                                for group in ordered_groups]
            grand_target = int(sum(group_raw_totals, Decimal(0)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP))
            group_result = sum_preserving_round(
                group_raw_totals, ["|".join(group) for group in ordered_groups], grand_target
            )
            field_raw_total = Decimal(0)
            field_adjusted = field_decimals = field_zero_modified = 0
            for group, group_target in zip(ordered_groups, group_result["values"]):
                indices = groups[group]
                result = sum_preserving_round(
                    [rows[i].get(field) for i in indices],
                    [cls._rounding_key(rows[i], i) for i in indices], group_target,
                )
                field_raw_total += result["raw_total"]
                field_adjusted += result["adjusted_record_count"]
                field_decimals += result["decimal_record_count"]
                field_zero_modified += result["zero_modified_count"]
                for index, rounded_value in zip(indices, result["values"]):
                    raw = _decimal_number(rows[index].get(field))
                    rows[index].setdefault("_rounding_audit", {})[field] = {
                        "raw_value": str(raw), "rounded_value": rounded_value,
                        "rounding_adjustment": None if raw is None else str(Decimal(rounded_value) - raw),
                    }
                    rows[index][field] = rounded_value
            rounded_total = sum(int(rows[i][field]) for i in populated)
            summary = {
                "field": field, "raw_total": str(field_raw_total),
                "target_total": grand_target, "rounded_total": rounded_total,
                "difference": grand_target - rounded_total,
                "decimal_record_count": field_decimals,
                "adjusted_record_count": field_adjusted,
                "zero_modified_count": field_zero_modified,
                "status": "VALID" if rounded_total == grand_target and not field_zero_modified else "INVALID",
            }
            if summary["status"] != "VALID":
                raise ValueError("ROUNDING_RECONCILIATION_FAILED")
            summaries.append(summary)

        # Aggregate fields are sums of rounded leaf values whenever their
        # source details exist. This makes DETAIL the operational source of truth.
        for row in rows:
            def derive(total_field, detail_fields):
                values = [row.get(name) for name in detail_fields]
                if any(value is not None for value in values):
                    row[total_field] = sum(int(value or 0) for value in values)
            derive("total_awal_tukin", [f"tukin_pengembalian_{m}" for m in ("oktober", "november", "desember")])
            derive("final_total_pengembalian_tukin", [f"final_pengembalian_tukin_{m}" for m in ("oktober", "november", "desember")])
            derive("final_total_pengembalian_uang_makan", [f"pengembalian_uang_makan_{m}" for m in ("oktober", "november", "desember")])
            if row.get("final_total_pengembalian_tukin") is not None or row.get("final_total_pengembalian_uang_makan") is not None:
                row["final_total_pengembalian_tukin_uang_makan"] = int(row.get("final_total_pengembalian_tukin") or 0) + int(row.get("final_total_pengembalian_uang_makan") or 0)
            # Rebuild every monetary delta/calculated amount from reconciled
            # integers; values computed during parsing must not leak decimals.
            for month in ("oktober", "november", "desember"):
                awal = row.get(f"tukin_pengembalian_{month}")
                final = row.get(f"final_pengembalian_tukin_{month}")
                delta = None if awal is None or final is None else int(final) - int(awal)
                row[f"selisih_{month}"] = delta
                row[f"flag_perubahan_{month}"] = "BERUBAH" if delta not in (None, 0) else "TIDAK BERUBAH"
            awal_total = row.get("total_awal_tukin")
            final_total = row.get("final_total_pengembalian_tukin")
            total_delta = None if awal_total is None or final_total is None else int(final_total) - int(awal_total)
            row["selisih_total_tukin"] = total_delta
            row["flag_perubahan_total"] = "BERUBAH" if total_delta not in (None, 0) else "TIDAK BERUBAH"
            calculated_change = any(row[f"flag_perubahan_{month}"] == "BERUBAH"
                                    for month in ("oktober", "november", "desember"))
            row["flag_ada_perubahan"] = (
                "BERUBAH" if row.get("_source_flag_ada_perubahan") == "BERUBAH"
                or calculated_change or row["flag_perubahan_total"] == "BERUBAH"
                else "TIDAK BERUBAH"
            )
            row["arah_perubahan"] = "NAIK" if total_delta is not None and total_delta > 0 else "TURUN" if total_delta is not None and total_delta < 0 else "TETAP"
            if row.get("esdm") is not None and row.get("e_absensi") is not None:
                row["_calculated_total_potongan_absen"] = min(int(row["esdm"]), int(row["e_absensi"]))
            if row.get("potongan_skp") is not None and row.get("_calculated_total_potongan_absen") is not None:
                row["_calculated_total_potongan_tukin"] = int(row["potongan_skp"]) + int(row["_calculated_total_potongan_absen"])
            row.setdefault("_bnba_normalized", {})["rounding_audit"] = row.get("_rounding_audit", {})
            for field in all_fields:
                if row.get(field) is not None:
                    row["_bnba_normalized"][field] = row[field]
        return {
            "total_records": len(rows), "fields": summaries,
            "decimal_record_count": sum(item["decimal_record_count"] for item in summaries),
            "adjusted_record_count": sum(item["adjusted_record_count"] for item in summaries),
            "zero_modified_count": sum(item["zero_modified_count"] for item in summaries),
            "status": "VALID",
        }

    def validate(self, rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        normalized = [self.normalize_row(row, i + 1) for i, row in enumerate(rows)]
        rounding = self.reconcile_nominals(normalized)
        errors = [
            {"row": row.get("_source_row"), "flags": row.get("_validation_flags", [])}
            for row in normalized if row.get("_validation_flags")
        ]
        return {
            "valid": not errors,
            "rows": normalized,
            "errors": errors,
            "total": len(normalized),
            "valid_count": len(normalized) - len(errors),
            "invalid_count": len(errors),
            "rounding_reconciliation": rounding,
        }

    def preview(self, rows: Iterable[Mapping[str, Any]], source: str = SOURCE_AWAL,
                metadata: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        source = _canonical_source(source)
        metadata = dict(metadata or {})
        rows = list(rows)
        inferred_period_id = metadata.get("periode_id") or _infer_period_id_from_rows(rows)
        if inferred_period_id:
            metadata.setdefault("periode_id", inferred_period_id)
            for row in rows:
                if isinstance(row, Mapping) and row.get("periode_id") in (None, ""):
                    row["periode_id"] = inferred_period_id
        metadata.setdefault("dataset_type", source)
        metadata.setdefault("send_bpk_status", "BELUM SEND BPK")
        dataset_type = str(metadata["dataset_type"]).upper()
        send_bpk_status = str(metadata["send_bpk_status"]).upper()
        warnings = []
        if dataset_type not in DATASET_TYPES:
            warnings.append("SOURCE DATASET TIDAK DIKENAL")
        if send_bpk_status not in BPK_STATUSES:
            warnings.append("STATUS BPK TIDAK DIKENAL")
        result = self.validate(rows)
        # Preview duplicate warnings without collapsing rows.
        groups: Dict[str, int] = {}
        for row in result["rows"]:
            key = self.comparison_key(row)
            groups[key] = groups.get(key, 0) + 1
        duplicates = [{"comparison_key": key, "count": count}
                      for key, count in groups.items() if count > 1]
        total_return = sum(float(
                                 row.get("final_total_pengembalian_tukin_uang_makan")
                                 or row.get("final_total_pengembalian_tukin")
                                 or row.get("total_potongan_tukin")
                                 or row.get("_calculated_total_potongan_tukin") or 0)
                           for row in result["rows"])
        if metadata.get("periode_id"):
            for row in result["rows"]:
                row.setdefault("periode_id", metadata["periode_id"])
        result.update({"source": source, "metadata": metadata, "dataset_type": dataset_type,
                       "send_bpk_status": send_bpk_status,
                       "bpk_batch": metadata.get("bpk_batch"),
                       "warnings": warnings, "duplicates": duplicates,
                       "duplicate_count": len(duplicates),
                       "periods": sorted({row.get("periode") for row in result["rows"] if row.get("periode")}),
                       "total_pengembalian": total_return})
        return result

    def import_rows(self, rows: Iterable[Mapping[str, Any]], source: str = SOURCE_AWAL,
                    metadata: Optional[Mapping[str, Any]] = None,
                    imported_by: str = "system") -> Dict[str, Any]:
        source = _canonical_source(source)
        if source == SOURCE_FINAL:
            raise ValueError("DATA_FINAL adalah projection turunan dan tidak dapat diimport")
        preview = self.preview(rows, source, metadata)
        metadata = dict(metadata or {})
        import_mode = str(metadata.get("import_mode") or "APPEND").upper()
        if import_mode not in IMPORT_MODES:
            raise ValueError("import_mode harus APPEND atau UPSERT")
        metadata["import_mode"] = import_mode
        if import_mode == "UPSERT":
            latest_rows = {}
            for row in preview["rows"]:
                latest_rows[self.comparison_key(row)] = row
            preview["rows"] = list(latest_rows.values())
            preview["total"] = len(preview["rows"])
            preview["valid_count"] = sum(
                1 for row in preview["rows"] if not row.get("_schema_invalid")
            )
            preview["invalid_count"] = preview["total"] - preview["valid_count"]
        if not metadata.get("file_hash"):
            fingerprint_rows = [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in preview["rows"]
            ]
            metadata["file_hash"] = hashlib.sha256(
                _json(fingerprint_rows).encode("utf-8")
            ).hexdigest()
        if not preview["rows"]:
            raise ValueError("FILE KOSONG")
        # Mark every duplicate source row, rather than collapsing it or only
        # marking an aggregate comparison record.
        duplicate_keys = {item["comparison_key"] for item in preview["duplicates"]}
        for item in preview["rows"]:
            if self.comparison_key(item) in duplicate_keys:
                flags = item.setdefault("_validation_flags", [])
                for flag in ("DUPLIKASI", "RECORD GANDA - PERLU KONFIRMASI"):
                    if flag not in flags:
                        flags.append(flag)
        import_id = self.repository.insert_import(metadata or {}, preview["rows"], source, imported_by)
        period_id = metadata.get("periode_id")
        self.rebuild_final({"periode_id": period_id} if period_id else {})
        if preview["send_bpk_status"].startswith("SEND BPK"):
            batch = preview.get("bpk_batch")
            items = [
                {"comparison_key": self.comparison_key(row), "nip": row.get("nip"),
                 "source_dataset": source, "source_version": import_id,
                 "archive_version": metadata.get("version") or import_id}
                for row in preview["rows"] if row.get("nip")
            ]
            self.record_bpk_history(import_id, items, imported_by, batch)
        return {
            "status": "ok", "import_id": import_id, "batch_id": import_id,
            "source": source, "total": preview["total"], "total_rows": preview["total"],
            "valid": preview["valid_count"], "invalid": preview["invalid_count"],
            "validation_errors": preview["errors"], "duplicate_count": preview["duplicate_count"],
            "dataset_type": preview["dataset_type"], "send_bpk_status": preview["send_bpk_status"],
            "bpk_batch": preview["bpk_batch"], "total_pengembalian": preview["total_pengembalian"],
            "import_mode": import_mode,
        }

    # Friendly aliases used by integrations.
    import_source = import_rows
    append_import = import_rows

    def import_bnba_combined(self, rows: Iterable[Mapping[str, Any]],
                             metadata: Optional[Mapping[str, Any]] = None,
                             imported_by: str = "system") -> Dict[str, Any]:
        """Archive one BNBA workbook as initial and adjustment snapshots.

        The workbook's initial columns are stored in DATA_AWAL. Its FINAL
        columns are projected into a separate DATA_PENYESUAIAN row so the
        comparison layer remains append-only and never overwrites the source.
        """
        source_rows = [dict(row) for row in rows]
        period_id = (metadata or {}).get("periode_id")
        if period_id:
            for row in source_rows:
                row.setdefault("periode_id", period_id)
        adjustment_rows = []
        for source_row in source_rows:
            row = self.normalize_row(source_row)
            adjusted = dict(source_row)
            for month in ("oktober", "november", "desember"):
                final_value = row.get(f"final_pengembalian_tukin_{month}")
                if final_value is not None:
                    adjusted[f"tukin_pengembalian_{month}"] = final_value
            final_total = row.get("final_total_pengembalian_tukin")
            if final_total is not None:
                adjusted["total_potongan_tukin"] = final_total
            adjusted["sumber_data"] = "FINAL_COLUMNS"
            adjustment_rows.append(adjusted)
        base_metadata = dict(metadata or {})
        base_metadata["import_mode"] = "APPEND"
        batch_values = {
            _normalize_bnba_batch(self.normalize_row(row).get("batch"))
            for row in source_rows
            if self.normalize_row(row).get("batch") is not None
        }
        numeric_batches = {
            int(match.group(1))
            for value in batch_values
            for match in [re.search(r"(\d+)", str(value))]
            if match
        }
        if len(numeric_batches) == 1:
            batch_number = next(iter(numeric_batches))
            base_metadata["send_bpk_status"] = f"SEND BPK BATCH {batch_number}"
            base_metadata["bpk_batch"] = batch_number
        else:
            base_metadata["send_bpk_status"] = "BELUM SEND BPK"
            base_metadata.pop("bpk_batch", None)
        initial_metadata = {**base_metadata, "dataset_type": SOURCE_AWAL,
                            "embedded_final_columns": True}
        adjustment_metadata = {**base_metadata, "dataset_type": SOURCE_PENYESUAIAN,
                               "embedded_final_columns": True}
        initial = self.import_rows(source_rows, SOURCE_AWAL, initial_metadata, imported_by)
        try:
            adjustment = self.import_rows(adjustment_rows, SOURCE_PENYESUAIAN,
                                          adjustment_metadata, imported_by)
        except Exception:
            # The public workflow is one logical import. Compensate the first
            # append if the final snapshot fails so no half-import becomes active.
            conn = self.repository.connect()
            try:
                conn.execute("BEGIN")
                conn.execute("DELETE FROM pengembalian_archive_data_awal WHERE import_id=?",
                             [initial["import_id"]])
                conn.execute("DELETE FROM pengembalian_archive_bpk_history WHERE source_version=?",
                             [initial["import_id"]])
                conn.execute("DELETE FROM pengembalian_archive_import WHERE import_id=?",
                             [initial["import_id"]])
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                self.repository.close(conn)
            raise
        final_build = self.rebuild_final({"periode_id": period_id} if period_id else {})
        return {
            "status": "ok",
            "import_mode": base_metadata.get("import_mode") or "APPEND",
            "embedded_final_columns": True,
            "initial": initial,
            "adjustment": adjustment,
            "total": initial["total"],
            "final_ready": True,
            "final_rows": final_build["rows"],
            "progress": {"percent": 100, "stage": "FINAL READY",
                         "processed": initial["total"], "total": initial["total"]},
        }

    def periods(self) -> List[Dict[str, Any]]:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            frame = conn.execute(
                """SELECT p.*,
                    COALESCE(f.final_rows,0) final_rows,
                    COALESCE(a.archive_rows,0) archive_rows,
                    COALESCE(d.dataset_rows,0) dataset_count,
                    COALESCE(o.obligation_rows,0) obligation_rows,
                    COALESCE(t.transaction_rows,0) transaction_rows,
                    COALESCE(f.final_rows,0)+COALESCE(a.archive_rows,0)+
                    COALESCE(d.dataset_rows,0)+COALESCE(o.obligation_rows,0)+
                    COALESCE(t.transaction_rows,0) usage_count
                FROM pengembalian_period p
                LEFT JOIN (SELECT periode_id,count(*) final_rows FROM pengembalian_final GROUP BY periode_id) f USING(periode_id)
                LEFT JOIN (SELECT periode_id,count(*) archive_rows FROM (
                    SELECT periode_id FROM pengembalian_archive_data_awal
                    UNION ALL SELECT periode_id FROM pengembalian_archive_data_penyesuaian
                ) x GROUP BY periode_id) a USING(periode_id)
                LEFT JOIN (SELECT periode_id,count(*) dataset_rows FROM pengembalian_archive_dataset GROUP BY periode_id) d USING(periode_id)
                LEFT JOIN (SELECT periode_id,count(*) obligation_rows FROM pengembalian_master_obligation GROUP BY periode_id) o USING(periode_id)
                LEFT JOIN (SELECT periode_id,count(*) transaction_rows FROM pengembalian_progress_transaction GROUP BY periode_id) t USING(periode_id)
                ORDER BY p.is_active DESC,p.tahun_proses DESC,p.bulan_proses DESC,p.created_at DESC"""
            ).fetchdf()
            records = frame.to_dict(orient="records")
            for record in records:
                for key, value in list(record.items()):
                    if isinstance(value, (datetime, date)):
                        record[key] = value.isoformat()
                    elif isinstance(value, Decimal):
                        record[key] = float(value)
            return records
        finally:
            self.repository.close(conn)

    def active_period(self) -> Optional[Dict[str, Any]]:
        return next((row for row in self.periods() if bool(row.get("is_active"))), None)

    def _audit_period(self, conn, period_id: str, action: str,
                      previous_status=None, new_status=None, details=None, created_by="system"):
        conn.execute("""INSERT INTO pengembalian_period_audit
            (audit_id,periode_id,action,previous_status,new_status,details_json,created_by)
            VALUES (?,?,?,?,?,?,?)""", [str(uuid.uuid4()), period_id, action,
                previous_status, new_status, _json(details or {}), created_by])

    def assert_period_writable(self, period_id: str) -> Dict[str, Any]:
        normalized_id = str(period_id or "").strip()
        if not normalized_id:
            raise ValueError("Pilih Database Master/Periode sebelum import")
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            row = conn.execute("""SELECT periode_id,nama_periode,status,is_active
                FROM pengembalian_period WHERE periode_id=?""", [normalized_id]).fetchone()
            if not row:
                raise ValueError("Database Master/Periode tidak ditemukan")
            status = str(row[2] or "DRAFT").upper()
            if status in {"LOCKED", "CLOSED", "ARCHIVED"}:
                raise ValueError(f"Database Master {normalized_id} berstatus {status} dan tidak menerima import")
            return {"periode_id": row[0], "nama_periode": row[1],
                    "status": status, "is_active": bool(row[3])}
        finally:
            self.repository.close(conn)

    def create_period(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        self.repository.ensure_schema()
        process_year = int(payload.get("tahun_proses") or payload.get("tahun"))
        process_month = int(payload.get("bulan_proses") or payload.get("bulan_awal"))
        source_year = int(payload.get("tahun_penghasilan") or process_year)
        source_month = int(payload.get("bulan_penghasilan") or payload.get("bulan_awal") or process_month)
        year = process_year
        start = int(payload.get("bulan_awal") or source_month)
        end = int(payload.get("bulan_akhir") or source_month)
        if not 1 <= start <= end <= 12:
            raise ValueError("Rentang bulan periode tidak valid")
        if not 1 <= process_month <= 12 or not 1 <= source_month <= 12:
            raise ValueError("Bulan proses/penghasilan tidak valid")
        period_id = str(payload.get("periode_id") or
                        f"RET-{process_year}-{process_month:02d}-{source_year}-{source_month:02d}")
        name = str(payload.get("nama_periode") or
                   f"Pengembalian {process_month:02d}/{process_year} untuk {source_month:02d}/{source_year}").strip()
        status = str(payload.get("status") or "DRAFT").strip().upper()
        if status not in {"DRAFT", "ACTIVE"}:
            raise ValueError("Periode baru harus berstatus DRAFT atau ACTIVE")
        created_by = str(payload.get("created_by") or "system")
        conn = self.repository.connect()
        try:
            conn.execute("BEGIN")
            if status == "ACTIVE" or bool(payload.get("is_active")):
                conn.execute("UPDATE pengembalian_period SET is_active=FALSE WHERE is_active=TRUE")
                status = "ACTIVE"
            conn.execute("""INSERT INTO pengembalian_period
                (periode_id,nama_periode,tahun,bulan_awal,bulan_akhir,status,
                 tahun_proses,bulan_proses,tahun_penghasilan,bulan_penghasilan,
                 is_active,created_by,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [period_id, name, year, start, end,
                    status, process_year, process_month, source_year, source_month,
                    status == "ACTIVE", created_by, payload.get("notes")])
            self._audit_period(conn, period_id, "CREATE", None, status,
                               {"nama_periode": name}, created_by)
            conn.commit()
            return {"status": "ok", "periode_id": period_id, "nama_periode": name,
                    "period_status": status, "is_active": status == "ACTIVE"}
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        finally:
            self.repository.close(conn)

    def transition_period(self, period_id: str, action: str,
                          created_by: str = "system") -> Dict[str, Any]:
        self.repository.ensure_schema()
        normalized_id, action = str(period_id).strip(), str(action).strip().upper()
        allowed = {"ACTIVATE", "LOCK", "ARCHIVE", "REOPEN"}
        if action not in allowed:
            raise ValueError("Aksi periode harus ACTIVATE, LOCK, ARCHIVE, atau REOPEN")
        conn = self.repository.connect()
        try:
            row = conn.execute("SELECT status FROM pengembalian_period WHERE periode_id=?",
                               [normalized_id]).fetchone()
            if not row: raise LookupError("Periode tidak ditemukan")
            previous = str(row[0] or "DRAFT").upper()
            if action == "ACTIVATE":
                new_status, active = "ACTIVE", True
            elif action == "LOCK":
                new_status, active = "LOCKED", False
            elif action == "ARCHIVE":
                new_status, active = "ARCHIVED", False
            else:
                new_status, active = "DRAFT", False
            conn.execute("BEGIN")
            if active:
                conn.execute("UPDATE pengembalian_period SET is_active=FALSE WHERE is_active=TRUE")
            conn.execute("""UPDATE pengembalian_period SET status=?,is_active=?,
                locked_at=CASE WHEN ?='LOCKED' THEN now() ELSE NULL END,
                archived_at=CASE WHEN ?='ARCHIVED' THEN now() ELSE NULL END,
                updated_at=now() WHERE periode_id=?""",
                [new_status, active, new_status, new_status, normalized_id])
            self._audit_period(conn, normalized_id, action, previous, new_status,
                               {}, created_by)
            conn.execute("COMMIT")
            return {"status": "ok", "periode_id": normalized_id,
                    "period_status": new_status, "is_active": active}
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        finally:
            self.repository.close(conn)

    def import_dataset(self, rows: Iterable[Mapping[str, Any]], metadata: Mapping[str, Any],
                       imported_by="system") -> Dict[str, Any]:
        """Archive an arbitrary table as ordered JSON rows; never ALTER source tables."""
        self.repository.ensure_schema()
        source_rows = [dict(row) for row in rows]
        if not source_rows:
            raise ValueError("Dataset kosong")
        headers = list(source_rows[0].keys())
        schema = [{"position": index, "original": header, "normalized": _key_name(header)}
                  for index, header in enumerate(headers)]
        month = _month_number(metadata.get("bulan"), metadata.get("sheet_name"),
                              metadata.get("nama_dataset"), metadata.get("filename"))
        checksum_payload = {
            "periode_id": metadata.get("periode_id"),
            "sheet_name": metadata.get("sheet_name"),
            "bulan": month,
            "rows": source_rows,
        }
        checksum = str(metadata.get("checksum") or hashlib.sha256(
            _json(checksum_payload).encode("utf-8")
        ).hexdigest())
        dataset_id = str(uuid.uuid4())
        conn = self.repository.connect()
        transaction_started = False
        try:
            duplicate = conn.execute(
                "SELECT dataset_id FROM pengembalian_archive_dataset WHERE checksum=? AND status='SUCCESS' LIMIT 1",
                [checksum],
            ).fetchone()
            if duplicate:
                raise ValueError(f"DATASET IDENTIK SUDAH ADA: {duplicate[0]}")
            conn.execute("BEGIN")
            transaction_started = True
            conn.execute("""INSERT INTO pengembalian_archive_dataset
                (dataset_id,periode_id,nama_dataset,jenis_dataset,source_filename,sheet_name,
                 jumlah_baris,jumlah_kolom,schema_json,checksum,imported_by,bulan,metadata_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [dataset_id, metadata.get("periode_id"), metadata.get("nama_dataset") or
                 metadata.get("filename") or "Data Dasar", metadata.get("jenis_dataset") or
                 "DATA_DASAR", metadata.get("filename"), metadata.get("sheet_name"),
                 len(source_rows), len(headers), _json(schema), checksum, imported_by,
                 month, _json(metadata)])
            conn.executemany("""INSERT INTO pengembalian_archive_dataset_row
                (dataset_id,row_number,row_json) VALUES (?,?,?)""",
                [(dataset_id, index, _json(row)) for index, row in enumerate(source_rows, 1)])
            conn.execute("COMMIT")
            transaction_started = False
            result = {"status": "ok", "dataset_id": dataset_id, "rows": len(source_rows),
                      "columns": len(headers), "schema": schema, "bulan": month}
        except Exception:
            if transaction_started:
                conn.execute("ROLLBACK")
            raise
        finally:
            self.repository.close(conn)
        if month in {10, 11, 12} and any(
                "total_potongan" in item["normalized"] for item in schema):
            result["materialization"] = self.materialize_rekap_dataset(
                dataset_id, rebuild=not bool(metadata.get("defer_rebuild"))
            )
        return result

    def materialize_rekap_dataset(self, dataset_id: str, rebuild: bool = True) -> Dict[str, Any]:
        """Normalize a JSON recap dataset into auditable NIP/month percentage rows."""
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            metadata = conn.execute("""SELECT periode_id,source_filename,sheet_name,bulan,
                nama_dataset,tanggal_import FROM pengembalian_archive_dataset
                WHERE dataset_id=?""", [dataset_id]).fetchone()
            if not metadata:
                raise LookupError("Dataset tidak ditemukan")
            period_id, filename, sheet_name, stored_month, dataset_name, _ = metadata
            month = _month_number(stored_month, sheet_name, dataset_name, filename)
            if month not in {10, 11, 12}:
                raise ValueError("Bulan rekap harus Oktober, November, atau Desember")
            records = conn.execute("""SELECT row_number,row_json
                FROM pengembalian_archive_dataset_row WHERE dataset_id=?
                ORDER BY row_number""", [dataset_id]).fetchall()
            if not records:
                raise ValueError("Dataset kosong")
            first = _json_load(records[0][1]) or {}
            normalized_headers = {_key_name(key): key for key in first}
            nip_header = next((original for key, original in normalized_headers.items()
                               if key in {"nip", "no_nip", "nomor_nip"}), None)
            value_header = next((original for key, original in normalized_headers.items()
                                 if "total_potongan" in key), None)
            if not nip_header or not value_header:
                raise ValueError("Header NIP/Total Potongan tidak ditemukan")

            rows, valid_count, error_count = [], 0, 0
            year_match = re.search(r"(20\d{2})", " ".join(str(value or "")
                                   for value in (dataset_name, filename, sheet_name)))
            year = int(year_match.group(1)) if year_match else None
            for row_number, row_json in records:
                source = _json_load(row_json) or {}
                nip = str(source.get(nip_header) or "").strip()
                raw = source.get(value_header)
                decimal = _decimal_number(raw)
                status, message = "VALID", None
                if not nip:
                    status, message = "ERROR", "NIP KOSONG"
                elif decimal is None:
                    status = "ERROR"
                    message = f"NILAI TIDAK VALID: {raw}" if raw not in (None, "") else "NILAI KOSONG"
                elif decimal < 0:
                    status, message = "ERROR", "PERSENTASE NEGATIF"
                elif decimal > 1 and decimal <= 100:
                    decimal = decimal / Decimal(100)
                    status, message = "WARNING", "DIKONVERSI DARI SKALA 0-100"
                elif decimal > 1:
                    status, message = "ERROR", "PERSENTASE DI ATAS 100%"
                if status == "ERROR":
                    error_count += 1
                    decimal = None
                else:
                    valid_count += 1
                rows.append((
                    str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{row_number}")),
                    period_id, dataset_id, nip, year, month,
                    str(decimal) if decimal is not None else None,
                    None if raw is None else str(raw), status, message,
                    filename, sheet_name, int(row_number),
                ))

            conn.execute("BEGIN")
            conn.execute("DELETE FROM pengembalian_dasar_rekap_absensi WHERE dataset_id=?",
                         [dataset_id])
            conn.executemany("""INSERT INTO pengembalian_dasar_rekap_absensi
                (record_id,periode_id,dataset_id,nip,tahun,bulan,persentase_potongan,
                 raw_value,validation_status,validation_message,source_filename,
                 source_sheet,source_row) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            conn.execute("UPDATE pengembalian_archive_dataset SET bulan=? WHERE dataset_id=?",
                         [month, dataset_id])
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.repository.close(conn)
        calculation = self.rebuild_dasar_absensi(period_id) if rebuild else None
        return {"status": "ok", "dataset_id": dataset_id, "periode_id": period_id,
                "bulan": month, "rows": len(rows), "valid_rows": valid_count,
                "error_rows": error_count, "calculation": calculation}

    def materialize_rekap_datasets(self, period_id: Optional[str] = None) -> Dict[str, Any]:
        """Materialize previously archived recap datasets, newest import last."""
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            sql = """SELECT dataset_id FROM pengembalian_archive_dataset
                WHERE status='SUCCESS' AND (jenis_dataset='DATA_DASAR_PERHITUNGAN_REKAP'
                OR upper(coalesce(sheet_name,'')) LIKE 'REKAP %')"""
            params = []
            if period_id:
                sql += " AND periode_id=?"
                params.append(period_id)
            sql += " ORDER BY tanggal_import"
            dataset_ids = [row[0] for row in conn.execute(sql, params).fetchall()]
        finally:
            self.repository.close(conn)
        results = [self.materialize_rekap_dataset(item, rebuild=False) for item in dataset_ids]
        calculation = self.rebuild_dasar_absensi(period_id) if period_id and results else None
        return {"status": "ok", "datasets": len(results), "results": results,
                "calculation": calculation}

    def rebuild_dasar_absensi(self, period_id: str) -> Dict[str, Any]:
        """Build the formula Total Tukin × 30% × recap percentage for Final SDM."""
        self.repository.ensure_schema()
        normalized_id = str(period_id or "").strip()
        if not normalized_id:
            raise ValueError("periode_id wajib diisi")
        conn = self.repository.connect()
        try:
            recap_records = conn.execute("""SELECT nip,bulan,persentase_potongan,
                    validation_status,validation_message,dataset_id,raw_value
                FROM (
                    SELECT r.*,d.tanggal_import,
                        row_number() OVER (PARTITION BY r.periode_id,r.nip,r.bulan
                            ORDER BY d.tanggal_import DESC,r.created_at DESC) AS rank
                    FROM pengembalian_dasar_rekap_absensi r
                    JOIN pengembalian_archive_dataset d USING(dataset_id)
                    WHERE r.periode_id=?
                ) ranked WHERE rank=1""", [normalized_id]).fetchall()
            recap = {}
            for nip, month, percent, status, message, source_id, raw in recap_records:
                recap[(str(nip), int(month))] = {
                    "percent": _decimal_number(percent), "status": status,
                    "message": message, "dataset_id": source_id, "raw": raw,
                }
            final_records = conn.execute("""SELECT record_id,nip,row_json
                FROM pengembalian_final WHERE periode_id=? ORDER BY record_id""",
                [normalized_id]).fetchall()
            prepared = []
            month_names = ((10, "oktober"), (11, "november"), (12, "desember"))
            for record_id, nip, row_json in final_records:
                row = _json_load(row_json) or {}
                total_tukin = _decimal_number(row.get("total_tukin"))
                basis_30 = total_tukin * Decimal("0.30") if total_tukin is not None else None
                raw_months, issues, source_ids, percentages = {}, [], {}, {}
                for month, name in month_names:
                    item = recap.get((str(nip), month))
                    if item is None:
                        percentages[name] = None
                        raw_months[name] = None
                        issues.append(f"REKAP {name.upper()} TIDAK DITEMUKAN")
                        continue
                    source_ids[name] = item["dataset_id"]
                    percentages[name] = item["percent"]
                    if item["status"] == "ERROR" or item["percent"] is None:
                        raw_months[name] = None
                        issues.append(item["message"] or f"REKAP {name.upper()} TIDAK VALID")
                    elif basis_30 is None:
                        raw_months[name] = None
                        issues.append("TOTAL TUKIN TIDAK TERSEDIA")
                    else:
                        raw_months[name] = basis_30 * item["percent"]
                prepared.append({
                    "record_id": str(record_id), "nip": str(nip), "row": row,
                    "total_tukin": total_tukin, "basis_30": basis_30,
                    "percentages": percentages, "raw": raw_months,
                    "issues": sorted(set(issues)), "source_ids": source_ids,
                })

            rounded = {}
            rounding_summary = {}
            for _, name in month_names:
                result = sum_preserving_round(
                    [item["raw"][name] for item in prepared],
                    [item["record_id"] for item in prepared],
                )
                rounding_summary[name] = {
                    "raw_total": str(result["raw_total"]),
                    "rounded_total": result["rounded_total"],
                    "adjusted_record_count": result["adjusted_record_count"],
                    "zero_modified_count": result["zero_modified_count"],
                }
                for item, value in zip(prepared, result["values"]):
                    rounded[(item["record_id"], name)] = value

            values = []
            valid = warning = error = 0
            for item in prepared:
                row = item["row"]
                nominal = {name: rounded[(item["record_id"], name)] for _, name in month_names}
                nominal_total = sum(value or 0 for value in nominal.values())
                current = {name: _rupiah(row.get(f"final_pengembalian_tukin_{name}"))
                           for _, name in month_names}
                current_total = _rupiah(row.get("final_total_pengembalian_tukin"))
                status = "ERROR" if any("TIDAK VALID" in issue or "TOTAL TUKIN" in issue
                                         for issue in item["issues"]) else (
                    "WARNING" if item["issues"] else "VALID")
                valid += status == "VALID"
                warning += status == "WARNING"
                error += status == "ERROR"
                values.append((
                    str(uuid.uuid5(uuid.NAMESPACE_URL,
                        f"dasar-absensi:{normalized_id}:{item['record_id']}")),
                    normalized_id, item["record_id"], item["nip"],
                    str(item["total_tukin"]) if item["total_tukin"] is not None else None,
                    str(item["basis_30"]) if item["basis_30"] is not None else None,
                    *(str(item["percentages"][name]) if item["percentages"][name] is not None else None
                      for _, name in month_names),
                    *(str(item["raw"][name]) if item["raw"][name] is not None else None
                      for _, name in month_names),
                    *(nominal[name] for _, name in month_names), nominal_total,
                    *(current[name] for _, name in month_names), current_total,
                    *((nominal[name] - current[name]) if nominal[name] is not None and current[name] is not None else None
                      for _, name in month_names),
                    (nominal_total - current_total) if current_total is not None else None,
                    status, _json(item["issues"]), _json(item["source_ids"]),
                    "ABSENSI_REKAP_V1=TOTAL_TUKIN*30%*PERSENTASE_REKAP",
                ))
            conn.execute("BEGIN")
            conn.execute("DELETE FROM pengembalian_dasar_kalkulasi_absensi WHERE periode_id=?",
                         [normalized_id])
            if values:
                conn.executemany("""INSERT INTO pengembalian_dasar_kalkulasi_absensi
                    (calculation_id,periode_id,final_record_id,nip,total_tukin,tukin_absen_30,
                     persen_oktober,persen_november,persen_desember,
                     raw_oktober,raw_november,raw_desember,
                     nominal_oktober,nominal_november,nominal_desember,nominal_total,
                     current_oktober,current_november,current_desember,current_total,
                     selisih_oktober,selisih_november,selisih_desember,selisih_total,
                     validation_status,issues_json,source_dataset_ids,formula_version)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values)
            conn.execute("COMMIT")
            return {"status": "ok", "periode_id": normalized_id, "rows": len(values),
                    "valid": valid, "warning": warning, "error": error,
                    "rounding": rounding_summary}
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.repository.close(conn)

    @staticmethod
    def _calculation_payload(record: Mapping[str, Any]) -> Dict[str, Any]:
        clean = {key: _clean(value) for key, value in record.items()}
        issues = _json_load(clean.pop("issues_json", None)) or []
        source_ids = _json_load(clean.pop("source_dataset_ids", None)) or {}
        months = {}
        for name in ("oktober", "november", "desember"):
            months[name] = {
                "persentase_potongan": clean.get(f"persen_{name}"),
                "nominal_raw": clean.get(f"raw_{name}"),
                "nominal_dasar": clean.get(f"nominal_{name}"),
                "nominal_final_saat_ini": clean.get(f"current_{name}"),
                "selisih_dasar_vs_final": clean.get(f"selisih_{name}"),
                "dataset_id": source_ids.get(name),
            }
        return {
            "calculation_id": clean.get("calculation_id"),
            "periode_id": clean.get("periode_id"),
            "final_record_id": clean.get("final_record_id"),
            "nip": clean.get("nip"),
            "total_tukin": clean.get("total_tukin"),
            "tukin_absen_30": clean.get("tukin_absen_30"),
            "formula": clean.get("formula_version"),
            "status": clean.get("validation_status"),
            "issues": issues,
            "months": months,
            "nominal_dasar_total": clean.get("nominal_total"),
            "nominal_final_total_saat_ini": clean.get("current_total"),
            "selisih_dasar_vs_final_total": clean.get("selisih_total"),
            "calculated_at": clean.get("calculated_at"),
        }

    def dasar_absensi(self, nip: Optional[str] = None,
                      period_id: Optional[str] = None,
                      final_record_id: Optional[str] = None) -> Dict[str, Any]:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            clauses, params = [], []
            for column, value in (("nip", nip), ("periode_id", period_id),
                                  ("final_record_id", final_record_id)):
                if value not in (None, ""):
                    clauses.append(f"{column}=?")
                    params.append(value)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            frame = conn.execute("SELECT * FROM pengembalian_dasar_kalkulasi_absensi" +
                                 where + " ORDER BY nip,final_record_id", params).fetchdf()
            rows = [self._calculation_payload(row)
                    for row in frame.to_dict(orient="records")]
            return {"status": "ok", "rows": rows, "count": len(rows)}
        finally:
            self.repository.close(conn)

    def rekap_absensi(self, nip: str, period_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the latest source recap value for each employee/month."""
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            period_clause = " AND r.periode_id=?" if period_id else ""
            params = [str(nip)] + ([str(period_id)] if period_id else [])
            frame = conn.execute(f"""SELECT * EXCLUDE (rank) FROM (
                    SELECT r.*,d.nama_dataset,d.tanggal_import,
                        row_number() OVER (PARTITION BY r.periode_id,r.nip,r.bulan
                            ORDER BY d.tanggal_import DESC,r.created_at DESC) rank
                    FROM pengembalian_dasar_rekap_absensi r
                    JOIN pengembalian_archive_dataset d USING(dataset_id)
                    WHERE r.nip=?{period_clause}
                ) source WHERE rank=1 ORDER BY periode_id,bulan""", params).fetchdf()
            rows = [{key: _clean(value) for key, value in row.items()}
                    for row in frame.to_dict(orient="records")]
            return {"status": "ok", "rows": rows, "count": len(rows)}
        finally:
            self.repository.close(conn)

    def _attach_dasar_calculation(self, conn, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        record_ids = [str(row.get("record_id") or "") for row in rows if row.get("record_id")]
        if len(record_ids) <= 1000:
            placeholders = ",".join("?" for _ in record_ids)
            sql = ("SELECT * FROM pengembalian_dasar_kalkulasi_absensi WHERE final_record_id IN (" +
                   placeholders + ")")
            frame = conn.execute(sql, record_ids).fetchdf() if record_ids else pd.DataFrame()
        else:
            periods = sorted({str(row.get("periode_id") or "") for row in rows
                              if row.get("periode_id")})
            placeholders = ",".join("?" for _ in periods)
            sql = ("SELECT * FROM pengembalian_dasar_kalkulasi_absensi WHERE periode_id IN (" +
                   placeholders + ")")
            frame = conn.execute(sql, periods).fetchdf() if periods else pd.DataFrame()
        calculations = {
            str(record["final_record_id"]): self._calculation_payload(record)
            for record in frame.to_dict(orient="records")
        }
        for row in rows:
            payload = calculations.get(str(row.get("record_id")))
            if not payload:
                continue
            row["dasar_perhitungan_absensi"] = payload
            row["nilai_dasar_absensi"] = payload["nominal_dasar_total"]
            row.setdefault("traceability", {})["dasar_perhitungan_absensi"] = payload

    def datasets(self, limit=100, offset=0) -> Dict[str, Any]:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM pengembalian_archive_dataset").fetchone()[0]
            frame = conn.execute("""SELECT * FROM pengembalian_archive_dataset
                ORDER BY tanggal_import DESC LIMIT ? OFFSET ?""", [int(limit), int(offset)]).fetchdf()
            rows = frame.to_dict(orient="records")
            for row in rows:
                row["schema"] = _json_load(row.pop("schema_json", None)) or []
            return {"status": "ok", "rows": rows, "total": total}
        finally:
            self.repository.close(conn)

    def dataset_rows(self, dataset_id: str, search=None, limit=100, offset=0) -> Dict[str, Any]:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            where, params = "dataset_id=?", [dataset_id]
            if search:
                where += " AND row_json ILIKE ?"
                params.append(f"%{search}%")
            total = conn.execute(f"SELECT COUNT(*) FROM pengembalian_archive_dataset_row WHERE {where}", params).fetchone()[0]
            records = conn.execute(f"""SELECT row_number,row_json FROM pengembalian_archive_dataset_row
                WHERE {where} ORDER BY row_number LIMIT ? OFFSET ?""",
                params + [int(limit), int(offset)]).fetchall()
            return {"status": "ok", "rows": [_json_load(row[1]) for row in records],
                    "row_numbers": [row[0] for row in records], "total": total}
        finally:
            self.repository.close(conn)

    def export_dataset_xlsx(self, dataset_id: str) -> bytes:
        data = self.dataset_rows(dataset_id, limit=1_000_000)
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            pd.DataFrame(data["rows"]).to_excel(writer, index=False, sheet_name="DATA")
        return output.getvalue()

    @staticmethod
    def _payment_status(value: Any) -> str:
        status = _key_name(value).upper()
        if status in {"SUCCESS", "SUKSES", "BERHASIL", "BERHASIL_DEBIT"}:
            return "BERHASIL"
        if status in {"FAILED", "FAIL", "GAGAL", "GAGAL_DEBIT"}:
            return "GAGAL"
        raise ValueError(f"Status debit tidak dikenali: {value}")

    def import_payments(self, rows: Iterable[Mapping[str, Any]], metadata=None,
                        imported_by="system") -> Dict[str, Any]:
        self.repository.ensure_schema()
        metadata = dict(metadata or {})
        final_rows = self.final({"limit": 100000})["rows"]
        by_nip = {}
        for item in final_rows:
            by_nip.setdefault(str(item.get("nip") or ""), []).append(item)
        prepared = []
        for source in rows:
            normalized = {_key_name(key): value for key, value in source.items()}
            nip = _clean(normalized.get("nip") or normalized.get("nomor_nip") or normalized.get("no_nip"))
            nominal = _number(normalized.get("nominal") or normalized.get("nominal_debit") or normalized.get("jumlah"))
            if not nip or nominal is None or nominal < 0:
                raise ValueError("Setiap transaksi wajib memiliki NIP dan nominal non-negatif")
            key = _clean(normalized.get("obligation_key") or normalized.get("comparison_key"))
            candidates = by_nip.get(str(nip), [])
            if not key:
                period_id = _clean(normalized.get("periode_id") or metadata.get("periode_id"))
                if period_id:
                    candidates = [row for row in candidates if row.get("periode_id") == period_id]
                if len(candidates) != 1:
                    raise ValueError(f"Kewajiban NIP {nip} ambigu; isi obligation_key/periode_id")
                key = candidates[0]["comparison_key"]
            status = self._payment_status(normalized.get("status") or normalized.get("status_debit"))
            prepared.append((str(uuid.uuid4()), key, metadata.get("periode_id"), str(nip),
                             _clean(normalized.get("tanggal") or normalized.get("tanggal_debit")),
                             _clean(normalized.get("bulan") or normalized.get("bulan_debit")),
                             nominal, _clean(normalized.get("komponen")), status,
                             _clean(normalized.get("alasan") or normalized.get("alasan_gagal") or normalized.get("keterangan")),
                             _clean(normalized.get("kategori_gagal")),
                             _clean(normalized.get("batch") or normalized.get("batch_debit")),
                             metadata.get("filename"), _json(dict(source)), imported_by))
        conn = self.repository.connect()
        try:
            conn.execute("BEGIN")
            conn.executemany("""INSERT INTO pengembalian_payment_transaction
                (transaction_id,obligation_key,periode_id,nip,tanggal_debit,bulan_debit,
                 nominal,komponen,status_debit,alasan_gagal,kategori_gagal,batch_debit,
                 source_import,raw_data,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", prepared)
            conn.execute("COMMIT")
            result = {"status": "ok", "inserted": len(prepared)}
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self.repository.close(conn)
        self.rebuild_final({"periode_id": metadata.get("periode_id")}
                           if metadata.get("periode_id") else {})
        return result

    @staticmethod
    def comparison_key(row: Mapping[str, Any]) -> str:
        values = [("nip", row.get("nip"))]
        if _clean(row.get("periode_id")) is not None:
            values.append(("periode_id", row.get("periode_id")))
        values.append(("tahun_sp2d", row.get("tahun_sp2d")))
        for field in ("periode", "bulan", "batch", "komponen"):
            if _clean(row.get(field)) is not None:
                values.append((field, row.get(field)))
        return "|".join(f"{name}={value}" for name, value in values)

    @staticmethod
    def _comparison_values(row: Optional[Mapping[str, Any]]) -> Dict[str, Optional[float]]:
        row = row or {}
        values = {component: _number(row.get(component)) for component in COMPONENTS}
        if values["total_potongan_absen"] is None:
            values["total_potongan_absen"] = _number(
                row.get("calculated_total_potongan_absen")
            )
        if values["total_potongan_tukin"] is None:
            values["total_potongan_tukin"] = _number(
                row.get("calculated_total_potongan_tukin")
            )
        return values

    @staticmethod
    def _identity(a_row: Optional[Mapping[str, Any]],
                  b_row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        a_row, b_row = a_row or {}, b_row or {}
        raw = b_row.get("raw_data") or a_row.get("raw_data") or {}
        return {
            field: b_row.get(field) if b_row.get(field) is not None
            else a_row.get(field)
            for field in ("nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun",
                          "bulan", "periode", "komponen", "unit_kerja")
        } | {
            field: (b_row.get(field) if b_row.get(field) is not None
                    else a_row.get(field) if a_row.get(field) is not None
                    else raw.get(field))
            for field in (
                "provinsi", "kabupaten_kota", "kdanaksatker",
                "kode_anak_satker", "tahun_sp2d_sebelumnya",
                "tahun_sp2d_update", "status_sp2d", "nama_bank",
                "nomor_rekening", "nama_direk",
            )
        }

    @staticmethod
    def _traceability(a_row: Optional[Mapping[str, Any]],
                      b_row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        a_row, b_row = a_row or {}, b_row or {}
        a_raw, b_raw = a_row.get("raw_data") or {}, b_row.get("raw_data") or {}
        daily_keys = ("daily_data", "daily_records", "absensi_harian", "data_harian")
        a_daily = next((a_raw.get(key) for key in daily_keys if a_raw.get(key)), None)
        b_daily = next((b_raw.get(key) for key in daily_keys if b_raw.get(key)), None)
        refs = {
            "daily_ref": b_row.get("daily_ref") or a_row.get("daily_ref"),
            "monthly_ref": b_row.get("monthly_ref") or a_row.get("monthly_ref"),
            "absence_ref": b_row.get("absence_ref") or a_row.get("absence_ref"),
            "total_tukin_ref": b_row.get("total_tukin_ref") or a_row.get("total_tukin_ref"),
        }
        if a_daily is not None or b_daily is not None:
            return {
                "source_type": "ABSENSI_HARIAN",
                "source_status": "TERIDENTIFIKASI",
                "source_reference": refs,
                "daily": {"data_awal": a_daily or [], "data_penyesuaian": b_daily or []},
                "chain": ["Data Harian", "Rekap Bulanan", "Potongan Absen", "Total Potongan Tukin"],
            }
        return {
            "source_type": "UNKNOWN",
            "source_status": SOURCE_UNKNOWN,
            "source_reference": refs,
            "daily": {"data_awal": [], "data_penyesuaian": []},
            "chain": ["Data Harian", "Rekap Bulanan", "Potongan Absen", "Total Potongan Tukin"],
        }

    def compare(self, filters: Optional[Mapping[str, Any]] = None,
                source_a: str = SOURCE_AWAL, source_b: str = SOURCE_PENYESUAIAN,
                created_by: str = "system", persist: bool = True) -> Dict[str, Any]:
        source_a, source_b = _canonical_source(source_a), _canonical_source(source_b)
        filters = dict(filters or {})
        left = self.repository.rows(source_a, filters)
        right = self.repository.rows(source_b, filters)
        groups_a: Dict[str, List[Dict[str, Any]]] = {}
        groups_b: Dict[str, List[Dict[str, Any]]] = {}
        for row in left:
            groups_a.setdefault(self.comparison_key(row), []).append(row)
        for row in right:
            groups_b.setdefault(self.comparison_key(row), []).append(row)

        # Load BPK history once. The previous per-record query made a 32k-row
        # Final page execute 32k extra DuckDB queries.
        bpk_by_key: Dict[str, List[Dict[str, Any]]] = {}
        for history_row in self.repository.bpk_history():
            bpk_by_key.setdefault(str(history_row.get("comparison_key")), []).append(history_row)

        details = []
        counts = {"unchanged": 0, "changed": 0, "new": 0, "missing": 0, "duplicate": 0}
        for key in sorted(set(groups_a) | set(groups_b)):
            a_rows, b_rows = groups_a.get(key, []), groups_b.get(key, [])
            flags: List[str] = []
            status = "CHANGED"
            traceability = self._traceability(a_rows[0] if a_rows else None,
                                              b_rows[0] if b_rows else None)
            bpk_history = bpk_by_key.get(key, [])
            bpk_current = bpk_history[-1] if bpk_history else None
            if len(a_rows) > 1 or len(b_rows) > 1:
                flags = ["DUPLIKASI", "RECORD GANDA - PERLU KONFIRMASI"]
                result_type = "DUPLIKASI"
                status = "DUPLICATE"
                compare_status = "NEED REVIEW"
                counts["duplicate"] += 1
            elif not a_rows:
                result_type = "BARU"
                status = "NEW"
                compare_status = "DATA BARU"
                flags = ["BARU DI DATA_PENYESUAIAN", "DATA BARU"]
                counts["new"] += 1
            elif not b_rows:
                result_type = "HILANG"
                status = "MISSING"
                compare_status = "DATA HILANG"
                flags = ["HILANG DI DATA_PENYESUAIAN", "DATA HILANG"]
                counts["missing"] += 1
            else:
                changes = {}
                a_values, b_values = self._comparison_values(a_rows[0]), self._comparison_values(b_rows[0])
                for component in COMPONENTS:
                    av, bv = a_values.get(component), b_values.get(component)
                    if av is not None or bv is not None:
                        delta = None if av is None or bv is None else bv - av
                        if av is None or bv is None or abs((delta or 0)) > 1e-9:
                            changes[component] = {"data_awal": av, "data_penyesuaian": bv, "delta": delta}
                            flags.append("PERUBAHAN " + component.upper().replace("_", " "))
                result_type = "TIDAK_BERUBAH" if not changes else "BERUBAH"
                status = "UNCHANGED" if not changes else "CHANGED"
                compare_status = "TIDAK BERUBAH" if not changes else "BERUBAH"
                counts["unchanged" if not changes else "changed"] += 1
                if changes:
                    names = {
                        "esdm": "PERUBAHAN POTONGAN ABSEN",
                        "e_absensi": "PERUBAHAN POTONGAN ABSEN",
                        "total_potongan_absen": "PERUBAHAN POTONGAN ABSEN",
                        "potongan_skp": "PERUBAHAN POTONGAN SKP",
                        "tendik": "PERUBAHAN POTONGAN TENDIK",
                        "total_tukin": "PERUBAHAN NILAI TUKIN",
                        "total_potongan_tukin": "PERUBAHAN TOTAL PENGEMBALIAN",
                    }
                    flags.extend(names[field] for field in changes if names.get(field))
                    if any(field in changes for field in ("esdm", "e_absensi", "total_potongan_absen")):
                        flags.append("PERUBAHAN DASAR ABSENSI")
                    traceability = self._traceability(a_rows[0], b_rows[0])
                    if traceability["source_status"] == SOURCE_UNKNOWN:
                        flags.append(SOURCE_UNKNOWN)
                else:
                    flags.append("TIDAK BERUBAH")
            details.append({
                "comparison_key": key, "result_type": result_type, "status": status,
                "compare_status": compare_status,
                "result": status, "flag": " | ".join(flags), "flags": flags,
                "identity": self._identity(a_rows[0] if a_rows else None,
                                            b_rows[0] if b_rows else None),
                "initial_values": self._comparison_values(a_rows[0] if a_rows else None),
                "adjusted_values": self._comparison_values(b_rows[0] if b_rows else None),
                "changed_fields": list(changes.keys()) if result_type == "BERUBAH" else [],
                "changes": changes if result_type == "BERUBAH" else {},
                "data_awal": a_rows, "data_penyesuaian": b_rows,
                "traceability": traceability,
                "source_status": traceability["source_status"],
                "source_reference": traceability["source_reference"],
                "source_type": traceability["source_type"],
                "is_send_bpk": bool(bpk_history),
                "bpk_batch": bpk_current.get("bpk_batch") if bpk_current else None,
                "bpk_batch_label": (bpk_current.get("bpk_batch_label")
                                    if bpk_current else "BELUM SEND BPK"),
                "tanggal_send_bpk": (bpk_current.get("tanggal_send_bpk")
                                     if bpk_current else None),
                "bpk_reference": (bpk_current.get("bpk_reference")
                                  if bpk_current else None),
                "bpk_history": bpk_history,
            })

        result = {
            "source_a": source_a, "source_b": source_b, "filters": filters,
            "total_a": len(left), "total_b": len(right), "counts": counts,
            "unchanged_count": counts["unchanged"], "changed_count": counts["changed"],
            "new_count": counts["new"], "missing_count": counts["missing"],
            "duplicate_count": counts["duplicate"],
            "flags": sorted({flag for detail in details for flag in detail["flags"]}),
            "details": details,
        }
        if persist:
            result["compare_id"] = self._save_comparison(result, created_by)
        return result

    compare_sources = compare

    def _calculate_final(self, filters: Optional[Mapping[str, Any]] = None,
                         created_by: str = "system") -> Dict[str, Any]:
        """Return the latest reconciliation projection without copying source rows."""
        filters = dict(filters or {})
        bpk_batch = filters.pop("bpk_batch", None)
        status_compare = filters.pop("status_compare", None)
        payment_status = filters.pop("payment_status", None)
        change_class = filters.pop("change_class", None)
        record_ids = filters.pop("record_ids", None)
        derived_filters = {
            key: filters.pop(key, None) for key in (
                "arah_perubahan", "flag_ada_perubahan",
                "flag_perubahan_oktober", "flag_perubahan_november",
                "flag_perubahan_desember", "flag_perubahan_total",
                "batch_oktober_normalized", "batch_november_normalized",
                "batch_desember_normalized", "final_batch_normalized",
            )
        }
        # FINAL is a projection and must not silently truncate a large archive
        # at the repository's normal list-page size.
        filters.setdefault("limit", 100000)
        filters["_lightweight"] = True
        comparison = self.compare(filters=filters, created_by=created_by, persist=False)
        rows = []
        for detail in comparison["details"]:
            if bpk_batch is not None and not any(
                    item.get("bpk_batch") == int(bpk_batch)
                    for item in detail["bpk_history"]):
                continue
            initial = detail["data_awal"][0] if detail["data_awal"] else None
            adjusted = detail["data_penyesuaian"][-1] if detail["data_penyesuaian"] else None
            latest = adjusted or initial or {}
            initial_values = detail["initial_values"]
            adjusted_values = detail["adjusted_values"]
            # Adjustment files commonly contain only the corrected columns.
            # Preserve unchanged source values instead of turning omitted
            # columns into NULL in the current-state projection.
            # DATA_FINAL also represents records that only exist in DATA_AWAL.
            # Start from the initial values in both cases, then overlay only
            # values explicitly supplied by DATA_PENYESUAIAN.
            merged_values = dict(initial_values)
            merged_values.update({
                key: value for key, value in adjusted_values.items()
                if value is not None
            })
            repayment_fields = (
                ("tukin_pengembalian_oktober", "final_pengembalian_tukin_oktober"),
                ("tukin_pengembalian_november", "final_pengembalian_tukin_november"),
                ("tukin_pengembalian_desember", "final_pengembalian_tukin_desember"),
                ("total_awal_tukin", "final_total_pengembalian_tukin"),
            )
            repayment_changes = []
            repayment_compared = 0
            for awal_field, final_field in repayment_fields:
                awal_value = _rupiah((initial or {}).get(awal_field))
                final_value = _rupiah((latest or {}).get(final_field))
                if awal_value is not None and final_value is not None:
                    repayment_compared += 1
                if awal_value is not None and final_value is not None and awal_value != final_value:
                    repayment_changes.append({
                        "field": final_field, "awal": awal_value,
                        "final": final_value, "delta": final_value - awal_value,
                    })
            # Legacy archive rows may only expose total_potongan_tukin. Use it
            # only when none of the explicit Tukin comparison pairs exists.
            if not repayment_compared and initial and adjusted:
                awal_legacy = _rupiah(initial_values.get("total_potongan_tukin"))
                final_legacy = _rupiah(adjusted_values.get("total_potongan_tukin"))
                if awal_legacy is not None and final_legacy is not None and awal_legacy != final_legacy:
                    repayment_changes.append({
                        "field": "total_potongan_tukin", "awal": awal_legacy,
                        "final": final_legacy, "delta": final_legacy - awal_legacy,
                    })
                elif detail.get("result_type") == "BERUBAH":
                    # Compatibility for legacy archives that predate the
                    # explicit Oktober/November/Desember + Final columns.
                    for field, change in detail.get("changes", {}).items():
                        repayment_changes.append({
                            "field": field, "awal": _rupiah(change.get("data_awal")),
                            "final": _rupiah(change.get("data_penyesuaian")),
                            "delta": _rupiah(change.get("delta")),
                        })
            # Flaging in the latest/final workbook is the authoritative
            # business classification. Delta inference remains a fallback for
            # older imports that do not contain that column.
            source_business_status = _source_change_flag(latest)
            business_status = source_business_status or (
                "BERUBAH" if repayment_changes else "TIDAK BERUBAH"
            )
            reconciliation_status = detail["compare_status"]
            # A source-side flag from DATA_AWAL cannot turn a record that is
            # absent from DATA_PENYESUAIAN into "TIDAK BERUBAH". Presence on
            # only one side is authoritative for DATA BARU / DATA HILANG.
            if not initial or not adjusted:
                business_status = reconciliation_status
            deltas = {
                field: (merged_values.get(field) - initial_values.get(field)
                        if merged_values.get(field) is not None and initial_values.get(field) is not None
                        else None)
                for field in COMPONENTS
            }
            rows.append({
                "record_id": f"FINAL:{detail['comparison_key']}",
                "comparison_key": detail["comparison_key"],
                "initial_record_id": initial.get("row_id") if initial else None,
                "latest_adjustment_record_id": adjusted.get("row_id") if adjusted else None,
                "identity": detail["identity"],
                "tahun_sp2d": latest.get("tahun_sp2d") or detail["identity"].get("tahun_sp2d"),
                "initial_values": initial_values,
                "final_values": merged_values,
                "nilai_awal": (
                    (initial or {}).get("total_awal_tukin")
                    if (initial or {}).get("total_awal_tukin") is not None
                    else initial_values.get("total_potongan_tukin")
                ),
                "nilai_final": (
                    (latest or {}).get("final_total_pengembalian_tukin")
                    if (latest or {}).get("final_total_pengembalian_tukin") is not None
                    else (latest or {}).get("total_awal_tukin")
                    if (latest or {}).get("total_awal_tukin") is not None
                    else merged_values.get("total_potongan_tukin")
                ),
                "selisih": None,
                "deltas": deltas,
                "status_compare": business_status,
                "status_perubahan": business_status,
                "reconciliation_status": reconciliation_status,
                "changed_fields": [item["field"] for item in repayment_changes],
                "repayment_changes": repayment_changes,
                "pernah_send_bpk": detail["is_send_bpk"],
                "bpk_batch": detail["bpk_batch"],
                "tanggal_send_bpk": detail["tanggal_send_bpk"],
                "bpk_reference": detail["bpk_reference"],
                "bpk_history": detail["bpk_history"],
                "source_version": initial.get("import_id") if initial else None,
                "current_version": latest.get("import_id"),
                "traceability": {
                    "data_awal": detail["data_awal"],
                    "send_bpk": detail["bpk_history"],
                    "data_penyesuaian": detail["data_penyesuaian"],
                    "final": detail,
                },
            })
            rows[-1]["nilai_awal"] = _rupiah(rows[-1]["nilai_awal"])
            rows[-1]["nilai_final"] = _rupiah(rows[-1]["nilai_final"])
            rows[-1]["selisih"] = rows[-1]["nilai_final"] - rows[-1]["nilai_awal"] \
                if rows[-1]["nilai_final"] is not None and rows[-1]["nilai_awal"] is not None else None
            # Expose the current-state fields at the top level as well as in
            # final_values.  Consumers such as the BNBA grid and CSV export
            # should not need to understand the internal comparison shape.
            rows[-1].update({
                field: detail["identity"].get(field)
                for field in (
                    "nip", "nama", "periode_id", "tahun_sp2d", "nomor_sp2d", "tahun",
                    "bulan", "periode", "komponen", "provinsi",
                    "kabupaten_kota", "kdanaksatker",
                )
            })
            rows[-1].update({
                field: latest.get(field)
                for field in (
                    "unit_kerja", "jabatan", "golongan", "status",
                    "nomor_rekening", "kode_bank", "nama_bank",
                    "nama_direk", "source_file", "source_sheet",
                    "final_pengembalian_tukin_oktober",
                    "final_pengembalian_tukin_november",
                    "final_pengembalian_tukin_desember",
                    "final_total_pengembalian_tukin",
                    "final_total_pengembalian_uang_makan",
                    "final_total_pengembalian_tukin_uang_makan",
                )
            })
            source_batch = latest.get("batch")
            if source_batch is None or str(source_batch).strip() == "":
                source_batch = (initial or {}).get("batch")
            rows[-1]["batch"] = source_batch
            rows[-1]["batch_bpk"] = source_batch
            rows[-1]["total_awal_tukin"] = _number((initial or {}).get("total_awal_tukin"))
            for field in (
                "tukin_pengembalian_oktober", "tukin_pengembalian_november",
                "tukin_pengembalian_desember", "total_awal_tukin",
                "final_pengembalian_tukin_oktober", "final_pengembalian_tukin_november",
                "final_pengembalian_tukin_desember", "final_total_pengembalian_tukin",
            ):
                rows[-1][field] = ((latest if field.startswith("final_") else initial) or {}).get(field)
            rows[-1].update({
                field: value
                for field, value in merged_values.items()
                if field in COMPONENTS
            })
            # Keep BNBA-derived values available on FINAL rows so filtering,
            # table display, and export use the same current-state record.
            for field in (
                "batch_oktober_normalized", "batch_november_normalized",
                "batch_desember_normalized", "final_batch_normalized",
            ):
                rows[-1][field] = latest.get(field)
            for month in ("oktober", "november", "desember"):
                initial_month = _rupiah((initial or {}).get(f"tukin_pengembalian_{month}"))
                final_month = _rupiah(latest.get(f"final_pengembalian_tukin_{month}"))
                delta = (final_month - initial_month
                         if initial_month is not None and final_month is not None else None)
                rows[-1][f"selisih_{month}"] = delta
                rows[-1][f"flag_perubahan_{month}"] = (
                    "BERUBAH" if delta is not None and delta != 0 else "TIDAK BERUBAH"
                )
                rows[-1][f"tukin_pengembalian_{month}"] = initial_month
                rows[-1][f"final_pengembalian_tukin_{month}"] = final_month
                rows[-1][f"pengurangan_{month}"] = -delta if delta is not None else None
                rows[-1][f"klasifikasi_{month}"] = (
                    "TIDAK BERUBAH" if delta in (None, 0)
                    else "MENJADI 0" if initial_month not in (None, 0) and final_month == 0
                    else "DARI 0 MENJADI ADA" if initial_month == 0 and final_month not in (None, 0)
                    else "NAIK" if delta is not None and delta > 0 else "TURUN"
                )
            rows[-1]["selisih_total_tukin"] = rows[-1]["selisih"]
            rows[-1]["flag_perubahan_total"] = (
                "BERUBAH" if rows[-1]["selisih_total_tukin"] not in (None, 0)
                else "TIDAK BERUBAH"
            )
            rows[-1]["flag_ada_perubahan"] = (
                "BERUBAH" if business_status == "BERUBAH"
                else "TIDAK BERUBAH"
            )
            rows[-1]["status_perubahan"] = rows[-1]["flag_ada_perubahan"]
            rows[-1]["ada_perubahan"] = (
                "YA" if rows[-1]["flag_ada_perubahan"] == "BERUBAH" else "TIDAK"
            )
            rows[-1]["jumlah_bulan_berubah"] = sum(
                1 for month in ("oktober", "november", "desember")
                if rows[-1][f"flag_perubahan_{month}"] == "BERUBAH"
            )
            rows[-1]["pengurangan_total"] = (
                -rows[-1]["selisih_total_tukin"]
                if rows[-1]["selisih_total_tukin"] is not None else None
            )
            rows[-1]["arah_perubahan"] = (
                "NAIK" if rows[-1]["selisih_total_tukin"] and rows[-1]["selisih_total_tukin"] > 0
                else "TURUN" if rows[-1]["selisih_total_tukin"] and rows[-1]["selisih_total_tukin"] < 0
                else "TETAP"
            )
        if status_compare not in (None, ""):
            allowed_statuses = {str(value) for value in _filter_values(status_compare)}
            rows = [row for row in rows if row.get("status_compare") in allowed_statuses]
        if record_ids:
            wanted = {str(item) for item in _filter_values(record_ids)}
            rows = [row for row in rows if str(row.get("record_id")) in wanted]
        for field, expected in derived_filters.items():
            if expected not in (None, ""):
                allowed_values = {str(value) for value in _filter_values(expected)}
                rows = [row for row in rows if str(row.get(field)) in allowed_values]
        # Decorate current obligations with successful/failed debit realization.
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            payment_rows = conn.execute("""SELECT obligation_key,
                SUM(CASE WHEN status_debit='BERHASIL' THEN nominal ELSE 0 END),
                SUM(CASE WHEN status_debit='GAGAL' THEN nominal ELSE 0 END)
                FROM pengembalian_payment_transaction GROUP BY obligation_key""").fetchall()
        finally:
            self.repository.close(conn)
        payment_map = {str(item[0]): (float(item[1] or 0), float(item[2] or 0))
                       for item in payment_rows}
        for row in rows:
            success, failed = payment_map.get(str(row["comparison_key"]), (0.0, 0.0))
            obligation = float(row.get("nilai_final") or 0)
            if obligation <= 0:
                status = "TIDAK ADA KEWAJIBAN" if success <= 0 else "LEBIH BAYAR / PERLU REVIEW"
            elif success <= 0:
                status = "BELUM ADA PENGEMBALIAN"
            elif success < obligation:
                status = "SEBAGIAN"
            elif success == obligation:
                status = "LUNAS"
            else:
                status = "LEBIH BAYAR / PERLU REVIEW"
            row.update({"total_debit_berhasil": success, "total_debit_gagal": failed,
                        "sisa_piutang": max(obligation - success, 0),
                        "kelebihan_bayar": max(success - obligation, 0),
                        "status_lunas": status})
        if payment_status not in (None, ""):
            allowed = {str(value) for value in _filter_values(payment_status)}
            rows = [row for row in rows if row.get("status_lunas") in allowed]
        if change_class not in (None, ""):
            allowed = {str(value) for value in _filter_values(change_class)}
            rows = [row for row in rows if any(
                row.get(f"klasifikasi_{month}") in allowed
                for month in ("oktober", "november", "desember")
            )]
        return {"status": "ok", "source_a": comparison["source_a"],
                "source_b": comparison["source_b"], "rows": rows,
                "count": len(rows), "compare": comparison}

    def rebuild_final(self, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Atomically replace the materialized current projection after import."""
        filters = dict(filters or {})
        calculated = self._calculate_final(filters)
        rows = calculated["rows"]
        period_id = filters.get("periode_id")
        conn = self.repository.connect()
        try:
            conn.execute("BEGIN")
            if period_id:
                conn.execute("DELETE FROM pengembalian_final WHERE periode_id=?", [period_id])
            else:
                conn.execute("DELETE FROM pengembalian_final")
            values = []
            for row in rows:
                values.append((
                    row["record_id"], row["comparison_key"], row.get("periode_id"),
                    row.get("nip"), row.get("nama"), row.get("tahun_sp2d"),
                    row.get("periode"), row.get("batch"), row.get("provinsi"), row.get("kabupaten_kota"),
                    row.get("unit_kerja"), row.get("status_compare"), row.get("arah_perubahan"),
                    row.get("ada_perubahan"), row.get("flag_ada_perubahan"),
                    row.get("status_lunas"), row.get("nilai_awal"), row.get("nilai_final"),
                    row.get("selisih_total_tukin"), row.get("total_debit_berhasil"),
                    row.get("total_debit_gagal"), row.get("sisa_piutang"), _json(row),
                    row.get("total_awal_tukin"),
                    row.get("final_total_pengembalian_tukin"),
                    row.get("final_total_pengembalian_uang_makan"),
                    row.get("final_total_pengembalian_tukin_uang_makan"),
                ))
            if values:
                frame = pd.DataFrame(values, columns=[
                    "record_id", "comparison_key", "periode_id", "nip", "nama",
                    "tahun_sp2d", "periode", "batch", "provinsi", "kabupaten_kota", "unit_kerja",
                    "status_compare", "arah_perubahan", "ada_perubahan",
                    "flag_ada_perubahan", "status_lunas", "nilai_awal", "nilai_final",
                    "selisih_total", "total_debit_berhasil", "total_debit_gagal",
                    "sisa_piutang", "row_json", "total_tukin_awal", "final_tukin", "final_uang_makan", "final_total",
                ])
                conn.register("_pengembalian_final_build", frame)
                conn.execute("""INSERT INTO pengembalian_final
                    (record_id,comparison_key,periode_id,nip,nama,tahun_sp2d,periode,batch,
                     provinsi,kabupaten_kota,unit_kerja,status_compare,arah_perubahan,
                     ada_perubahan,flag_ada_perubahan,status_lunas,nilai_awal,nilai_final,
                     selisih_total,total_debit_berhasil,total_debit_gagal,sisa_piutang,row_json,
                     total_tukin_awal,final_tukin,final_uang_makan,final_total)
                     SELECT * FROM _pengembalian_final_build""")
                conn.unregister("_pengembalian_final_build")
            conn.execute("COMMIT")
            return {"status": "ok", "rows": len(rows), "periode_id": period_id}
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            self.repository.close(conn)

    def final(self, filters: Optional[Mapping[str, Any]] = None,
              created_by: str = "system") -> Dict[str, Any]:
        """Read materialized Final when available; fall back for legacy/test DBs."""
        filters = dict(filters or {})
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            available = conn.execute("SELECT COUNT(*) FROM pengembalian_final").fetchone()[0]
            if not available:
                return self._calculate_final(filters, created_by)
            where, params = [], []
            effective_change = """CASE
                WHEN status_compare IN ('DATA BARU','DATA HILANG','NEED REVIEW') THEN status_compare
                WHEN flag_ada_perubahan='BERUBAH' OR COALESCE(nilai_final,0)<>COALESCE(nilai_awal,0) THEN 'BERUBAH'
                ELSE 'TIDAK BERUBAH' END"""
            mapping = {
                "periode_id": "periode_id", "nip": "nip", "nama": "nama",
                "tahun_sp2d": "tahun_sp2d", "periode": "periode",
                "batch": "batch",
                "provinsi": "provinsi", "kabupaten_kota": "kabupaten_kota",
                "unit_kerja": "unit_kerja", "arah_perubahan": "arah_perubahan",
                "payment_status": "status_lunas",
                "record_ids": "record_id",
            }
            for key, column in mapping.items():
                value = filters.get(key)
                if value not in (None, ""):
                    values_filter = _filter_values(value)
                    if key in {"status_perubahan", "flag_ada_perubahan"}:
                        values_filter = [str(item).replace("_", " ") for item in values_filter]
                    where.append(f"{column} IN ({','.join('?' for _ in values_filter)})")
                    params.extend(values_filter)
            for key in ("status_compare", "flag_ada_perubahan", "status_perubahan", "ada_perubahan"):
                value = filters.get(key)
                if value in (None, ""):
                    continue
                values_filter = [str(item).replace("_", " ") for item in _filter_values(value)]
                if key == "ada_perubahan":
                    values_filter = ["BERUBAH" if item in {"YA", "BERUBAH"} else "TIDAK BERUBAH" for item in values_filter]
                where.append(f"({effective_change}) IN ({','.join('?' for _ in values_filter)})")
                params.extend(values_filter)
            if filters.get("search"):
                where.append("(nip ILIKE ? OR nama ILIKE ? OR periode ILIKE ?)")
                term = f"%{filters['search']}%"
                params.extend([term, term, term])
            for key in ("flag_perubahan_oktober", "flag_perubahan_november",
                        "flag_perubahan_desember", "flag_perubahan_total",
                        "final_batch_normalized", "change_class"):
                value = filters.get(key)
                if value not in (None, ""):
                    params.append(f'%"{value}"%')
                    where.append("row_json ILIKE ?")
            clause = " WHERE " + " AND ".join(where) if where else ""
            total = conn.execute("SELECT COUNT(*) FROM pengembalian_final" + clause, params).fetchone()[0]
            page_limit = filters.get("_page_limit")
            page_offset = int(filters.get("_page_offset") or 0)
            sql = "SELECT row_json FROM pengembalian_final" + clause + " ORDER BY nip, record_id"
            query_params = list(params)
            if page_limit is not None:
                sql += " LIMIT ? OFFSET ?"
                query_params.extend([int(page_limit), page_offset])
            records = conn.execute(sql, query_params).fetchall()
            rows = [_json_load(record[0]) for record in records]
            self._attach_dasar_calculation(conn, rows)
            for row in rows:
                numeric_change = float(row.get("nilai_final") or 0) != float(row.get("nilai_awal") or 0)
                stored_status = row.get("status_compare")
                effective_status = (stored_status if stored_status in {"DATA BARU", "DATA HILANG", "NEED REVIEW"}
                                    else "BERUBAH" if row.get("flag_ada_perubahan") == "BERUBAH" or numeric_change
                                    else "TIDAK BERUBAH")
                binary_status = "BERUBAH" if effective_status == "BERUBAH" else "TIDAK BERUBAH"
                row["flag_ada_perubahan"] = binary_status
                row["status_perubahan"] = effective_status
                row["status_compare"] = effective_status
                row["ada_perubahan"] = "YA" if binary_status == "BERUBAH" else "TIDAK"
            return {"status": "ok", "source_a": SOURCE_AWAL,
                    "source_b": SOURCE_PENYESUAIAN, "rows": rows,
                    "count": len(rows), "total": total, "materialized": True}
        finally:
            self.repository.close(conn)

    def record_bpk_history(self, batch_id: str, items: Sequence[Mapping[str, Any]],
                           created_by: str = "system",
                           bpk_batch: Optional[int] = None) -> Dict[str, Any]:
        result = self.repository.record_bpk_history(batch_id, items, created_by, bpk_batch)
        self.rebuild_final()
        return result

    def _save_comparison(self, result: Mapping[str, Any], created_by: str) -> str:
        self.repository.ensure_schema()
        conn = self.repository.connect()
        compare_id = str(uuid.uuid4())
        try:
            conn.execute("BEGIN")
            c = result["counts"]
            conn.execute(
                """INSERT INTO pengembalian_archive_compare
                (compare_id, source_a, source_b, filters, finished_at, total_a, total_b,
                 unchanged_count, changed_count, new_count, missing_count, duplicate_count,
                 flags, created_by)
                VALUES (?, ?, ?, ?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [compare_id, result["source_a"], result["source_b"], _json(result["filters"]),
                 result["total_a"], result["total_b"], c["unchanged"], c["changed"],
                 c["new"], c["missing"], c["duplicate"], _json(
                     sorted({flag for d in result["details"] for flag in d["flags"]})
                 ), created_by],
            )
            for detail in result["details"]:
                conn.execute(
                    """INSERT INTO pengembalian_archive_compare_detail
                    (detail_id, compare_id, comparison_key, result_type, flags, changes,
                     data_awal, data_penyesuaian, source_status, source_reference, source_type,
                     identity, initial_values, adjusted_values, changed_fields)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [str(uuid.uuid4()), compare_id, detail["comparison_key"],
                     detail["result_type"], _json(detail["flags"]), _json(detail["changes"]),
                    _json(detail["data_awal"]), _json(detail["data_penyesuaian"]),
                    detail["source_status"], _json(detail["source_reference"]),
                    detail["source_type"], _json(detail["identity"]),
                    _json(detail["initial_values"]), _json(detail["adjusted_values"]),
                    _json(detail["changed_fields"])],
                )
            conn.execute("COMMIT")
            return compare_id
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.repository.close(conn)

    def list(self, source: str = SOURCE_AWAL, filters: Optional[Mapping[str, Any]] = None,
             **filter_values):
        merged = dict(filters or {})
        merged.update({key: value for key, value in filter_values.items() if value is not None})
        if _canonical_source(source) == SOURCE_FINAL:
            return self.final(merged).get("rows", [])
        bpk_batch = merged.pop("bpk_batch", None)
        # Archive browsing/history must expose every immutable source version;
        # current/final calculations continue to use active imports only.
        merged["_include_inactive"] = True
        rows = self.repository.rows(source, merged)
        if bpk_batch is not None:
            history = self.repository.bpk_history(batch=int(bpk_batch))
            keys = {item["comparison_key"] for item in history}
            rows = [row for row in rows if self.comparison_key(row) in keys]
        for row in rows:
            history = self.repository.bpk_history([self.comparison_key(row)])
            current = history[-1] if history else None
            row.update({
                "is_send_bpk": bool(history),
                "bpk_batch": current.get("bpk_batch") if current else None,
                "bpk_batch_label": current.get("bpk_batch_label") if current else "BELUM SEND BPK",
                "tanggal_send_bpk": current.get("tanggal_send_bpk") if current else None,
                "bpk_reference": current.get("bpk_reference") if current else None,
                "bpk_history": history,
            })
        return rows

    def query(self, source: str = SOURCE_AWAL, filters: Optional[Mapping[str, Any]] = None,
              **filter_values):
        return self.list(source, filters, **filter_values)

    def aggregate(self, source: str = SOURCE_AWAL,
                  filters: Optional[Mapping[str, Any]] = None,
                  group_by: Sequence[str] = ("periode",)) -> List[Dict[str, Any]]:
        """Return numeric BNBA totals grouped by period/batch/other fields."""
        source = _canonical_source(source)
        rows = self.list(source, filters)
        groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for row in rows:
            key = tuple(row.get(field) for field in group_by)
            item = groups.setdefault(key, {field: value for field, value in zip(group_by, key)})
            item["jumlah_baris"] = item.get("jumlah_baris", 0) + 1
            item["jumlah_sdm"] = item.get("jumlah_sdm", 0) + (1 if row.get("nip") else 0)
            numeric_fields = (
                ("total_awal_tukin", "total_potongan_absen", "total_potongan_tukin")
                if source == SOURCE_FINAL
                else ("total_tukin", "total_potongan_absen", "total_potongan_tukin")
            )
            for field in numeric_fields:
                value = row.get(field)
                if value is None:
                    value = row.get("calculated_" + field)
                item[field] = item.get(field, 0) + float(value or 0)
        return list(groups.values())

    def detail(self, row_id: str, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if source and _canonical_source(source) == SOURCE_FINAL:
            return next((row for row in self.final({"record_ids": row_id})["rows"]
                         if row.get("record_id") == row_id), None)
        sources = [_canonical_source(source)] if source else list(SOURCES)
        for current in sources:
            rows = self.repository.rows(current, {"limit": 5000})
            for row in rows:
                if row.get("row_id") == row_id:
                    history = self.repository.bpk_history([self.comparison_key(row)])
                    current = history[-1] if history else None
                    row.update({
                        "is_send_bpk": bool(history),
                        "bpk_batch": current.get("bpk_batch") if current else None,
                        "bpk_batch_label": current.get("bpk_batch_label") if current else "BELUM SEND BPK",
                        "tanggal_send_bpk": current.get("tanggal_send_bpk") if current else None,
                        "bpk_reference": current.get("bpk_reference") if current else None,
                        "bpk_history": history,
                    })
                    return row
        return None

    def history(self, source: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        return {
            "imports": self.repository.imports(source, limit),
            "comparisons": self.repository.compare_runs(limit),
        }

    get_history = history

    def delete_archive_row(self, row_id: str, source: str) -> Dict[str, Any]:
        """Delete one explicitly selected archive row and its direct BPK reference."""
        self.repository.ensure_schema()
        normalized_id = str(row_id or "").strip()
        normalized_source = _canonical_source(source)
        if normalized_source == SOURCE_FINAL:
            raise ValueError("DATA_FINAL adalah proyeksi turunan dan tidak dapat dihapus langsung")
        if not normalized_id:
            raise ValueError("ID baris arsip wajib diisi")

        table = self.repository.table_for(normalized_source)
        conn = self.repository.connect()
        try:
            row = conn.execute(
                f"SELECT import_id, nip, nama FROM {table} WHERE row_id=?", [normalized_id]
            ).fetchone()
            if not row:
                raise LookupError("Archive row tidak ditemukan")
            import_id, nip, nama = row
            result = delete_where_without_secondary_indexes(conn, [
                ("pengembalian_archive_bpk_history", "row_id=?", [normalized_id]),
                (table, "row_id=?", [normalized_id]),
                ("pengembalian_archive_import",
                 f"import_id=? AND NOT EXISTS (SELECT 1 FROM {table} WHERE import_id=?)",
                 [import_id, import_id]),
            ])
            return {
                **result,
                "row_id": normalized_id,
                "source": normalized_source,
                "import_id": import_id,
                "nip": nip,
                "nama": nama,
            }
        finally:
            self.repository.close(conn)

    def _legacy_materialized_dashboard(self, filters: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Database aggregation for large Final datasets; avoids decoding every row JSON."""
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            if not conn.execute("SELECT COUNT(*) FROM pengembalian_final").fetchone()[0]:
                return None
            where, params = [], []
            mapping = {"periode_id": "periode_id", "nip": "nip", "nama": "nama",
                       "tahun_sp2d": "tahun_sp2d", "periode": "periode",
                       "provinsi": "provinsi", "kabupaten_kota": "kabupaten_kota",
                       "unit_kerja": "unit_kerja", "status_compare": "status_compare",
                       "arah_perubahan": "arah_perubahan",
                       "flag_ada_perubahan": "flag_ada_perubahan",
                       "payment_status": "status_lunas"}
            for key, column in mapping.items():
                value = filters.get(key)
                if value not in (None, ""):
                    values = _filter_values(value)
                    where.append(f"{column} IN ({','.join('?' for _ in values)})")
                    params.extend(values)
            if filters.get("search"):
                where.append("(nip ILIKE ? OR nama ILIKE ? OR periode ILIKE ?)")
                term = f"%{filters['search']}%"
                params.extend([term, term, term])
            clause = " WHERE " + " AND ".join(where) if where else ""
            number = lambda field: (
                f"COALESCE(TRY_CAST(json_extract_string(row_json, '$.{field}') AS DOUBLE),0)"
            )
            sql = f"""SELECT COUNT(*), COUNT(DISTINCT nip),
                COUNT(DISTINCT CASE WHEN status_compare='BERUBAH' THEN nip END),
                COUNT(DISTINCT CASE WHEN status_compare='TIDAK BERUBAH' THEN nip END),
                SUM(COALESCE(nilai_awal,0)), SUM(COALESCE(nilai_final,0)),
                SUM(COALESCE(selisih_total,0)),
                SUM(CASE WHEN selisih_total < 0 THEN -selisih_total ELSE 0 END),
                SUM(CASE WHEN selisih_total > 0 THEN selisih_total ELSE 0 END),
                SUM(COALESCE(total_tukin_awal,0)), SUM(COALESCE(final_tukin,0)),
                SUM(COALESCE(final_uang_makan,0)), SUM(COALESCE(final_uang_makan,0)),
                SUM(COALESCE(final_total,0)),
                SUM(COALESCE(total_debit_berhasil,0)), SUM(COALESCE(total_debit_gagal,0)),
                SUM(COALESCE(sisa_piutang,0)),
                COUNT(DISTINCT CASE WHEN status_lunas='LUNAS' THEN nip END),
                COUNT(DISTINCT CASE WHEN status_lunas='SEBAGIAN' THEN nip END),
                COUNT(DISTINCT CASE WHEN status_lunas='BELUM ADA PENGEMBALIAN' THEN nip END)
                FROM pengembalian_final{clause}"""
            row = conn.execute(sql, params).fetchone()
            total = int(row[0] or 0)
            statuses = dict(conn.execute(
                "SELECT status_compare,COUNT(*) FROM pengembalian_final" + clause +
                " GROUP BY status_compare", params).fetchall())
            return {
                "data_awal": total, "data_penyesuaian": total, "total": total,
                "total_sdm": int(row[1] or 0), "sdm_berubah": int(row[2] or 0),
                "sdm_tidak_berubah": int(row[3] or 0), "data_baru": statuses.get("DATA BARU", 0),
                "data_hilang": statuses.get("DATA HILANG", 0),
                "total_potongan_awal": float(row[4] or 0),
                "total_potongan_penyesuaian": float(row[5] or 0),
                "total_selisih": float(row[6] or 0), "total_pengurangan": float(row[7] or 0),
                "total_kenaikan": float(row[8] or 0),
                "persentase_berubah": (float(row[2] or 0) / total * 100) if total else 0,
                "total_pengembalian_tukin_awal": float(row[9] or 0),
                "total_pengembalian_tukin_final": float(row[10] or 0),
                "selisih_pengembalian_tukin": float((row[10] or 0) - (row[9] or 0)),
                "total_pengembalian_uang_makan_awal": float(row[11] or 0),
                "total_pengembalian_uang_makan_final": float(row[12] or 0),
                "selisih_pengembalian_uang_makan": float((row[12] or 0) - (row[11] or 0)),
                "total_pengembalian_tukin_uang_makan": float(row[13] or 0),
                "total_oktober_awal": 0, "total_oktober_final": 0, "selisih_oktober": 0,
                "total_november_awal": 0, "total_november_final": 0, "selisih_november": 0,
                "total_desember_awal": 0, "total_desember_final": 0, "selisih_desember": 0,
                "total_naik": statuses.get("NAIK", 0), "total_turun": statuses.get("TURUN", 0),
                "status_pengembalian": statuses, "batch_bpk": {},
                "duplicate_awal": 0, "duplicate_penyesuaian": 0,
                "progress": {"total_berhasil": float(row[14] or 0), "total_gagal": float(row[15] or 0),
                             "total_sisa": float(row[16] or 0), "sdm_lunas": int(row[17] or 0),
                             "sdm_sebagian": int(row[18] or 0), "sdm_belum": int(row[19] or 0)}
            }
        finally:
            self.repository.close(conn)

    def _materialized_dashboard(self, filters: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """One database calculation layer for KPI, SP2D, batch and filters."""
        self.repository.ensure_schema()
        conn = self.repository.connect()
        try:
            if not conn.execute("SELECT COUNT(*) FROM pengembalian_final").fetchone()[0]:
                return None
            where, params = [], []
            effective_change = "CASE WHEN flag_ada_perubahan='BERUBAH' OR COALESCE(nilai_final,0)<>COALESCE(nilai_awal,0) THEN 'BERUBAH' ELSE 'TIDAK BERUBAH' END"
            mapping = {
                "periode_id": "periode_id", "nip": "nip", "nama": "nama",
                "tahun_sp2d": "tahun_sp2d", "periode": "periode", "batch": "batch",
                "provinsi": "provinsi", "kabupaten_kota": "kabupaten_kota",
                "unit_kerja": "unit_kerja", "status_compare": effective_change,
                "arah_perubahan": "arah_perubahan", "flag_ada_perubahan": effective_change,
                "status_perubahan": effective_change, "payment_status": "status_lunas",
            }
            for key, column in mapping.items():
                value = filters.get(key)
                if value in (None, ""):
                    continue
                values = [str(v).replace("_", " ") if key in {"status_perubahan", "flag_ada_perubahan"}
                          else v for v in _filter_values(value)]
                where.append(f"({column}) IN ({','.join('?' for _ in values)})")
                params.extend(values)
            if filters.get("search"):
                where.append("(nip ILIKE ? OR nama ILIKE ? OR periode ILIKE ? OR batch ILIKE ?)")
                term = f"%{filters['search']}%"
                params.extend([term, term, term, term])
            clause = " WHERE " + " AND ".join(where) if where else ""
            cte = f"""WITH filtered AS (
                    SELECT * FROM pengembalian_final{clause}
                ), grain AS (
                    SELECT COALESCE(nip,record_id) AS nip, tahun_sp2d,
                           SUM(COALESCE(nilai_awal,0)) AS nilai_awal,
                           SUM(COALESCE(nilai_final,0)) AS nilai_final,
                           MAX(CASE WHEN flag_ada_perubahan='BERUBAH' OR COALESCE(nilai_final,0)<>COALESCE(nilai_awal,0) THEN 1 ELSE 0 END) AS berubah
                    FROM filtered GROUP BY COALESCE(nip,record_id),tahun_sp2d
                )"""
            aggregate_sql = cte + """ SELECT COUNT(*),
                    SUM(berubah), SUM(CASE WHEN berubah=0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN nilai_final-nilai_awal>0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN nilai_final-nilai_awal<0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN nilai_final-nilai_awal=0 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN berubah=1 AND nilai_final-nilai_awal=0 THEN 1 ELSE 0 END),
                    SUM(nilai_awal),SUM(nilai_final),SUM(nilai_final-nilai_awal),
                    SUM(CASE WHEN nilai_final>nilai_awal THEN nilai_final-nilai_awal ELSE 0 END),
                    SUM(CASE WHEN nilai_final<nilai_awal THEN nilai_awal-nilai_final ELSE 0 END)
                    FROM grain"""
            row = conn.execute(aggregate_sql, params).fetchone()

            def grouped(group_columns: str, select_columns: str):
                sql = f"""WITH filtered AS (SELECT * FROM pengembalian_final{clause}),
                    grain AS (
                      SELECT {group_columns},COALESCE(nip,record_id) AS nip,
                        SUM(COALESCE(nilai_awal,0)) AS awal,SUM(COALESCE(nilai_final,0)) AS final,
                        MAX(CASE WHEN flag_ada_perubahan='BERUBAH' OR COALESCE(nilai_final,0)<>COALESCE(nilai_awal,0) THEN 1 ELSE 0 END) AS berubah
                      FROM filtered GROUP BY {group_columns},COALESCE(nip,record_id)
                    ) SELECT {select_columns},COUNT(*) AS total_sdm,SUM(berubah) AS berubah,
                      SUM(CASE WHEN berubah=0 THEN 1 ELSE 0 END) AS tidak_berubah,
                      SUM(CASE WHEN final-awal>0 THEN 1 ELSE 0 END) AS naik,
                      SUM(CASE WHEN final-awal<0 THEN 1 ELSE 0 END) AS turun,
                      SUM(CASE WHEN final-awal=0 THEN 1 ELSE 0 END) AS tetap,
                      SUM(CASE WHEN berubah=1 AND final-awal=0 THEN 1 ELSE 0 END) AS tetap_berubah,
                      SUM(awal) AS nilai_awal,SUM(final) AS nilai_final,SUM(final-awal) AS selisih,
                      SUM(CASE WHEN final>awal THEN final-awal ELSE 0 END) AS kenaikan,
                      SUM(CASE WHEN final<awal THEN awal-final ELSE 0 END) AS penurunan
                    FROM grain GROUP BY {select_columns} ORDER BY {select_columns}"""
                columns = [part.strip() for part in select_columns.split(",")] + [
                    "total_sdm", "berubah", "tidak_berubah", "naik", "turun", "tetap", "tetap_berubah",
                    "nilai_awal", "nilai_final", "selisih", "kenaikan", "penurunan",
                ]
                results = [dict(zip(columns, values)) for values in conn.execute(sql, params).fetchall()]
                for result in results:
                    result["invariants"] = {
                        "status_ok": result["total_sdm"] == result["berubah"] + result["tidak_berubah"],
                        "direction_ok": result["berubah"] == result["naik"] + result["turun"] + result["tetap_berubah"],
                        "nominal_ok": round(float(result["nilai_final"] or 0) - float(result["nilai_awal"] or 0)) == round(float(result["selisih"] or 0)),
                    }
                return results

            sp2d = grouped("tahun_sp2d", "tahun_sp2d")
            by_batch = grouped("tahun_sp2d,batch", "tahun_sp2d,batch")
            status_rows = conn.execute(
                f"SELECT {effective_change} AS effective_status,COUNT(*) FROM pengembalian_final" + clause +
                " GROUP BY effective_status", params).fetchall()
            batch_counts = {
                str(batch): int(count) for batch, count in conn.execute(
                    "SELECT batch,COUNT(DISTINCT COALESCE(nip,record_id)||'|'||"
                    "COALESCE(CAST(tahun_sp2d AS VARCHAR),'')) FROM pengembalian_final" + clause +
                    " AND batch IS NOT NULL AND TRIM(batch)<>'' GROUP BY batch" if clause else
                    "SELECT batch,COUNT(DISTINCT COALESCE(nip,record_id)||'|'||"
                    "COALESCE(CAST(tahun_sp2d AS VARCHAR),'')) FROM pengembalian_final "
                    "WHERE batch IS NOT NULL AND TRIM(batch)<>'' GROUP BY batch",
                    params,
                ).fetchall()
            }
            option_years = [value[0] for value in conn.execute(
                "SELECT DISTINCT tahun_sp2d FROM pengembalian_final WHERE tahun_sp2d IS NOT NULL ORDER BY 1"
            ).fetchall()]
            option_batches = [value[0] for value in conn.execute(
                "SELECT DISTINCT batch FROM pengembalian_final WHERE batch IS NOT NULL "
                "AND TRIM(batch)<>'' ORDER BY 1"
            ).fetchall()]
            progress = conn.execute("""SELECT
                SUM(COALESCE(total_debit_berhasil,0)),SUM(COALESCE(total_debit_gagal,0)),
                SUM(COALESCE(sisa_piutang,0)),
                COUNT(DISTINCT CASE WHEN status_lunas='LUNAS' THEN nip END),
                COUNT(DISTINCT CASE WHEN status_lunas='SEBAGIAN' THEN nip END),
                COUNT(DISTINCT CASE WHEN status_lunas='BELUM ADA PENGEMBALIAN' THEN nip END)
                FROM pengembalian_final""" + clause, params).fetchone()
            total_sdm = int(row[0] or 0)
            changed = int(row[1] or 0)
            unchanged = int(row[2] or 0)
            return {
                "data_awal": total_sdm, "data_penyesuaian": total_sdm, "total": total_sdm,
                "total_sdm": total_sdm, "sdm_berubah": changed,
                "sdm_tidak_berubah": unchanged, "total_naik": int(row[3] or 0),
                "total_turun": int(row[4] or 0), "total_tetap": int(row[5] or 0),
                "total_tetap_berubah": int(row[6] or 0),
                "total_potongan_awal": float(row[7] or 0),
                "total_potongan_penyesuaian": float(row[8] or 0),
                "total_selisih": float(row[9] or 0), "total_kenaikan": float(row[10] or 0),
                "total_pengurangan": float(row[11] or 0),
                "persentase_berubah": changed / total_sdm * 100 if total_sdm else 0,
                "data_baru": dict(status_rows).get("DATA BARU", 0),
                "data_hilang": dict(status_rows).get("DATA HILANG", 0),
                "status_pengembalian": dict(status_rows), "batch_bpk": batch_counts,
                "sp2d_summary": sp2d, "batch_summary": by_batch,
                "filter_options": {"tahun_sp2d": option_years, "batch": option_batches},
                "invariants": {
                    "status_ok": total_sdm == changed + unchanged,
                    "direction_ok": changed == int(row[3] or 0) + int(row[4] or 0) +
                                    int(row[6] or 0),
                    "nominal_ok": round(float(row[8] or 0) - float(row[7] or 0)) == round(float(row[9] or 0)),
                },
                "duplicate_awal": 0, "duplicate_penyesuaian": 0,
                "progress": {"total_berhasil": float(progress[0] or 0),
                             "total_gagal": float(progress[1] or 0), "total_sisa": float(progress[2] or 0),
                             "sdm_lunas": int(progress[3] or 0), "sdm_sebagian": int(progress[4] or 0),
                             "sdm_belum": int(progress[5] or 0)},
            }
        finally:
            self.repository.close(conn)

    def delete_period(self, period_id: str) -> Dict[str, Any]:
        """Delete only period configuration while preserving historical datasets."""
        self.repository.ensure_schema()
        normalized_id = str(period_id or "").strip()
        if not normalized_id:
            raise ValueError("ID periode wajib diisi")
        conn = self.repository.connect()
        try:
            row = conn.execute(
                "SELECT nama_periode FROM pengembalian_period WHERE periode_id=?",
                [normalized_id],
            ).fetchone()
            if not row:
                raise LookupError("Periode tidak ditemukan")
            conn.execute("BEGIN")
            conn.execute("DELETE FROM pengembalian_period WHERE periode_id=?", [normalized_id])
            self._audit_period(conn, normalized_id, "DELETE", None, None,
                               {"nama_periode": row[0]}, "system")
            conn.execute("COMMIT")
            return {
                "status": "ok", "periode_id": normalized_id,
                "nama_periode": row[0], "deleted_rows": 1,
            }
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.repository.close(conn)

    def reset_period(self, period_id: str, created_by: str = "system") -> Dict[str, Any]:
        """Remove only one logical Master workspace while preserving all others."""
        period = self.assert_period_writable(period_id)
        normalized_id = period["periode_id"]
        conn = self.repository.connect()
        try:
            operations = [
                ("pengembalian_dasar_kalkulasi_absensi", "periode_id=?", [normalized_id]),
                ("pengembalian_dasar_rekap_absensi", "periode_id=?", [normalized_id]),
                ("pengembalian_progress_transaction", "periode_id=?", [normalized_id]),
                ("pengembalian_progress_staging", "periode_id=?", [normalized_id]),
                ("pengembalian_progress_import_batch", "periode_id=?", [normalized_id]),
                ("pengembalian_master_obligation", "periode_id=?", [normalized_id]),
                ("pengembalian_obligation", "periode_id=?", [normalized_id]),
                ("pengembalian_payment_transaction", "periode_id=?", [normalized_id]),
                ("pengembalian_final", "periode_id=?", [normalized_id]),
                ("pengembalian_archive_dataset_row", "dataset_id IN (SELECT dataset_id FROM pengembalian_archive_dataset WHERE periode_id=?)", [normalized_id]),
                ("pengembalian_archive_dataset", "periode_id=?", [normalized_id]),
                ("pengembalian_archive_bpk_history", "source_version IN (SELECT import_id FROM pengembalian_archive_import WHERE periode_id=?)", [normalized_id]),
                ("pengembalian_archive_data_awal", "periode_id=?", [normalized_id]),
                ("pengembalian_archive_data_penyesuaian", "periode_id=?", [normalized_id]),
                ("pengembalian_archive_import", "periode_id=?", [normalized_id]),
            ]
            result = delete_where_without_secondary_indexes(conn, operations)
            conn.execute("BEGIN")
            conn.execute("UPDATE pengembalian_period SET status='DRAFT',is_active=FALSE,updated_at=now() WHERE periode_id=?", [normalized_id])
            self._audit_period(conn, normalized_id, "RESET", period["status"], "DRAFT",
                               result, created_by)
            conn.execute("COMMIT")
            return {**result, "periode_id": normalized_id, "period_status": "DRAFT"}
        except Exception:
            try: conn.execute("ROLLBACK")
            except Exception: pass
            raise
        finally:
            self.repository.close(conn)

    def dashboard(self, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        filters = dict(filters or {})
        selected_source = filters.pop("source", None)
        if selected_source and _canonical_source(selected_source) == SOURCE_FINAL:
            materialized = self._materialized_dashboard(filters)
            if materialized is not None:
                return materialized
            final_result = self.final(filters)
            rows = final_result["rows"]
            changed = [row for row in rows if row.get("status_compare") == "BERUBAH"]
            unchanged = [row for row in rows if row.get("status_compare") == "TIDAK BERUBAH"]
            total_awal = sum(float(row.get("nilai_awal") or 0) for row in rows)
            total_final = sum(float(row.get("nilai_final") or 0) for row in rows)
            def total(field):
                return sum(float(row.get(field) or 0) for row in rows)
            total_tukin_awal = total("total_awal_tukin")
            total_tukin_final = total("final_total_pengembalian_tukin")
            total_uang_makan_awal = sum(
                total(field) for field in (
                    "pengembalian_uang_makan_oktober",
                    "pengembalian_uang_makan_november",
                    "pengembalian_uang_makan_desember",
                )
            )
            total_uang_makan_final = total("final_total_pengembalian_uang_makan")
            progress = self.repayment_progress(filters).get("summary", {})
            batches = Counter(str(row.get("bpk_batch")) for row in rows
                              if row.get("bpk_batch") is not None)
            return {
                "data_awal": len(rows), "data_penyesuaian": len(rows),
                "total": len(rows), "total_sdm": len({
                    row.get("identity", {}).get("nip") for row in rows
                    if row.get("identity", {}).get("nip")
                }),
                "sdm_berubah": len({row.get("identity", {}).get("nip") for row in changed
                                   if row.get("identity", {}).get("nip")}),
                "sdm_tidak_berubah": len({row.get("identity", {}).get("nip") for row in unchanged
                                         if row.get("identity", {}).get("nip")}),
                "data_baru": sum(1 for row in rows if row.get("status_compare") == "DATA_BARU"),
                "data_hilang": sum(1 for row in rows if row.get("status_compare") == "DATA_HILANG"),
                "total_potongan_awal": total_awal,
                "total_potongan_penyesuaian": total_final,
                "total_selisih": total_final - total_awal,
                "total_pengembalian_tukin_awal": total_tukin_awal,
                "total_pengembalian_tukin_final": total_tukin_final,
                "selisih_pengembalian_tukin": total_tukin_final - total_tukin_awal,
                "total_pengembalian_uang_makan_awal": total_uang_makan_awal,
                "total_pengembalian_uang_makan_final": total_uang_makan_final,
                "selisih_pengembalian_uang_makan": total_uang_makan_final - total_uang_makan_awal,
                "total_pengembalian_tukin_uang_makan": total("final_total_pengembalian_tukin_uang_makan"),
                "persentase_berubah": (len(changed) / len(rows) * 100) if rows else 0,
                "total_pengurangan": sum(max(float(row.get("pengurangan_total") or 0), 0) for row in rows),
                "total_kenaikan": sum(max(float(row.get("selisih_total_tukin") or 0), 0) for row in rows),
                "total_oktober_awal": total("tukin_pengembalian_oktober"),
                "total_oktober_final": total("final_pengembalian_tukin_oktober"),
                "selisih_oktober": total("final_pengembalian_tukin_oktober") - total("tukin_pengembalian_oktober"),
                "total_november_awal": total("tukin_pengembalian_november"),
                "total_november_final": total("final_pengembalian_tukin_november"),
                "selisih_november": total("final_pengembalian_tukin_november") - total("tukin_pengembalian_november"),
                "total_desember_awal": total("tukin_pengembalian_desember"),
                "total_desember_final": total("final_pengembalian_tukin_desember"),
                "selisih_desember": total("final_pengembalian_tukin_desember") - total("tukin_pengembalian_desember"),
                "progress": progress,
                "total_naik": sum(1 for row in rows if row.get("arah_perubahan") == "NAIK"),
                "total_turun": sum(1 for row in rows if row.get("arah_perubahan") == "TURUN"),
                "status_pengembalian": Counter(row.get("status_compare") for row in rows),
                "batch_bpk": dict(batches),
                "duplicate_awal": 0, "duplicate_penyesuaian": 0,
            }
        awal = self.repository.rows(SOURCE_AWAL, {**filters, "limit": 5000})
        penyesuaian = self.repository.rows(SOURCE_PENYESUAIAN, {**filters, "limit": 5000})
        if selected_source:
            if _canonical_source(selected_source) == SOURCE_AWAL:
                penyesuaian = []
            else:
                awal = []
        awal_keys = Counter(self.comparison_key(row) for row in awal)
        penyesuaian_keys = Counter(self.comparison_key(row) for row in penyesuaian)
        comparison = self.compare(filters, persist=False)
        all_rows = awal + penyesuaian
        unique_nip = {row.get("nip") for row in all_rows if row.get("nip")}

        def nominal(rows, field):
            calculated = {
                "total_potongan_absen": "calculated_total_potongan_absen",
                "total_potongan_tukin": "calculated_total_potongan_tukin",
            }.get(field)
            return sum(float(row.get(field) if row.get(field) is not None
                             else (row.get(calculated) if calculated else 0) or 0)
                       for row in rows)

        awal_values = [row for detail in comparison["details"] for row in detail["data_awal"]]
        penyesuaian_values = [
            row for detail in comparison["details"] for row in detail["data_penyesuaian"]
        ]
        total_awal = nominal(awal_values, "total_potongan_tukin")
        total_penyesuaian = nominal(penyesuaian_values, "total_potongan_tukin")
        return {
            "data_awal": len(awal), "data_penyesuaian": len(penyesuaian),
            "total": len(awal) + len(penyesuaian),
            "total_sdm": len(unique_nip),
            "sdm_berubah": len({
                row.get("nip") for row in comparison["details"]
                if row["result_type"] == "BERUBAH"
                for row in (row["data_awal"] + row["data_penyesuaian"])
                if row.get("nip")
            }),
            "sdm_tidak_berubah": len({
                row.get("nip") for row in comparison["details"]
                if row["result_type"] == "TIDAK_BERUBAH"
                for row in (row["data_awal"] + row["data_penyesuaian"])
                if row.get("nip")
            }),
            "data_baru": comparison["new_count"],
            "data_hilang": comparison["missing_count"],
            "total_potongan_awal": total_awal,
            "total_potongan_penyesuaian": total_penyesuaian,
            "total_selisih": total_penyesuaian - total_awal,
            "total_naik": sum(1 for detail in comparison["details"]
                              if any((change.get("delta") or 0) > 0
                                     for change in detail.get("changes", {}).values())),
            "total_turun": sum(1 for detail in comparison["details"]
                               if any((change.get("delta") or 0) < 0
                                      for change in detail.get("changes", {}).values())),
            "status_pengembalian": Counter(detail["compare_status"]
                                            for detail in comparison["details"]),
            "batch_bpk": {},
            "duplicate_awal": sum(1 for count in awal_keys.values() if count > 1),
            "duplicate_penyesuaian": sum(1 for count in penyesuaian_keys.values() if count > 1),
        }

    get_dashboard = dashboard

    def bpk_reconciliation(self, filters: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        filters = dict(filters or {})
        requested_batch = filters.pop("bpk_batch", None)
        final_result = self.final(filters)

        def batch_label(row: Mapping[str, Any]) -> Optional[str]:
            # The imported Batch column is the business source of truth.  BPK
            # history remains a fallback for records sent by the older UI.
            source_batch = row.get("batch") or row.get("batch_bpk")
            if source_batch not in (None, ""):
                return _normalize_bnba_batch(source_batch)
            history_batch = row.get("bpk_batch")
            return f"BATCH {history_batch}" if history_batch is not None else None

        all_rows = []
        for row in final_result["rows"]:
            label = batch_label(row)
            if not label and not row.get("pernah_send_bpk"):
                continue
            item = dict(row)
            item["reconciliation_batch"] = label or "TANPA BATCH"
            all_rows.append(item)

        available_batches = sorted(
            {row["reconciliation_batch"] for row in all_rows},
            key=lambda value: (int(re.search(r"\d+", value).group())
                               if re.search(r"\d+", value) else 10**9, value),
        )
        requested_label = (_normalize_bnba_batch(requested_batch)
                           if requested_batch not in (None, "") else None)
        rows = [row for row in all_rows
                if requested_label is None or row["reconciliation_batch"] == requested_label]

        def status_summary(items: Sequence[Mapping[str, Any]], status: str) -> Dict[str, Any]:
            selected = [row for row in items if row.get("status_compare") == status]
            nominal_awal = sum(float(row.get("nilai_awal") or 0) for row in selected)
            nominal_final = sum(float(row.get("nilai_final") or 0) for row in selected
                                if status != "DATA HILANG")
            return {
                "jumlah_sdm": len({row.get("identity", {}).get("nip") for row in selected
                                    if row.get("identity", {}).get("nip")}),
                "jumlah_data": len(selected),
                "nominal_awal": nominal_awal,
                "nominal_final": nominal_final,
                "selisih_nominal": nominal_final - nominal_awal,
            }

        def summarize(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
            awal = sum(float(row.get("nilai_awal") or 0) for row in items)
            final = sum(float(row.get("nilai_final") or 0) for row in items
                        if row.get("status_compare") != "DATA HILANG")
            by_status = {
                status: status_summary(items, status)
                for status in ("BERUBAH", "TIDAK BERUBAH", "DATA BARU", "DATA HILANG", "NEED REVIEW")
            }
            return {
                "jumlah_sdm_awal_send_bpk": len({row.get("identity", {}).get("nip") for row in items
                                                  if row.get("identity", {}).get("nip")}),
                "jumlah_sdm_final": len({row.get("identity", {}).get("nip") for row in items
                                          if row.get("identity", {}).get("nip") and
                                          row.get("status_compare") != "DATA HILANG"}),
                "total_pengembalian_awal": awal,
                "total_pengembalian_final": final,
                "selisih_nominal": final - awal,
                "pengurangan_kewajiban": awal - final,
                "jumlah_sdm_berubah": by_status["BERUBAH"]["jumlah_sdm"],
                "jumlah_tidak_berubah": by_status["TIDAK BERUBAH"]["jumlah_sdm"],
                "data_baru": by_status["DATA BARU"]["jumlah_data"],
                "data_hilang": by_status["DATA HILANG"]["jumlah_data"],
                "need_review": by_status["NEED REVIEW"]["jumlah_data"],
                "status_summary": by_status,
            }

        counts = summarize(rows)
        batch_summaries = []
        for label in available_batches:
            summary = summarize([row for row in all_rows
                                 if row["reconciliation_batch"] == label])
            batch_summaries.append({"batch": label, **summary})
        response_filters = dict(filters)
        response_filters["bpk_batch"] = requested_batch
        return {"status": "ok", "filters": response_filters, "selected_batch": requested_label,
                "available_batches": available_batches, "batch_summaries": batch_summaries,
                "kpi": counts, "rows": rows}

    def compare_daily(self, nip: Optional[str] = None,
                      periode: Optional[str] = None) -> Dict[str, Any]:
        self.repository.ensure_schema()
        import importlib.util
        migration_path = Path(__file__).resolve().parent / "migrations" / (
            "024_create_pengembalian_dasar_harian_archive.py"
        )
        spec = importlib.util.spec_from_file_location("daily_archive_migration", migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.main(self.repository.db_path)
        conn = self.repository.connect()
        try:
            clauses, params = [], []
            for field, value in (("nip", nip), ("periode", periode)):
                if value:
                    clauses.append(f"{field} = ?")
                    params.append(value)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            def load(table):
                sql = f"SELECT * FROM {table}{where} ORDER BY tanggal, record_id"
                return [{k: _clean(v) for k, v in row.items()}
                        for row in conn.execute(sql, params).fetchdf().to_dict("records")]
            awal, adjusted = load("pengembalian_dasar_harian_awal"), load(
                "pengembalian_dasar_harian_penyesuaian")
            def key(row):
                tanggal = str(row.get("tanggal") or "")[:10]
                return "|".join((str(row.get("nip") or ""), tanggal,
                                 str(row.get("periode") or "")))
            a_groups, b_groups = {}, {}
            for row in awal: a_groups.setdefault(key(row), []).append(row)
            for row in adjusted: b_groups.setdefault(key(row), []).append(row)
            fields = ("jam_masuk", "jam_pulang", "status_kehadiran", "nilai_potongan_harian",
                      "nilai_tukin")
            details = []
            for item in sorted(set(a_groups) | set(b_groups)):
                a, b = a_groups.get(item, []), b_groups.get(item, [])
                left, right = (a[0] if a else {}), (b[0] if b else {})
                changed = [field for field in fields if left.get(field) != right.get(field)]
                status = "BERUBAH" if a and b and changed else (
                    "TIDAK BERUBAH" if a and b else "BARU" if b else "HILANG")
                details.append({
                    "comparison_key": item, "nip": right.get("nip") or left.get("nip"),
                    "nama": right.get("nama") or left.get("nama"),
                    "tanggal": str(right.get("tanggal") or left.get("tanggal") or "")[:10],
                    "jam_masuk_awal": left.get("jam_masuk"),
                    "jam_masuk_penyesuaian": right.get("jam_masuk"),
                    "jam_pulang_awal": left.get("jam_pulang"),
                    "jam_pulang_penyesuaian": right.get("jam_pulang"),
                    "status_awal": left.get("status_kehadiran"),
                    "status_penyesuaian": right.get("status_kehadiran"),
                    "potongan_awal": left.get("persentase_potongan_harian"),
                    "potongan_penyesuaian": right.get("persentase_potongan_harian"),
                    "nominal_awal": left.get("nilai_potongan_harian"),
                    "nominal_penyesuaian": right.get("nilai_potongan_harian"),
                    "selisih": ((right.get("nilai_potongan_harian") or 0) -
                                (left.get("nilai_potongan_harian") or 0))
                               if a and b else None,
                    "changed_fields": changed, "status": status,
                    "data_awal": a, "data_penyesuaian": b,
                })
            aggregates = {}
            for row in details:
                adjusted_period = (row["data_penyesuaian"][0].get("periode")
                                   if row["data_penyesuaian"] else None)
                initial_period = (row["data_awal"][0].get("periode")
                                  if row["data_awal"] else None)
                aggregate_key = "|".join((str(row.get("nip") or ""),
                                           str(adjusted_period or initial_period or "")))
                item = aggregates.setdefault(aggregate_key, {
                    "nip": row.get("nip"), "periode": aggregate_key.rsplit("|", 1)[-1],
                    "nominal_awal": 0, "nominal_penyesuaian": 0,
                    "selisih": 0, "jumlah_harian": 0, "jumlah_berubah": 0,
                })
                item["nominal_awal"] += row.get("nominal_awal") or 0
                item["nominal_penyesuaian"] += row.get("nominal_penyesuaian") or 0
                item["selisih"] += row.get("selisih") or 0
                item["jumlah_harian"] += 1
                item["jumlah_berubah"] += row["status"] == "BERUBAH"
            return {"status": "ok", "rows": details, "count": len(details),
                    "aggregates": list(aggregates.values())}
        finally:
            self.repository.close(conn)

    def daily_detail(self, nip: str, periode: Optional[str] = None,
                     period_id: Optional[str] = None) -> Dict[str, Any]:
        if not period_id and str(periode or "").upper().startswith("RET-"):
            period_id, periode = str(periode), None
        daily = self.compare_daily(nip, periode)
        final_filters = {"nip": nip}
        source_filters = {"nip": nip}
        if period_id:
            final_filters["periode_id"] = period_id
            source_filters["periode_id"] = period_id
        elif periode:
            final_filters["periode"] = periode
            source_filters["periode"] = periode
        return {"status": "ok", "tabs": {
            "summary": self.final(final_filters),
            "history_pengembalian": self.history(),
            "data_awal": self.list(SOURCE_AWAL, source_filters),
            "data_penyesuaian": self.list(SOURCE_PENYESUAIAN, source_filters),
            "dasar_perhitungan_absensi": self.dasar_absensi(nip=nip, period_id=period_id),
            "data_dasar_rekap": self.rekap_absensi(nip, period_id),
            "perubahan_absensi": [row for row in daily["rows"] if row["status"] == "BERUBAH"],
            "data_dasar_harian": daily["rows"],
        }}

    def export_xlsx(self, source: Optional[str] = None, filters: Optional[Mapping[str, Any]] = None,
                    compare_result: Optional[Mapping[str, Any]] = None) -> bytes:
        summary_rows = None
        if compare_result is not None:
            rows = compare_result.get("details", [])
            frame = pd.json_normalize(rows) if rows else pd.DataFrame()
            name = "BNBA PENGEMBALIAN ALL SDM"
        elif source and _canonical_source(source) == "DATA_FINAL":
            rows = self.final(filters or {}).get("rows", [])
            frame = self._bnba_frame(rows)
            summary_rows = rows
            name = "BNBA PENGEMBALIAN ALL SDM"
        elif source:
            rows = self.repository.rows(source, filters)
            frame = self._source_frame(rows, include_computed=True)
            name = "BNBA " + _canonical_source(source)
        else:
            rows = self.repository.rows(SOURCE_AWAL, filters) + self.repository.rows(SOURCE_PENYESUAIAN, filters)
            frame = self._source_frame(rows, include_computed=True)
            name = "archive"
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            if frame.empty:
                frame = pd.DataFrame({"Keterangan": ["Tidak ada data sesuai filter"]})
            frame.to_excel(writer, index=False, sheet_name=name[:31])
            guide = pd.DataFrame({
                "Informasi": ["Export Master Pengembalian", "Sumber", "Filter"],
                "Nilai": [name, source or "COMPARE", _json(dict(filters or {}))]
            })
            guide.to_excel(writer, index=False, sheet_name="PETUNJUK")
            worksheet = writer.sheets[name[:31]]
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, len(frame), max(len(frame.columns) - 1, 0))
            worksheet.set_column(0, len(frame.columns) - 1, 20)
            text_format = writer.book.add_format({"num_format": "@"})
            for text_column in ("NIP", "Nomor Rekening", "NOMER REKENING"):
                if text_column in frame.columns:
                    index = frame.columns.get_loc(text_column)
                    worksheet.set_column(index, index, 24, text_format)
            if summary_rows is not None:
                self._write_summary_sheets(writer, summary_rows)
        return output.getvalue()

    @staticmethod
    def _write_summary_sheets(writer, rows: Sequence[Mapping[str, Any]]) -> None:
        def summary(group_field=None) -> pd.DataFrame:
            groups: Dict[Any, Dict[str, Any]] = {}
            for row in rows:
                identity = row.get("identity") or {}
                fields = tuple(group_field) if isinstance(group_field, (tuple, list)) else ((group_field,) if group_field else ())
                values = tuple(row.get(field, identity.get(field)) for field in fields)
                key = values if fields else "TOTAL"
                labels = ({field: value for field, value in zip(fields, values)}
                          if fields else {"Ringkasan": "TOTAL"})
                item = groups.setdefault(key, {**labels,
                    "Jumlah SDM": 0,
                    "Total Pengembalian Awal": 0.0,
                    "Total Pengembalian Final": 0.0,
                    "Total Selisih": 0.0,
                    "Berubah": 0,
                    "Tidak Berubah": 0,
                })
                item["Jumlah SDM"] += 1
                item["Total Pengembalian Awal"] += float(row.get("nilai_awal") or 0)
                item["Total Pengembalian Final"] += float(row.get("nilai_final") or 0)
                item["Total Selisih"] += float(row.get("selisih") or 0)
                if row.get("status_compare") == "BERUBAH":
                    item["Berubah"] += 1
                elif row.get("status_compare") == "TIDAK BERUBAH":
                    item["Tidak Berubah"] += 1
            return pd.DataFrame(list(groups.values()))

        for sheet_name, group_field in (
            ("REKAP", None),
            ("REKAP TAHUN SP2D", "tahun_sp2d"),
            ("REKAP TAHUN BATCH", ("tahun_sp2d", "batch")),
            ("REKAP PROVINSI", "provinsi"),
            ("REKAP BATCH", "batch"),
        ):
            frame = summary(group_field)
            frame.to_excel(writer, index=False, sheet_name=sheet_name)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, len(frame), max(len(frame.columns) - 1, 0))
            worksheet.set_column(0, len(frame.columns) - 1, 22)

    @staticmethod
    def _source_frame(rows: Sequence[Mapping[str, Any]],
                      include_computed: bool = False) -> pd.DataFrame:
        output = []
        computed = {
            "flag_ada_perubahan", "flag_perubahan_oktober", "selisih_oktober",
            "flag_perubahan_november", "selisih_november",
            "flag_perubahan_desember", "selisih_desember",
            "flag_perubahan_total", "selisih_total_tukin", "arah_perubahan",
            "batch_oktober_normalized", "batch_november_normalized",
            "batch_desember_normalized", "final_batch_normalized",
        }
        for row in rows:
            raw = dict(row.get("raw_data") or {})
            if not raw:
                raw = {key: value for key, value in row.items()
                       if key not in {"raw_data", "validation_flags", "tukin_validation"}}
            if include_computed:
                raw.update({key: row.get(key) for key in computed})
            output.append(raw)
        return pd.DataFrame(output)

    @staticmethod
    def _bnba_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
        """Flatten current-state rows into the official BNBA export shape."""
        output = []
        for row in rows:
            identity = row.get("identity") or {}
            initial = row.get("initial_values") or {}
            final = row.get("final_values") or {}
            output.append({
                "NIP": identity.get("nip"),
                "Nama": identity.get("nama"),
                "Tahun SP2D": row.get("tahun_sp2d") or identity.get("tahun_sp2d"),
                "Nomor SP2D": identity.get("nomor_sp2d"),
                "Tahun": identity.get("tahun"),
                "Bulan": identity.get("bulan"),
                "Periode": identity.get("periode"),
                "Periode ID": identity.get("periode_id") or row.get("periode_id"),
                "Komponen": identity.get("komponen"),
                "Provinsi": identity.get("provinsi"),
                "Kabupaten/Kota": identity.get("kabupaten_kota"),
                "KdanakSatker": identity.get("kdanaksatker"),
                "Unit/Satker": identity.get("unit_kerja") or row.get("unit_kerja"),
                "Tukin Pengembalian Oktober": row.get("tukin_pengembalian_oktober"),
                "Final Pengembalian Tukin Oktober": row.get("final_pengembalian_tukin_oktober"),
                "Flag Oktober": row.get("klasifikasi_oktober"),
                "Selisih Oktober": row.get("selisih_oktober"),
                "Pengurangan Oktober": row.get("pengurangan_oktober"),
                "Tukin Pengembalian November": row.get("tukin_pengembalian_november"),
                "Final Pengembalian Tukin November": row.get("final_pengembalian_tukin_november"),
                "Flag November": row.get("klasifikasi_november"),
                "Selisih November": row.get("selisih_november"),
                "Pengurangan November": row.get("pengurangan_november"),
                "Tukin Pengembalian Desember": row.get("tukin_pengembalian_desember"),
                "Final Pengembalian Tukin Desember": row.get("final_pengembalian_tukin_desember"),
                "Flag Desember": row.get("klasifikasi_desember"),
                "Selisih Desember": row.get("selisih_desember"),
                "Pengurangan Desember": row.get("pengurangan_desember"),
                "Total Awal Pengembalian Tukin": row.get("total_awal_tukin"),
                "Final Total Pengembalian Tukin": row.get("final_total_pengembalian_tukin"),
                "Flag Total": row.get("flag_perubahan_total"),
                "Selisih Total": row.get("selisih_total_tukin"),
                "Pengurangan Total": row.get("pengurangan_total"),
                "Ada Perubahan": row.get("ada_perubahan"),
                "Jumlah Bulan Berubah": row.get("jumlah_bulan_berubah"),
                "Total Debit Berhasil": row.get("total_debit_berhasil"),
                "Total Debit Gagal": row.get("total_debit_gagal"),
                "Sisa Piutang": row.get("sisa_piutang"),
                "Status Lunas": row.get("status_lunas"),
                "Total Pengembalian Awal": initial.get("total_potongan_tukin"),
                "Total Pengembalian Final": final.get("total_potongan_tukin"),
                "Selisih": row.get("selisih"),
                "Status Compare": row.get("status_compare"),
                "Changed Fields": ", ".join(row.get("changed_fields") or []),
                "Pernah Send BPK": "YA" if row.get("pernah_send_bpk") else "TIDAK",
                "Batch BPK": row.get("batch"),
                "Riwayat Batch Kirim BPK": row.get("bpk_batch"),
                "BPK Batch Label": row.get("bpk_batch_label") or "BELUM SEND BPK",
                "Tanggal Send BPK": row.get("tanggal_send_bpk"),
                "Reference BPK": row.get("bpk_reference"),
                "Initial Record ID": row.get("initial_record_id"),
                "Latest Adjustment Record ID": row.get("latest_adjustment_record_id"),
                "Source Version": row.get("source_version"),
                "Current Version": row.get("current_version"),
                "Comparison Key": row.get("comparison_key"),
                "Kode Anak Satker": identity.get("kdanaksatker"),
                "Tahun SP2D Sebelumnya": identity.get("tahun_sp2d_sebelumnya"),
                "Tahun SP2D Update": identity.get("tahun_sp2d_update") or row.get("tahun_sp2d"),
                "Status SP2D": identity.get("status_sp2d"),
                "Nama Bank": identity.get("nama_bank"),
                "Nomor Rekening": identity.get("nomor_rekening"),
                "Nama Direk": identity.get("nama_direk"),
            })
        return pd.DataFrame(output)

    download_xlsx = export_xlsx


# Backwards-friendly names for consumers that use Repository/Service terminology.
PengembalianArchiveRepository = ArchiveRepository
PengembalianArchiveService = ArchiveService


def normalize_row(row, source_row=None):
    return ArchiveService.normalize_row(row, source_row)


def comparison_key(row):
    return ArchiveService.comparison_key(row)


def preview_import(rows, source=SOURCE_AWAL, metadata=None, db_path=None):
    return ArchiveService(db_path).preview(rows, source, metadata)


def import_archive(rows, source=SOURCE_AWAL, metadata=None, created_by="system", db_path=None):
    return ArchiveService(db_path).import_rows(rows, source, metadata, created_by)


def compare_archive(filters=None, source_a=SOURCE_AWAL, source_b=SOURCE_PENYESUAIAN,
                    created_by="system", db_path=None):
    return ArchiveService(db_path).compare(filters, source_a, source_b, created_by)
