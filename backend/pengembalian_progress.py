"""Progress Pengembalian v2: obligations, immutable debit history, aggregates and Excel."""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
import base64
import binascii
from pathlib import Path
import re
import threading
import uuid

import duckdb
import pandas as pd
from openpyxl import load_workbook

try:
    from .duckdb_maintenance import clear_tables_without_secondary_indexes, is_invalidated_duckdb_error
except ImportError:  # pragma: no cover - direct module execution compatibility
    from duckdb_maintenance import clear_tables_without_secondary_indexes, is_invalidated_duckdb_error


ALLOWED_STATUS = {"BERHASIL", "GAGAL", "PENDING", "DIBATALKAN", "REVERSAL", "NEEDS_REVIEW"}
COMPONENTS = {"TUKIN", "UANG_MAKAN"}
BANK_ALIASES = {
    "BRI": ("BRI", "BANK BRI", "PT BANK RAKYAT INDONESIA", "BANK RAKYAT INDONESIA"),
    "BNI": ("BNI", "BANK BNI", "PT BANK NEGARA INDONESIA", "BANK NEGARA INDONESIA"),
    "MANDIRI": ("MANDIRI", "BANK MANDIRI", "PT BANK MANDIRI"),
    "BSI": ("BSI", "BANK BSI", "BANK SYARIAH INDONESIA", "PT BANK SYARIAH INDONESIA"),
}
_MIGRATED_DATABASES = set()
_MIGRATION_LOCK = threading.Lock()


def _key(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return None if not text or text.lower() in {"nan", "none", "null"} else text


def _nip(value):
    text = _clean(value)
    if text is None:
        return None
    return re.sub(r"\.0$", "", text).strip()


def _number(value):
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = re.sub(r"[^0-9,.-]", "", str(value).strip())
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def _date(value):
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.date()


def normalize_bank(value):
    original = _clean(value)
    if original is None:
        return None
    canonical = re.sub(r"[^A-Z0-9]+", " ", original.upper()).strip()
    for name, aliases in BANK_ALIASES.items():
        if canonical in aliases:
            return name
    return canonical


def _master_bank_sql(column):
    """Return SQL that normalizes payroll/master-bank labels like ``normalize_bank``."""
    source = f"upper(trim(coalesce({column}, '')))"
    cases = " ".join(
        f"WHEN {source} IN ({','.join(repr(alias) for alias in aliases)}) THEN '{name}'"
        for name, aliases in BANK_ALIASES.items()
    )
    return f"CASE {cases} ELSE {source} END"


def _master_bank_value(alias="f"):
    """Canonical payroll-bank field retained in the Final row JSON."""
    return f"coalesce(json_extract_string({alias}.row_json,'$.nama_bank'),'')"


def _final_metadata_match(obligation_alias="o", final_alias="f"):
    """Match canonical obligations to Final metadata, including legacy null periods."""
    return (f"{final_alias}.nip={obligation_alias}.nip "
            f"AND {final_alias}.tahun_sp2d={obligation_alias}.tahun_sp2d "
            f"AND coalesce({final_alias}.periode_id,'LEGACY')="
            f"coalesce({obligation_alias}.periode_id,'LEGACY')")


def _stage_number(value):
    """Parse an unlimited positive integer stage, including common Roman labels."""
    text = (_clean(value) or "").upper().replace("TAHAP", "").strip()
    if re.fullmatch(r"\d+", text):
        return int(text) if int(text) > 0 else None
    if not re.fullmatch(r"[IVXLCDM]+", text):
        return None
    values, total, previous = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}, 0, 0
    for character in reversed(text):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total if total > 0 else None


def _component(value):
    text = re.sub(r"[^A-Z]+", "_", (_clean(value) or "").upper()).strip("_")
    aliases = {"UM": "UANG_MAKAN", "UANGMAKAN": "UANG_MAKAN", "UANG_MAKAN": "UANG_MAKAN", "TUKIN": "TUKIN"}
    return aliases.get(text)


def _expand_master_progress_rows(rows):
    """Convert the wide BNBA progress workbook into debit-event rows.

    SEND BANK and FINAL columns are source evidence. Only bank results,
    failures, and residual pending amounts become progress transactions.
    """
    rows = list(rows or [])
    if not rows:
        return rows, None
    header_keys = {_key(name) for row in rows[:3] for name in row.keys()}
    signature = {"final_total_pengembalian_tukin", "hasil_debit_juli_sp2d_2025",
                 "total_progress_tukin_sp2d_tahuh_2025"}
    if len(signature.intersection(header_keys)) < 2:
        return rows, None

    stages = (
        {"name": "TAHAP_1", "period": "Tahap 1 - Juli 2026", "date": "02/07/2026",
         "sent": "send_bank_1_dari_total_tukin_dibagi_3_bulan_debitan_bagi_yang_500rb_bagi_500rb_langsung_dibulan_juli",
         "success": ((2025, "hasil_debit_juli_sp2d_2025"), (2026, "hasil_debit_sp2d_2026")),
         "failed": "gagal", "reason": "keterangan_gagal"},
        {"name": "TAHAP_2", "period": "Tahap 2 - 22 & 24 Juli 2026", "date": None,
         "sent": "send_yang_gagal_tahap_2",
         "success": ((2025, "hasil_debit_tahap_2_2025"), (2026, "hasil_debit_tahap_2_sp2d_2026")),
         "failed": "gagal_tahap_2", "reason": "keterangan_gagal_1"},
        {"name": "TAHAP_3", "period": "Tahap 3 - Agustus 2026", "date": "01/08/2026",
         "sent": "send_bank_tahap_3",
         "success": ((2025, "hasil_debit_agustus_tahap_3_sp2d_2025"), (2026, "hasil_debit_tahap_3_sp2d_2026")),
         "failed": None, "reason": None},
    )

    result = []
    source_data_rows = 0
    for source_index, source in enumerate(rows, start=2):
        keyed = {_key(k): (k, v) for k, v in source.items()}
        value = lambda name: keyed.get(name, (None, None))[1]
        nip = _nip(value("nip"))
        if not nip:
            continue  # source rows 2-3 contain notes/totals, not SDM data
        source_data_rows += 1
        year_update = _number(value("tahun_sp2d_update"))
        year_update = int(year_update) if year_update and 1900 <= year_update <= 2200 else None
        base = {"NIP": nip, "Nama SDM": value("nama_sk"), "Provinsi": value("provinsi"),
                "Nama Bank": value("nama_bank"), "Source Row Number": source_index,
                "Final Tukin Sumber": value("final_total_pengembalian_tukin")}
        ordered_keys = list(source.keys())
        for stage in stages:
            successful_total = 0.0
            for year, success_key in stage["success"]:
                amount = _number(value(success_key)) or 0.0
                if amount <= 0:
                    continue
                successful_total += amount
                original_key = keyed.get(success_key, (None, None))[0]
                ntpn = None
                if original_key in ordered_keys:
                    pos = ordered_keys.index(original_key)
                    if pos + 1 < len(ordered_keys) and _key(ordered_keys[pos + 1]).startswith("ntpn"):
                        ntpn = source.get(ordered_keys[pos + 1])
                result.append({**base, "Tahun SP2D": year, "Periode Debit": stage["period"],
                               "Tanggal Debit": stage["date"], "Status Debit": "BERHASIL",
                               "Debit Tukin": amount, "NTPN": ntpn,
                               "Source Stage": stage["name"], "Source Result Column": original_key})
            failed = (_number(value(stage["failed"])) or 0.0) if stage["failed"] else 0.0
            if failed > 0:
                result.append({**base, "Tahun SP2D": year_update, "Periode Debit": stage["period"],
                               "Tanggal Debit": stage["date"], "Status Debit": "GAGAL",
                               "Debit Tukin": failed, "Keterangan Gagal": value(stage["reason"]),
                               "Source Stage": stage["name"]})
            sent = _number(value(stage["sent"])) or 0.0
            pending = max(sent - successful_total - failed, 0.0)
            if pending > 0.5:
                result.append({**base, "Tahun SP2D": year_update, "Periode Debit": stage["period"],
                               "Tanggal Debit": stage["date"], "Status Debit": "PENDING",
                               "Debit Tukin": pending, "Source Stage": stage["name"],
                               "Source Sent": sent})
    return result, {"format": "MASTER_PROGRESS_WIDE", "source_rows": source_data_rows,
                    "transaction_rows": len(result)}


def _encode_cursor(nip, record_id):
    payload = json.dumps({"nip": nip, "record_id": record_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor):
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(value, dict) or not value.get("nip") or not value.get("record_id"):
            raise ValueError
        return str(value["nip"]), str(value["record_id"])
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("cursor tidak valid") from exc


class ProgressService:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        with _MIGRATION_LOCK:
            if self.db_path not in _MIGRATED_DATABASES:
                for filename,name in (("028_create_pengembalian_progress.py","progress_legacy_migration"),
                                      ("030_create_pengembalian_progress_v2.py","progress_v2_migration"),
                                      ("031_optimize_pengembalian_progress_import.py","progress_import_migration"),
                                      ("033_create_multi_period_master.py","multi_period_migration"),
                                      ("046_create_progress_stage_ledger.py","progress_stage_ledger_migration"),
                                      ("047_normalize_progress_obligation_snapshot.py","progress_snapshot_migration")):
                    migration = Path(__file__).resolve().parent / "migrations" / filename
                    spec = importlib.util.spec_from_file_location(name, migration)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.main(self.db_path)
                _MIGRATED_DATABASES.add(self.db_path)

    def connect(self):
        conn = duckdb.connect(self.db_path)
        try:
            conn.execute("SELECT 1").fetchone()
            return conn
        except Exception as exc:
            if not is_invalidated_duckdb_error(exc):
                conn.close()
                raise
            conn.close()
            return duckdb.connect(self.db_path)

    def clear_database(self):
        """Clear only progress-import and obligation tables for the progress module."""
        conn = self.connect()
        tables = [
            "pengembalian_progress_staging",
            "pengembalian_progress_transaction",
            "pengembalian_progress_import_batch",
            "pengembalian_progress_bulanan",
            "pengembalian_payment_transaction",
        ]
        try:
            return clear_tables_without_secondary_indexes(conn, tables)
        finally:
            conn.close()

    def sync_obligations(self):
        conn = self.connect()
        try:
            master_count = conn.execute("SELECT count(*) FROM pengembalian_master_obligation").fetchone()[0]
            legacy_count = conn.execute("SELECT count(*) FROM pengembalian_obligation").fetchone()[0]
            if master_count == 0 and legacy_count == 0:
                self.backfill()
                master_count = conn.execute("SELECT count(*) FROM pengembalian_master_obligation").fetchone()[0]
                legacy_count = conn.execute("SELECT count(*) FROM pengembalian_obligation").fetchone()[0]
            if master_count > 0 and legacy_count == 0:
                conn.execute("""INSERT INTO pengembalian_obligation
                    (obligation_id,nip,tahun_sp2d,nama_sdm,provinsi,periode_id,final_tukin,final_uang_makan,
                     final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,sumber_sp2d,flags_json,
                     source_record_ids,created_at,updated_at,awal_tukin,awal_uang_makan,awal_total,source_import_id)
                    SELECT obligation_id,nip,tahun_sp2d,nama_sdm,provinsi,periode_id,final_tukin,
                           final_uang_makan,final_total,status_sp2d,tahun_sp2d_awal,
                           tahun_sp2d_update,sumber_sp2d,flags_json,source_record_ids,
                           created_at,updated_at,awal_tukin,awal_uang_makan,awal_total,source_import_id
                    FROM pengembalian_master_obligation
                    ON CONFLICT (obligation_id) DO UPDATE SET
                        nip=excluded.nip, tahun_sp2d=excluded.tahun_sp2d,
                        nama_sdm=excluded.nama_sdm, provinsi=excluded.provinsi,
                        periode_id=excluded.periode_id, final_tukin=excluded.final_tukin,
                        final_uang_makan=excluded.final_uang_makan, final_total=excluded.final_total,
                        status_sp2d=excluded.status_sp2d, tahun_sp2d_awal=excluded.tahun_sp2d_awal,
                        tahun_sp2d_update=excluded.tahun_sp2d_update, sumber_sp2d=excluded.sumber_sp2d,
                        flags_json=excluded.flags_json, source_record_ids=excluded.source_record_ids,
                        awal_tukin=excluded.awal_tukin,awal_uang_makan=excluded.awal_uang_makan,
                        awal_total=excluded.awal_total,source_import_id=excluded.source_import_id,
                        updated_at=excluded.updated_at""")
            elif legacy_count > 0 and master_count == 0:
                conn.execute("""INSERT INTO pengembalian_master_obligation
                    (obligation_id,periode_id,nip,tahun_sp2d,nama_sdm,provinsi,final_tukin,
                     final_uang_makan,final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,
                     sumber_sp2d,flags_json,source_record_ids,created_at,updated_at,
                     awal_tukin,awal_uang_makan,awal_total,source_import_id)
                    SELECT obligation_id,COALESCE(periode_id,'LEGACY'),nip,tahun_sp2d,nama_sdm,
                           provinsi,final_tukin,final_uang_makan,final_total,status_sp2d,
                           tahun_sp2d_awal,tahun_sp2d_update,sumber_sp2d,flags_json,source_record_ids,
                           created_at,updated_at,awal_tukin,awal_uang_makan,awal_total,source_import_id
                    FROM pengembalian_obligation
                    ON CONFLICT (obligation_id) DO UPDATE SET
                        periode_id=excluded.periode_id, nip=excluded.nip, tahun_sp2d=excluded.tahun_sp2d,
                        nama_sdm=excluded.nama_sdm, provinsi=excluded.provinsi, final_tukin=excluded.final_tukin,
                        final_uang_makan=excluded.final_uang_makan, final_total=excluded.final_total,
                        status_sp2d=excluded.status_sp2d, tahun_sp2d_awal=excluded.tahun_sp2d_awal,
                        tahun_sp2d_update=excluded.tahun_sp2d_update, sumber_sp2d=excluded.sumber_sp2d,
                        flags_json=excluded.flags_json, source_record_ids=excluded.source_record_ids,
                        awal_tukin=excluded.awal_tukin,awal_uang_makan=excluded.awal_uang_makan,
                        awal_total=excluded.awal_total,source_import_id=excluded.source_import_id,
                        updated_at=excluded.updated_at""")
            return "pengembalian_master_obligation" if conn.execute("SELECT count(*) FROM pengembalian_master_obligation").fetchone()[0] > 0 else "pengembalian_obligation"
        finally:
            conn.close()

    @staticmethod
    def _obligation_id(period_id, nip, year):
        return "OBL-" + sha256(f"{period_id}|{nip}|{year}".encode()).hexdigest()[:24]

    def backfill(self):
        """Build one obligation per Master period + NIP + SP2D year."""
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            conn.execute("""UPDATE pengembalian_final SET
                total_tukin_awal=COALESCE(TRY_CAST(json_extract_string(row_json,'$.total_awal_tukin') AS DECIMAL(18,2)),0),
                final_tukin=COALESCE(TRY_CAST(json_extract_string(row_json,'$.final_total_pengembalian_tukin') AS DECIMAL(18,2)),0),
                final_uang_makan=COALESCE(TRY_CAST(json_extract_string(row_json,'$.final_total_pengembalian_uang_makan') AS DECIMAL(18,2)),0),
                final_total=COALESCE(TRY_CAST(json_extract_string(row_json,'$.final_total_pengembalian_tukin_uang_makan') AS DECIMAL(18,2)),
                    COALESCE(TRY_CAST(json_extract_string(row_json,'$.final_total_pengembalian_tukin') AS DECIMAL(18,2)),0)+
                    COALESCE(TRY_CAST(json_extract_string(row_json,'$.final_total_pengembalian_uang_makan') AS DECIMAL(18,2)),0))
                WHERE total_tukin_awal IS NULL OR final_tukin IS NULL OR final_uang_makan IS NULL OR final_total IS NULL""")
            conn.execute("""INSERT INTO pengembalian_master_obligation
                (obligation_id,periode_id,nip,tahun_sp2d,nama_sdm,provinsi,final_tukin,
                 final_uang_makan,final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,
                 sumber_sp2d,flags_json,source_record_ids,opening_balance,created_at,updated_at,
                 awal_tukin,awal_uang_makan,awal_total,source_import_id)
                SELECT 'OBL-' || substr(md5(periode_id || '|' || nip || '|' || tahun_sp2d::VARCHAR),1,24),
                    periode_id,nip,tahun_sp2d,max(nama),max(provinsi),sum(COALESCE(final_tukin,0)),
                    sum(COALESCE(final_uang_makan,0)), sum(COALESCE(final_total,0)),
                    CASE WHEN count(DISTINCT tahun_sp2d) OVER (PARTITION BY periode_id,nip)>1 THEN 'MULTI_SP2D'
                         ELSE 'NORMAL_SP2D' END, min(tahun_sp2d), max(tahun_sp2d),
                    'MASTER_PENGEMBALIAN_FINAL',
                    CASE WHEN abs(sum(COALESCE(final_total,0))-sum(COALESCE(final_tukin,0))-sum(COALESCE(final_uang_makan,0)))>0.01
                         THEN '["TOTAL_MISMATCH"]' ELSE '[]' END,
                    to_json(list(record_id)),0,now(),now(),sum(COALESCE(total_tukin_awal,0)),0,
                    sum(COALESCE(total_tukin_awal,0)),NULL
                FROM pengembalian_final WHERE periode_id IS NOT NULL AND nip IS NOT NULL AND tahun_sp2d IS NOT NULL
                GROUP BY periode_id,nip,tahun_sp2d
                ON CONFLICT (periode_id,nip,tahun_sp2d) DO UPDATE SET
                    nama_sdm=excluded.nama_sdm,provinsi=excluded.provinsi,
                    awal_tukin=excluded.awal_tukin,awal_uang_makan=excluded.awal_uang_makan,
                    awal_total=excluded.awal_total,
                    final_tukin=excluded.final_tukin,final_uang_makan=excluded.final_uang_makan,
                    final_total=excluded.final_total,status_sp2d=excluded.status_sp2d,
                    flags_json=excluded.flags_json,source_record_ids=excluded.source_record_ids,updated_at=now()""")
            conn.execute("""INSERT INTO pengembalian_obligation
                (obligation_id,nip,tahun_sp2d,nama_sdm,provinsi,periode_id,final_tukin,final_uang_makan,
                 final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,sumber_sp2d,flags_json,
                 source_record_ids,created_at,updated_at,awal_tukin,awal_uang_makan,awal_total,source_import_id)
                SELECT obligation_id,nip,tahun_sp2d,nama_sdm,provinsi,periode_id,final_tukin,
                       final_uang_makan,final_total,status_sp2d,tahun_sp2d_awal,tahun_sp2d_update,
                       sumber_sp2d,flags_json,source_record_ids,created_at,updated_at
                       ,awal_tukin,awal_uang_makan,awal_total,source_import_id
                FROM pengembalian_master_obligation
                ON CONFLICT (obligation_id) DO UPDATE SET
                    nip=excluded.nip, tahun_sp2d=excluded.tahun_sp2d,
                    nama_sdm=excluded.nama_sdm, provinsi=excluded.provinsi,
                    periode_id=excluded.periode_id, final_tukin=excluded.final_tukin,
                    final_uang_makan=excluded.final_uang_makan, final_total=excluded.final_total,
                    status_sp2d=excluded.status_sp2d, tahun_sp2d_awal=excluded.tahun_sp2d_awal,
                    tahun_sp2d_update=excluded.tahun_sp2d_update, sumber_sp2d=excluded.sumber_sp2d,
                    flags_json=excluded.flags_json, source_record_ids=excluded.source_record_ids,
                    awal_tukin=excluded.awal_tukin,awal_uang_makan=excluded.awal_uang_makan,
                    awal_total=excluded.awal_total,source_import_id=excluded.source_import_id,
                    updated_at=excluded.updated_at""")
            stats = conn.execute("""SELECT count(*),sum(final_tukin),sum(final_uang_makan),sum(final_total),
                sum(CASE WHEN abs(final_total-final_tukin-final_uang_makan)>0.01 THEN 1 ELSE 0 END)
                FROM pengembalian_master_obligation""").fetchone()
            conn.execute("COMMIT")
            return {"status": "ok", "obligations": int(stats[0] or 0),
                    "total_tukin": float(stats[1] or 0), "total_uang_makan": float(stats[2] or 0),
                    "total_kewajiban": float(stats[3] or 0), "mismatch": int(stats[4] or 0)}
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def parse_baseline_workbook(self, workbook_path, metadata=None):
        """Read only the three authoritative bank sheets from the legacy baseline."""
        metadata = dict(metadata or {})
        workbook = load_workbook(workbook_path, read_only=True, data_only=True)
        authoritative = {
            "BNBA PENGEMBALIAN MANDIRI": "MANDIRI",
            "BNBA PENGEMBALIAN BRI": "BRI",
            "BNBA PENGEMBALIAN BSI": "BSI",
        }
        rows, sheet_stats = [], []
        try:
            for sheet_name, fallback_bank in authoritative.items():
                if sheet_name not in workbook.sheetnames:
                    sheet_stats.append({"sheet": sheet_name, "status": "MISSING", "transactions": 0})
                    continue
                sheet = workbook[sheet_name]
                header_rows = list(sheet.iter_rows(min_row=1, max_row=3, values_only=True))
                headers = list(header_rows[0])
                years = list(header_rows[1])
                ntpns = list(header_rows[2])
                keyed = {_key(value): index for index, value in enumerate(headers) if _clean(value)}

                def identity_index(*aliases):
                    for alias in aliases:
                        if _key(alias) in keyed:
                            return keyed[_key(alias)]
                    return None

                identity = {
                    "NIP": identity_index("NIP", "Nomor NIP"),
                    "Nama": identity_index("Nama", "Nama SDM", "Nama sk", "Nama Direk"),
                    "Provinsi": identity_index("Provinsi"),
                    "Bank": identity_index("Bank", "Nama Bank"),
                    "Nomor Rekening": identity_index("Nomor Rekening", "Nomer Rekening"),
                }
                progress_columns = []
                for index, header in enumerate(headers):
                    label = (_clean(header) or "").upper()
                    if not (label.startswith("PENGEMBALIAN ") and "TAHAP" in label):
                        continue
                    if any(word in label for word in ("SISA", "TAGGING", "DUMMY", "HASIL BLOKIR", "KONTROL")):
                        continue
                    component = "UANG_MAKAN" if "UANG MAKAN" in label else "TUKIN" if "TUKIN" in label else None
                    match = re.search(r"TAHAP\s*([IVXLCDM]+|\d+)", label)
                    stage = _stage_number(match.group(1)) if match else None
                    year = _number(years[index] if index < len(years) else None)
                    if component and stage and year and 1900 <= year <= 2200:
                        progress_columns.append((index, component, stage, int(year), ntpns[index] if index < len(ntpns) else None))
                transaction_count = 0
                for source_row, values in enumerate(sheet.iter_rows(min_row=6, values_only=True), 6):
                    values = list(values)
                    nip_index = identity["NIP"]
                    nip = _nip(values[nip_index] if nip_index is not None and nip_index < len(values) else None)
                    if not nip:
                        continue
                    base = {}
                    for target, position in identity.items():
                        base[target] = values[position] if position is not None and position < len(values) else None
                    for column, component, stage, year, ntpn in progress_columns:
                        amount = _number(values[column] if column < len(values) else None) or 0
                        if amount <= 0:
                            continue
                        rows.append({
                            **base,
                            "Bank": base.get("Bank") or fallback_bank,
                            "Tahun SP2D": year,
                            "Komponen": component,
                            "Tahap": stage,
                            "Nominal Diajukan": amount,
                            "Nominal Berhasil": amount,
                            "Status": "BERHASIL",
                            "NTPN": None if _clean(ntpn) in {None, "-"} else ntpn,
                            "Periode Debit": f"Baseline Tahap {stage}",
                            "Source Sheet": sheet_name,
                            "Source Row Number": source_row,
                        })
                        transaction_count += 1
                sheet_stats.append({"sheet": sheet_name, "status": "PARSED", "columns": len(progress_columns), "transactions": transaction_count})
        finally:
            workbook.close()
        return rows, {"format": "INITIAL_BASELINE", "sheets": sheet_stats,
                      "transaction_rows": len(rows), "ignored_sheets": [name for name in workbook.sheetnames if name not in authoritative]}

    def preview_baseline_workbook(self, workbook_path, metadata=None):
        metadata = dict(metadata or {})
        metadata["import_mode"] = "INITIAL_BASELINE"
        rows, adapter = self.parse_baseline_workbook(workbook_path, metadata)
        result = self.preview(rows, metadata)
        result["source_adapter"] = adapter
        return result

    def _normalize(self, source, row_number, metadata=None):
        metadata = metadata or {}
        n = {_key(k): v for k, v in source.items()}
        get = lambda *names: next((n.get(_key(x)) for x in names if _key(x) in n), None)
        raw_nip = get("nip", "nip sdm", "nomor nip", "no nip")
        nip = _nip(raw_nip)
        year_raw = get("tahun sp2d", "tahun_sp2d")
        try:
            year = int(float(year_raw)) if _clean(year_raw) else None
        except (ValueError, TypeError):
            year = None
        component_input = _component(get("komponen", "komponen debit", "komponen_debit"))
        stage_raw = get("tahap", "stage", "tahap pengembalian")
        stage = _stage_number(stage_raw)
        tukin_raw, um_raw = get("debit tukin", "nominal debit tukin"), get("debit uang makan", "nominal debit uang makan")
        total_raw = get("nominal debit total", "nominal debit", "nominal debet", "jumlah debit")
        proposed_raw = get("nominal diajukan", "nominal_diajukan")
        successful_raw = get("nominal berhasil", "nominal_berhasil")
        tukin, um = _number(tukin_raw), _number(um_raw)
        status = (_clean(get("status debit", "status")) or "").upper().replace(" ", "_")
        if status == "SUKSES": status = "BERHASIL"
        original_bank = _clean(get("nama bank", "bank") or metadata.get("nama_bank"))
        tanggal = _date(get("tanggal proses", "tanggal debit"))
        period = _clean(get("periode debit") or metadata.get("periode_debit"))
        if stage is None and period:
            stage_match = re.search(r"TAHAP\s*([IVXLCDM]+|\d+)", period.upper())
            stage = _stage_number(stage_match.group(1)) if stage_match else None
        if not period and stage:
            period = f"Tahap {stage}"
        master_period = _clean(get("periode master", "periode id", "periode_id") or metadata.get("periode_id"))
        flags, errors, warnings = [], [], []
        if not nip: errors.append("NIP_KOSONG")
        if year is None or year < 1900 or year > 2200: errors.append("TAHUN_SP2D_INVALID")
        if not original_bank: errors.append("NAMA_BANK_KOSONG")
        if not period: errors.append("PERIODE_DEBIT_KOSONG")
        if metadata.get("import_mode") in {"INITIAL_BASELINE", "PROGRESS_STAGE_IMPORT"} and not stage:
            errors.append("TAHAP_INVALID")
        if status not in ALLOWED_STATUS: errors.append("STATUS_TIDAK_DIKENALI")
        proposed = _number(proposed_raw)
        successful = _number(successful_raw)
        if component_input and proposed is not None:
            effective = (successful if successful is not None else proposed) if status == "BERHASIL" else proposed
            tukin, um = (effective, 0) if component_input == "TUKIN" else (0, effective)
        if tukin is None and um is None and _number(total_raw) is not None:
            errors.append("COMPONENT_ALLOCATION_REQUIRED")
            warnings.append("NEEDS_REVIEW")
        elif tukin is None and um is None: errors.append("NOMINAL_DEBIT_KOSONG")
        tukin, um = float(tukin or 0), float(um or 0)
        if tukin < 0 or um < 0: errors.append("NOMINAL_NEGATIF")
        component = component_input or ("TUKIN_DAN_UANG_MAKAN" if tukin and um else "TUKIN" if tukin else "UANG_MAKAN" if um else "TIDAK_ADA_NOMINAL")
        if component_input not in COMPONENTS and component_input is not None: errors.append("KOMPONEN_INVALID")
        if proposed is None:
            proposed = float((_number(total_raw) if _number(total_raw) is not None else tukin + um) or 0)
        if successful is None:
            successful = float(tukin + um) if status in {"BERHASIL", "REVERSAL"} else 0.0
        if proposed < 0 or successful < 0: errors.append("NOMINAL_NEGATIF")
        if successful > proposed and status != "REVERSAL": warnings.append("BERHASIL_MELEBIHI_DIAJUKAN")
        if status not in {"BERHASIL", "REVERSAL"} and successful > 0: errors.append("NOMINAL_BERHASIL_STATUS_TIDAK_BERHASIL")
        if not tanggal: warnings.append("TANGGAL_DEBIT_KOSONG_ATAU_INVALID")
        source_row_number = _number(get("source row number", "source_row_number"))
        result = {"raw_nip": _clean(raw_nip), "nip": nip, "nama_sdm": _clean(get("nama sdm", "nama")), "tahun_sp2d": year,
                  "periode_id": master_period,
                  "provinsi": _clean(get("provinsi")), "nama_bank_original": original_bank,
                  "nama_bank_normalized": normalize_bank(original_bank), "periode_debit": period,
                  "tanggal_debit": tanggal, "tanggal_surat": _date(get("tanggal surat")), "tahap": stage,
                  "nomor_surat": _clean(get("nomor surat")), "status_debit": status,
                  "nominal_debit_tukin": tukin, "nominal_debit_uang_makan": um,
                  "nominal_debit_total": tukin + um, "komponen_debit": component,
                  "nominal_diajukan": float(proposed), "nominal_berhasil": float(successful),
                  "nomor_rekening": _clean(get("nomor rekening", "nomer rekening", "rekening")),
                  "ntpn": _clean(get("ntpn")), "keterangan": _clean(get("keterangan")),
                  "source_sheet": _clean(get("source sheet", "source_sheet") or metadata.get("source_sheet")),
                  "keterangan_gagal": _clean(get("keterangan gagal", "alasan gagal")),
                  "kategori_gagal": _clean(get("kategori gagal")), "source_row_number": int(source_row_number or row_number),
                  "original_transaction_id": _clean(get("original transaction id", "transaksi asal")),
                  "correction_type": _clean(get("correction type", "jenis koreksi")),
                  "errors": errors, "warnings": warnings, "flags": flags, "raw_data": dict(source)}
        fingerprint_parts = [master_period, nip, year, component, stage, result["nama_bank_normalized"],
                             result["ntpn"], successful, tanggal]
        result["fingerprint"] = sha256("|".join(str(x or "") for x in fingerprint_parts).encode()).hexdigest()
        return result

    def preview(self, rows, metadata=None):
        metadata = dict(metadata or {})
        rows, source_adapter = _expand_master_progress_rows(rows)
        if source_adapter:
            metadata["source_adapter"] = source_adapter
        self.sync_obligations()
        normalized = [self._normalize(row, index + 2, metadata) for index, row in enumerate(rows)]
        file_hash = _clean(metadata.get("file_hash")) or sha256(
            json.dumps(list(rows), sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()
        batch_id = metadata.get("import_batch_id") or "IMPORT_PROGRESS_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6].upper()
        conn = self.connect()
        try:
            obligation_table = self.sync_obligations()
            obligation_where = " WHERE periode_id=?" if metadata.get("periode_id") else ""
            obligation_params = [metadata["periode_id"]] if metadata.get("periode_id") else []
            obligation_rows = conn.execute(
                f"SELECT nip,tahun_sp2d,obligation_id,final_tukin,final_uang_makan,final_total,nama_sdm,status_sp2d,periode_id FROM {obligation_table}{obligation_where}",
                obligation_params,
            ).fetchall()
            obligations = {}
            obligations_by_nip = {}
            for r in obligation_rows:
                obligation = {
                    "obligation_id": r[2], "final_tukin": float(r[3] or 0),
                    "final_um": float(r[4] or 0), "final_total": float(r[5] or 0),
                    "nama": r[6], "status_sp2d": r[7], "periode_id": r[8],
                }
                obligations.setdefault((str(r[0]), int(r[1])), []).append(obligation)
                obligations_by_nip.setdefault(str(r[0]), []).append(obligation)
            paid = {r[0]: (float(r[1] or 0),float(r[2] or 0)) for r in conn.execute("""SELECT obligation_id,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_tukin WHEN status_debit='REVERSAL' THEN -nominal_debit_tukin ELSE 0 END),
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_uang_makan WHEN status_debit='REVERSAL' THEN -nominal_debit_uang_makan ELSE 0 END)
                FROM pengembalian_progress_transaction t
                JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id
                WHERE coalesce(t.is_active,true) AND b.status IN ('COMMITTED','PARTIAL')
                GROUP BY t.obligation_id""").fetchall()}
            existing = {r[0]: r[1:] for r in conn.execute(
                "SELECT fingerprint,transaction_id,import_batch_id,created_at FROM pengembalian_progress_transaction WHERE coalesce(is_active,true)").fetchall()}
            original_transactions = {r[0]: {"obligation_id": r[1], "nip": r[2], "tahun_sp2d": r[3],
                "tukin": float(r[4] or 0), "um": float(r[5] or 0), "status": r[6]} for r in conn.execute(
                """SELECT transaction_id,obligation_id,nip,tahun_sp2d,nominal_debit_tukin,
                nominal_debit_uang_makan,status_debit FROM pengembalian_progress_transaction
                WHERE coalesce(is_active,true)""").fetchall()}
            reversed_totals = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in conn.execute(
                """SELECT original_transaction_id,sum(nominal_debit_tukin),sum(nominal_debit_uang_makan)
                FROM pengembalian_progress_transaction WHERE coalesce(is_active,true)
                AND status_debit='REVERSAL' AND original_transaction_id IS NOT NULL
                GROUP BY original_transaction_id""").fetchall()}
            file_duplicate = conn.execute("""SELECT import_batch_id,imported_at FROM pengembalian_progress_import_batch
                WHERE source_file_hash=? AND status IN ('COMMITTED','PARTIAL') ORDER BY imported_at DESC LIMIT 1""",[file_hash]).fetchone()
        except Exception:
            conn.close(); raise
        seen = set()
        projected_paid = dict(paid)
        for row in normalized:
            key = (str(row["nip"] or ""), row["tahun_sp2d"])
            nip_matches = obligations_by_nip.get(str(row["nip"] or ""), [])
            if row["nip"] and not nip_matches:
                row["errors"].append("NIP_NOT_FOUND"); row["matching_status"]="NIP_NOT_FOUND"
            elif key not in obligations:
                row["errors"].append("SP2D_NOT_FOUND"); row["matching_status"]="SP2D_NOT_FOUND"
            else:
                candidates = obligations[key]
                if row.get("periode_id"):
                    candidates = [item for item in candidates if str(item.get("periode_id") or "") == row["periode_id"]]
                    if not candidates:
                        row["errors"].append("MASTER_PERIOD_NOT_FOUND"); row["matching_status"]="MASTER_PERIOD_NOT_FOUND"
                if len(candidates) > 1:
                    row["errors"].append("AMBIGUOUS_OBLIGATION"); row["matching_status"]="AMBIGUOUS_OBLIGATION"
                    row["flags"].append("MASTER_PERIOD_REQUIRED")
                if len(candidates) != 1:
                    obligation = None
                else:
                    obligation=candidates[0]; row["obligation_id"] = obligation["obligation_id"];row["matching_status"]="MATCHED"
                    row["periode_id"] = obligation.get("periode_id")
                if obligation is not None:
                    component_final = obligation["final_tukin"] if row["komponen_debit"] == "TUKIN" else obligation["final_um"] if row["komponen_debit"] == "UANG_MAKAN" else obligation["final_total"]
                    if component_final <= 0 and row["nominal_diajukan"] > 0:
                        row["errors"].append("UNMATCHED_FINAL")
                        row["matching_status"] = "UNMATCHED_FINAL"
                    if row["nama_sdm"] and obligation["nama"] and _key(row["nama_sdm"]) != _key(obligation["nama"]): row["warnings"].append("NAME_MISMATCH")
                    if obligation["status_sp2d"] == "MULTI_SP2D": row["flags"].append("MULTI_SP2D")
                    paid_tukin,paid_um=paid.get(obligation["obligation_id"],(0,0));sign=-1 if row["status_debit"]=="REVERSAL" else 1 if row["status_debit"]=="BERHASIL" else 0
                    row["existing_paid"]=paid_tukin+paid_um;row["existing_remaining"]=max(obligation["final_total"]-(paid_tukin+paid_um),0)
                    projected_tukin=paid_tukin+sign*row["nominal_debit_tukin"];projected_um=paid_um+sign*row["nominal_debit_uang_makan"]
                    row["projected_remaining"]=max(obligation["final_total"]-(projected_tukin+projected_um),0)
                    row["projected_overpayment"]=max((projected_tukin+projected_um)-obligation["final_total"],0)
                    if row["projected_overpayment"]>0: row["warnings"].append("POTENTIAL_OVERPAYMENT");row["flags"].append("OVERPAYMENT")
            if row["status_debit"] == "REVERSAL":
                original_id = row.get("original_transaction_id")
                original = original_transactions.get(original_id)
                if not original_id:
                    row["errors"].append("REVERSAL_ORIGINAL_REQUIRED")
                elif not original or original["status"] != "BERHASIL":
                    row["errors"].append("REVERSAL_ORIGINAL_NOT_FOUND")
                elif row.get("obligation_id") != original["obligation_id"]:
                    row["errors"].append("REVERSAL_OBLIGATION_MISMATCH")
                else:
                    prior_tukin, prior_um = reversed_totals.get(original_id, (0, 0))
                    if prior_tukin + row["nominal_debit_tukin"] > original["tukin"] or prior_um + row["nominal_debit_uang_makan"] > original["um"]:
                        row["errors"].append("REVERSAL_EXCEEDS_ORIGINAL")
            if row["fingerprint"] in existing or row["fingerprint"] in seen:
                row["errors"].append("DUPLICATE_TRANSACTION")
                row["existing_transaction"] = existing.get(row["fingerprint"])
            seen.add(row["fingerprint"])
            if row.get("obligation_id") and not row["errors"]:
                obligation=next(item for item in obligations[key] if item["obligation_id"] == row["obligation_id"]);actual_tukin,actual_um=paid.get(row["obligation_id"],(0,0))
                running_tukin,running_um=projected_paid.get(row["obligation_id"],(actual_tukin,actual_um))
                sign=-1 if row["status_debit"]=="REVERSAL" else 1 if row["status_debit"]=="BERHASIL" else 0
                running_tukin+=sign*row["nominal_debit_tukin"];running_um+=sign*row["nominal_debit_uang_makan"]
                projected_paid[row["obligation_id"]]=(running_tukin,running_um)
                row["existing_paid"]=actual_tukin+actual_um
                row["existing_remaining"]=max(obligation["final_total"]-(actual_tukin+actual_um),0)
                row["projected_remaining"]=max(obligation["final_total"]-(running_tukin+running_um),0)
                row["projected_overpayment"]=max((running_tukin+running_um)-obligation["final_total"],0)
                if row["projected_overpayment"]>0 and "POTENTIAL_OVERPAYMENT" not in row["warnings"]: row["warnings"].append("POTENTIAL_OVERPAYMENT");row["flags"].append("OVERPAYMENT")
            row["matching_status"] = row.get("matching_status") or "NEEDS_REVIEW"
            review_errors = {"COMPONENT_ALLOCATION_REQUIRED", "AMBIGUOUS_OBLIGATION"}
            row["classification"] = "DUPLICATE" if "DUPLICATE_TRANSACTION" in row["errors"] else "NEEDS_REVIEW" if review_errors.intersection(row["errors"]) else "INVALID" if row["errors"] else "WARNING" if row["warnings"] else "VALID"
        def count(fn): return sum(1 for r in normalized if fn(r))
        stats = {"total": len(normalized), "valid": count(lambda r:r["classification"]=="VALID"),
                  "invalid": count(lambda r:r["classification"]=="INVALID"), "warning": count(lambda r:r["classification"]=="WARNING"),
                  "needs_review": count(lambda r:r["classification"]=="NEEDS_REVIEW"),
                 "jumlah_nip": len({r["nip"] for r in normalized if r.get("nip")}),
                 "matched_final": count(lambda r:r.get("matching_status")=="MATCHED"),
                 "unmatched_final": count(lambda r:"UNMATCHED_FINAL" in r["errors"] or r.get("matching_status") in {"NIP_NOT_FOUND","SP2D_NOT_FOUND","MASTER_PERIOD_NOT_FOUND"}),
                 "nip_ditemukan": count(lambda r:r.get("obligation_id")), "nip_tidak_ditemukan": count(lambda r:"NIP_NOT_FOUND" in r["errors"]),
                  "tahun_sp2d_cocok": count(lambda r:r.get("obligation_id")), "tahun_sp2d_tidak_cocok": count(lambda r:"SP2D_NOT_FOUND" in r["errors"]),
                  "ambiguous_obligation": count(lambda r:"AMBIGUOUS_OBLIGATION" in r["errors"]),
                 "berhasil": count(lambda r:r["status_debit"]=="BERHASIL"), "gagal": count(lambda r:r["status_debit"]=="GAGAL"),
                 "tukin": count(lambda r:r["komponen_debit"]=="TUKIN"), "uang_makan": count(lambda r:r["komponen_debit"]=="UANG_MAKAN"),
                 "gabungan": count(lambda r:r["komponen_debit"]=="TUKIN_DAN_UANG_MAKAN"),
                 "duplicate": count(lambda r:"DUPLICATE_TRANSACTION" in r["errors"]),
                 "potential_overpayment": count(lambda r:"POTENTIAL_OVERPAYMENT" in r["warnings"]),
                 "tahap": sorted({int(r["tahap"]) for r in normalized if r.get("tahap")}),
                 "tahun_sp2d": sorted({int(r["tahun_sp2d"]) for r in normalized if r.get("tahun_sp2d")}),
                 "bank": sorted({r["nama_bank_normalized"] for r in normalized if r.get("nama_bank_normalized")}),
                 "total_tukin": sum(r["nominal_debit_tukin"] for r in normalized),
                 "total_uang_makan": sum(r["nominal_debit_uang_makan"] for r in normalized),
                 "total_diajukan": sum(r["nominal_diajukan"] for r in normalized),
                 "total_debit": sum(r["nominal_diajukan"] for r in normalized),
                 "debit_berhasil":sum(r["nominal_berhasil"] for r in normalized if r["status_debit"]=="BERHASIL"),
                 "debit_gagal":sum(r["nominal_diajukan"] for r in normalized if r["status_debit"]=="GAGAL")}
        preview_filters={"periode_id":metadata["periode_id"]} if metadata.get("periode_id") else None
        before=self.progress(preview_filters,limit=1)["summary"]
        successful=sum(r["nominal_berhasil"] for r in normalized if r["status_debit"]=="BERHASIL" and not r["errors"])
        reversals=sum(r["nominal_berhasil"] for r in normalized if r["status_debit"]=="REVERSAL" and not r["errors"])
        projected_states=[]
        for obligation in (item for values in obligations.values() for item in values):
            p_tukin,p_um=projected_paid.get(obligation["obligation_id"],paid.get(obligation["obligation_id"],(0,0)))
            remaining=max(obligation["final_total"]-(p_tukin+p_um),0)
            projected_states.append("OVERPAYMENT" if p_tukin+p_um>obligation["final_total"] else "LUNAS" if remaining==0 else "PARSIAL" if p_tukin+p_um>0 else "BELUM ADA PENGEMBALIAN")
        impact={"kewajiban_sebelum":before["total_kewajiban"],"realisasi_sebelum":before["total_berhasil"],
                "sisa_sebelum":before["total_sisa"],"nominal_berhasil_import":successful,
                "nominal_reversal_import":reversals,"proyeksi_realisasi":max(before["total_berhasil"]+successful-reversals,0),
                "proyeksi_sisa":max(before["total_sisa"]-successful+reversals,0),
                "potential_overpayment":sum(r.get("projected_overpayment",0) for r in normalized),
                "sdm_menjadi_lunas":sum(1 for x in projected_states if x=="LUNAS")-before["sdm_lunas"],
                "sdm_parsial":sum(1 for x in projected_states if x=="PARSIAL"),
                "sdm_belum_lunas":sum(1 for x in projected_states if x=="BELUM ADA PENGEMBALIAN"),
                "sdm_overpayment":sum(1 for x in projected_states if x=="OVERPAYMENT")}
        try:
            conn.execute("BEGIN")
            batch_status = "FAILED" if file_duplicate else "READY"
            conn.execute("""INSERT INTO pengembalian_progress_import_batch
                (import_batch_id,source_filename,source_file_hash,periode_debit,nama_bank_original,nama_bank_normalized,status,
                total_rows,valid_rows,invalid_rows,warning_rows,duplicate_rows,berhasil_rows,gagal_rows,total_tukin,total_uang_makan,
                total_debit,nominal_berhasil,nominal_gagal,metadata_json,imported_by,import_mode,periode_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [batch_id,metadata.get("filename"),file_hash,metadata.get("periode_debit"),metadata.get("nama_bank"),normalize_bank(metadata.get("nama_bank")),batch_status,
                 stats["total"],stats["valid"],stats["invalid"],stats["warning"],stats["duplicate"],stats["berhasil"],stats["gagal"],stats["total_tukin"],stats["total_uang_makan"],stats["total_debit"],stats["debit_berhasil"],stats["debit_gagal"],json.dumps(metadata,default=str),metadata.get("created_by","system"),metadata.get("import_mode","PROGRESS_STAGE_IMPORT"),metadata.get("periode_id")])
            stage=[]
            for r in normalized:
                stage.append([str(uuid.uuid4()),batch_id,metadata.get("filename"),file_hash,r["source_row_number"],r.get("raw_nip"),r["nip"],r["nama_sdm"],r["tahun_sp2d"],r["provinsi"],r["nama_bank_original"],r["nama_bank_normalized"],r["periode_debit"],r["tanggal_debit"],r["tanggal_surat"],r["nomor_surat"],r["nominal_debit_tukin"],r["nominal_debit_uang_makan"],r["nominal_debit_total"],r["status_debit"],r["keterangan_gagal"],r["komponen_debit"],r["fingerprint"],r["classification"],r["matching_status"],json.dumps(r["errors"]),json.dumps(r["warnings"]),r.get("obligation_id"),r.get("existing_transaction",[None])[0] if r.get("existing_transaction") else None,r.get("existing_paid"),r.get("existing_remaining"),r.get("projected_remaining"),r.get("projected_overpayment"),r.get("original_transaction_id"),r.get("correction_type"),json.dumps(r["raw_data"],default=str),r.get("periode_id"),r.get("tahap"),r.get("nomor_rekening"),r.get("nominal_diajukan"),r.get("nominal_berhasil"),r.get("ntpn"),r.get("keterangan"),r.get("source_sheet")])
            if stage:
                stage_columns=["staging_id","import_batch_id","source_file_name","source_file_hash","source_row_number","raw_nip","normalized_nip","nama_sdm","tahun_sp2d","provinsi","nama_bank_original","nama_bank_normalized","periode_debit","tanggal_debit","tanggal_surat","nomor_surat","debit_tukin","debit_uang_makan","debit_total","status_debit","alasan_gagal","komponen_debit","fingerprint","validation_status","matching_status","validation_messages","warning_messages","matched_obligation_id","existing_transaction_id","existing_paid","existing_remaining","projected_remaining","projected_overpayment","original_transaction_id","correction_type","raw_data","periode_id","tahap","nomor_rekening","nominal_diajukan","nominal_berhasil","ntpn","keterangan","source_sheet"]
                conn.register("_progress_stage",pd.DataFrame(stage,columns=stage_columns))
                conn.execute("""INSERT INTO pengembalian_progress_staging
                    (staging_id,import_batch_id,source_file_name,source_file_hash,source_row_number,raw_nip,normalized_nip,nama_sdm,tahun_sp2d,provinsi,nama_bank_original,nama_bank_normalized,periode_debit,tanggal_debit,tanggal_surat,nomor_surat,debit_tukin,debit_uang_makan,debit_total,status_debit,alasan_gagal,komponen_debit,fingerprint,validation_status,matching_status,validation_messages,warning_messages,matched_obligation_id,existing_transaction_id,existing_paid,existing_remaining,projected_remaining,projected_overpayment,original_transaction_id,correction_type,raw_data,periode_id,tahap,nomor_rekening,nominal_diajukan,nominal_berhasil,ntpn,keterangan,source_sheet)
                    SELECT staging_id,import_batch_id,source_file_name,source_file_hash,source_row_number,raw_nip,normalized_nip,nama_sdm,tahun_sp2d,provinsi,nama_bank_original,nama_bank_normalized,periode_debit,tanggal_debit,tanggal_surat,nomor_surat,debit_tukin,debit_uang_makan,debit_total,status_debit,alasan_gagal,komponen_debit,fingerprint,validation_status,matching_status,validation_messages,warning_messages,matched_obligation_id,existing_transaction_id,existing_paid,existing_remaining,projected_remaining,projected_overpayment,original_transaction_id,correction_type,raw_data,periode_id,tahap,nomor_rekening,nominal_diajukan,nominal_berhasil,ntpn,keterangan,source_sheet FROM _progress_stage""")
                conn.unregister("_progress_stage")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK");conn.close();raise
        conn.close()
        return {"status":"ok","import_batch_id":batch_id,"file_hash":file_hash,
                "source_adapter":source_adapter,
                "file_duplicate":{"warning":"FILE_ALREADY_IMPORTED","existing_batch_id":file_duplicate[0],"imported_at":str(file_duplicate[1])} if file_duplicate else None,
                "statistics":stats,"impact":impact,"rows":normalized}

    def import_rows(self, rows, metadata=None, imported_by="system"):
        metadata = dict(metadata or {})
        batch_id = metadata.get("import_batch_id")
        if not batch_id:
            metadata["created_by"] = imported_by
            preview = self.preview(rows, metadata)
            if preview.get("file_duplicate"):
                raise ValueError(f"FILE_ALREADY_IMPORTED: {preview['file_duplicate']['existing_batch_id']}")
            batch_id = preview["import_batch_id"]
        return self.commit_batch(batch_id, imported_by, bool(metadata.get("include_warnings", True)))

    def commit_batch(self, batch_id, imported_by="system", include_warnings=True):
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            batch=conn.execute("SELECT status,source_file_hash,periode_id FROM pengembalian_progress_import_batch WHERE import_batch_id=?",[batch_id]).fetchone()
            if not batch: raise ValueError("Import batch tidak ditemukan")
            if batch[0] != "READY": raise ValueError(f"Batch tidak dapat di-commit dari status {batch[0]}")
            duplicate_file=conn.execute("SELECT import_batch_id FROM pengembalian_progress_import_batch WHERE source_file_hash=? AND status IN ('COMMITTED','PARTIAL') AND import_batch_id<>? LIMIT 1",[batch[1],batch_id]).fetchone()
            if duplicate_file: raise ValueError(f"FILE_ALREADY_IMPORTED: {duplicate_file[0]}")
            # WARNING rows are structurally valid and remain traceable. INVALID,
            # DUPLICATE and NEEDS_REVIEW never reach final transaction history.
            allowed = "('VALID','WARNING')" if include_warnings else "('VALID')"
            conn.execute(f"""INSERT INTO pengembalian_progress_transaction
                    (transaction_id,fingerprint,import_batch_id,obligation_id,nip,nama_sdm,tahun_sp2d,provinsi,periode_id,
                    nama_bank_original,nama_bank_normalized,periode_debit,bulan_debit,tahun_debit,tanggal_debit,
                    tanggal_surat,nomor_surat,komponen_debit,nominal_debit_tukin,nominal_debit_uang_makan,
                    nominal_debit_total,status_debit,keterangan_gagal,kategori_gagal,source_filename,
                    source_row_number,validation_flags,raw_data,created_by,is_active,original_transaction_id,correction_type,
                    tahap,nomor_rekening,nominal_diajukan,nominal_berhasil,ntpn,keterangan,source_sheet)
                SELECT uuid()::VARCHAR,fingerprint,import_batch_id,matched_obligation_id,normalized_nip,nama_sdm,tahun_sp2d,provinsi,periode_id,
                    nama_bank_original,nama_bank_normalized,periode_debit,month(tanggal_debit),year(tanggal_debit),tanggal_debit,
                    tanggal_surat,nomor_surat,komponen_debit,debit_tukin,debit_uang_makan,debit_total,status_debit,alasan_gagal,NULL,
                    source_file_name,source_row_number,warning_messages,raw_data,?,true,original_transaction_id,correction_type,
                    tahap,nomor_rekening,nominal_diajukan,nominal_berhasil,ntpn,keterangan,source_sheet
                FROM pengembalian_progress_staging WHERE import_batch_id=? AND validation_status IN {allowed}""",[imported_by,batch_id])
            inserted=conn.execute("SELECT count(*) FROM pengembalian_progress_transaction WHERE import_batch_id=?",[batch_id]).fetchone()[0]
            # Reconciliation uses net successful debit (successful minus reversal) and explicit overpayment.
            obligation_table = "pengembalian_master_obligation" if conn.execute("SELECT count(*) FROM pengembalian_master_obligation").fetchone()[0] else "pengembalian_obligation"
            rec=conn.execute(f"""WITH paid AS (SELECT t.obligation_id,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_tukin WHEN status_debit='REVERSAL' THEN -nominal_debit_tukin ELSE 0 END) paid_tukin,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_uang_makan WHEN status_debit='REVERSAL' THEN -nominal_debit_uang_makan ELSE 0 END) paid_um
                FROM pengembalian_progress_transaction t
                JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id
                WHERE coalesce(t.is_active,true) AND b.status IN ('COMMITTED','PARTIAL')
                GROUP BY t.obligation_id)
                SELECT sum(o.final_total),sum(coalesce(p.paid_tukin,0)+coalesce(p.paid_um,0)),
                    sum(greatest(o.final_total-(coalesce(p.paid_tukin,0)+coalesce(p.paid_um,0)),0)),
                    sum(greatest((coalesce(p.paid_tukin,0)+coalesce(p.paid_um,0))-o.final_total,0))
                FROM {obligation_table} o LEFT JOIN paid p USING(obligation_id)""").fetchone()
            reconciliation={"total_kewajiban":float(rec[0] or 0),"net_berhasil":float(rec[1] or 0),"total_sisa":float(rec[2] or 0),"overpayment":float(rec[3] or 0)}
            reconciliation["selisih"]=round((reconciliation["total_kewajiban"]+reconciliation["overpayment"])-(reconciliation["net_berhasil"]+reconciliation["total_sisa"]),2)
            if abs(reconciliation["selisih"])>0.01: raise ValueError("RECONCILIATION_FAILED")
            staged_count=conn.execute("SELECT count(*) FROM pengembalian_progress_staging WHERE import_batch_id=?",[batch_id]).fetchone()[0]
            batch_status="COMMITTED" if inserted==staged_count else "PARTIAL"
            conn.execute("UPDATE pengembalian_progress_import_batch SET status=?,reconciliation_json=? WHERE import_batch_id=?",[batch_status,json.dumps(reconciliation),batch_id])
            conn.execute("COMMIT")
            summary=self.progress({"periode_id":batch[2]} if batch[2] else None,limit=1)["summary"]
            return {"status":"ok","status_batch":batch_status,"import_batch_id":batch_id,"inserted":int(inserted),
                    "reconciliation":reconciliation,"summary":summary}
        except Exception:
            conn.execute("ROLLBACK")
            try: conn.execute("UPDATE pengembalian_progress_import_batch SET status='FAILED' WHERE import_batch_id=?",[batch_id])
            except Exception: pass
            raise
        finally:
            conn.close()

    def rollback_batch(self, batch_id):
        conn=self.connect()
        try:
            conn.execute("BEGIN")
            status=conn.execute("SELECT status,reverted_at FROM pengembalian_progress_import_batch WHERE import_batch_id=?",[batch_id]).fetchone()
            if not status: raise ValueError("Import batch tidak ditemukan")
            if status[0] not in {"COMMITTED","PARTIAL"}: raise ValueError("Hanya batch COMMITTED/PARTIAL yang dapat di-rollback")
            if status[1] is not None: raise ValueError("Batch sudah pernah direvert")
            revert_batch = "REVERT_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6].upper()
            conn.execute("""INSERT INTO pengembalian_progress_import_batch
                (import_batch_id,source_filename,source_file_hash,status,total_rows,valid_rows,
                 berhasil_rows,total_tukin,total_uang_makan,total_debit,nominal_berhasil,
                 metadata_json,imported_by,import_mode,periode_id)
                SELECT ?, 'REVERT ' || coalesce(any_value(source_filename),any_value(import_batch_id)),
                    sha256('REVERT|' || any_value(import_batch_id) || '|' || ?), 'COMMITTED',
                    count(*),count(*),count(*),sum(nominal_debit_tukin),sum(nominal_debit_uang_makan),
                    sum(nominal_debit_total),sum(nominal_berhasil),?, 'system','REVERT_BATCH',max(periode_id)
                FROM pengembalian_progress_transaction WHERE import_batch_id=? AND coalesce(is_active,true)
                AND status_debit IN ('BERHASIL','REVERSAL')""",
                [revert_batch,revert_batch,json.dumps({"reverts_batch_id":batch_id}),batch_id])
            conn.execute("""INSERT INTO pengembalian_progress_transaction
                (transaction_id,fingerprint,import_batch_id,obligation_id,nip,nama_sdm,tahun_sp2d,provinsi,periode_id,
                 nama_bank_original,nama_bank_normalized,periode_debit,tanggal_debit,komponen_debit,
                 nominal_debit_tukin,nominal_debit_uang_makan,nominal_debit_total,status_debit,
                 keterangan_gagal,source_filename,source_row_number,validation_flags,raw_data,created_by,
                 is_active,original_transaction_id,correction_type,tahap,nomor_rekening,nominal_diajukan,
                 nominal_berhasil,ntpn,keterangan,source_sheet)
                SELECT uuid()::VARCHAR,sha256('REVERT|' || ? || '|' || transaction_id),?,obligation_id,nip,nama_sdm,
                    tahun_sp2d,provinsi,periode_id,nama_bank_original,nama_bank_normalized,
                    'Revert ' || coalesce(periode_debit,''),current_date,komponen_debit,
                    nominal_debit_tukin,nominal_debit_uang_makan,nominal_debit_total,
                    CASE WHEN status_debit='BERHASIL' THEN 'REVERSAL' ELSE 'BERHASIL' END,
                    'Revert batch ' || ?,source_filename,source_row_number,'[\"REVERT_BATCH\"]',raw_data,
                    'system',true,CASE WHEN status_debit='BERHASIL' THEN transaction_id ELSE NULL END,
                    'REVERT_BATCH',tahap,nomor_rekening,nominal_diajukan,nominal_berhasil,ntpn,
                    'Reversal audit untuk batch ' || ?,source_sheet
                FROM pengembalian_progress_transaction WHERE import_batch_id=? AND coalesce(is_active,true)
                AND status_debit IN ('BERHASIL','REVERSAL')""",
                [revert_batch,revert_batch,batch_id,batch_id,batch_id])
            affected=conn.execute("SELECT count(*) FROM pengembalian_progress_transaction WHERE import_batch_id=?",[revert_batch]).fetchone()[0]
            conn.execute("UPDATE pengembalian_progress_import_batch SET reverted_by_batch_id=?,reverted_at=now() WHERE import_batch_id=?",[revert_batch,batch_id])
            conn.execute("COMMIT")
            return {"status":"ok","status_batch":"REVERTED","import_batch_id":batch_id,
                    "revert_batch_id":revert_batch,"reversal_transactions":int(affected),
                    "summary":self.progress(limit=1)["summary"]}
        except Exception:
            conn.execute("ROLLBACK");raise
        finally: conn.close()

    def validation_result_xlsx(self,batch_id):
        conn=self.connect()
        try: frame=conn.execute("SELECT * FROM pengembalian_progress_staging WHERE import_batch_id=? ORDER BY source_row_number",[batch_id]).fetchdf()
        finally: conn.close()
        if frame.empty: raise ValueError("Hasil validasi batch tidak ditemukan")
        frame["ERROR_MESSAGE"]=frame["validation_messages"]
        frame["WARNING_MESSAGE"]=frame["warning_messages"]
        frame["MATCHING_STATUS"]=frame["matching_status"]
        output=BytesIO()
        with pd.ExcelWriter(output,engine="openpyxl") as writer:
            for status in ("VALID","WARNING","INVALID","DUPLICATE","NEEDS_REVIEW"):
                scoped=frame[frame["validation_status"]==status].copy()
                scoped.to_excel(writer,sheet_name=status,index=False)
                ws=writer.book[status];ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
        return output.getvalue()

    def _resolve_scope(self, filters=None):
        """Resolve the default active Master period without hiding explicit consolidation."""
        filters = dict(filters or {})
        requested = filters.get("periode_id")
        consolidate = bool(filters.pop("all_periods", False)) or str(requested or "").upper() in {
            "__ALL__", "ALL", "SEMUA"
        }
        if consolidate:
            filters.pop("periode_id", None)
            return filters, {"periode_id": None, "scope_label": "Konsolidasi Semua Periode",
                             "is_consolidated": True}
        if requested in (None, ""):
            conn = self.connect()
            try:
                row = conn.execute("""SELECT periode_id FROM pengembalian_period
                    WHERE coalesce(is_active,false)=true LIMIT 1""").fetchone()
            finally:
                conn.close()
            if row:
                filters["periode_id"] = row[0]
        resolved = filters.get("periode_id")
        return filters, {"periode_id": resolved,
                         "scope_label": str(resolved or "Konsolidasi Semua Periode"),
                         "is_consolidated": resolved in (None, "")}

    @staticmethod
    def _validate_stage_filters(filters):
        mode = str(filters.get("stage_mode") or ("single" if filters.get("tahap") not in (None, "") else "all")).lower()
        if mode not in {"single", "cumulative", "all"}:
            raise ValueError("stage_mode harus single, cumulative, atau all")
        stage = filters.get("tahap")
        if mode in {"single", "cumulative"}:
            try:
                stage = int(stage)
            except (TypeError, ValueError):
                raise ValueError("tahap wajib untuk stage_mode single/cumulative")
            if stage <= 0:
                raise ValueError("tahap harus lebih dari 0")
            filters["tahap"] = stage
        else:
            filters.pop("tahap", None)
        filters["stage_mode"] = mode
        return filters

    def _progress_sql(self, filters=None):
        filters, scope = self._resolve_scope(filters)
        filters = self._validate_stage_filters(filters)
        obligation_table = self.sync_obligations()
        ow, op, tw, tp = [], [], ["coalesce(t.is_active,true)",
                                  "b.status IN ('COMMITTED','PARTIAL')"], []
        for key, column in (("tahun_sp2d","o.tahun_sp2d"),("provinsi","o.provinsi"),
                            ("periode_id","o.periode_id"),("nip","o.nip")):
            if filters.get(key) not in (None,""):
                if key in {"provinsi", "nip"}:
                    ow.append(f"{column} ILIKE ?"); op.append(f"%{filters[key]}%")
                else:
                    ow.append(f"{column}=?"); op.append(filters[key])
        # Current final metadata narrows the population only; EXISTS avoids multiplying obligations.
        for key, column in (("kabupaten_kota", "kabupaten_kota"), ("batch_bpk", "batch")):
            if filters.get(key) not in (None, ""):
                ow.append(f"EXISTS (SELECT 1 FROM pengembalian_final f WHERE {_final_metadata_match()} "
                          f"AND f.{column}=?)")
                op.append(filters[key])
        if filters.get("tenor_bulan") not in (None, ""):
            ow.append("""EXISTS (
                SELECT 1 FROM pengembalian_progress_bulanan monthly
                WHERE monthly.nip=o.nip AND monthly.tenor_bulan=?
            )""")
            op.append(int(filters["tenor_bulan"]))
        search = filters.get("search")
        if search: ow.append("(o.nip ILIKE ? OR o.nama_sdm ILIKE ?)"); op += [f"%{search}%",f"%{search}%"]
        component = _component(filters.get("komponen") or filters.get("komponen_debit"))
        # Bank is payroll/master-bank metadata, never the bank recorded on a debit event.
        for key in ("nama_bank", "bank"):
            if filters.get(key) not in (None, ""):
                ow.append(f"EXISTS (SELECT 1 FROM pengembalian_final f WHERE {_final_metadata_match()} "
                          f"AND {_master_bank_sql(_master_bank_value())}=?)")
                op.append(normalize_bank(filters[key]))
        for key,column in (("periode_debit","t.periode_debit"),("bulan_debit","t.bulan_debit"),
                           ("tahun_debit","t.tahun_debit"),("status_debit","t.status_debit"),
                           ("status","t.status_debit"),("import_batch_id","t.import_batch_id"),
                           ("batch_id","t.import_batch_id"),("tanggal_proses","t.tanggal_debit")):
            if filters.get(key) not in (None,""):
                tw.append(f"{column}=?")
                tp.append(normalize_bank(filters[key]) if key in {"nama_bank", "bank"} else filters[key])
        if component:
            tw.append("t.komponen_debit=?"); tp.append(component)
        if filters["stage_mode"] == "single":
            tw.append("t.tahap=?"); tp.append(filters["tahap"])
        elif filters["stage_mode"] == "cumulative":
            tw.append("t.tahap<=?"); tp.append(filters["tahap"])
        tx_where = " WHERE " + " AND ".join(tw) if tw else ""
        obligation_where = " WHERE " + " AND ".join(ow) if ow else ""
        tukin_initial = "coalesce(o.awal_tukin,0)" if component != "UANG_MAKAN" else "0"
        um_initial = "coalesce(o.awal_uang_makan,0)" if component != "TUKIN" else "0"
        tukin_final = "coalesce(o.final_tukin,0)" if component != "UANG_MAKAN" else "0"
        um_final = "coalesce(o.final_uang_makan,0)" if component != "TUKIN" else "0"
        sql = f"""WITH obligation_scope AS (
            SELECT o.* EXCLUDE (awal_tukin,awal_uang_makan,awal_total,final_tukin,final_uang_makan,final_total),
              {tukin_initial} awal_tukin,{um_initial} awal_uang_makan,
              {tukin_initial}+{um_initial} awal_total,
              {tukin_final} final_tukin,{um_final} final_uang_makan,
              {tukin_final}+{um_final} final_total
            FROM {obligation_table} o{obligation_where}),
          tx AS (SELECT t.* FROM pengembalian_progress_transaction t
            JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id{tx_where}), agg AS (
            SELECT obligation_id,
              sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_tukin WHEN status_debit='REVERSAL' THEN -nominal_debit_tukin ELSE 0 END) berhasil_tukin,
              sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_uang_makan WHEN status_debit='REVERSAL' THEN -nominal_debit_uang_makan ELSE 0 END) berhasil_um,
              sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) nominal_gagal,
              sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) nominal_reversal,
              count(*) FILTER(status_debit='BERHASIL') transaksi_berhasil,
              count(*) FILTER(status_debit='GAGAL') transaksi_gagal,
              arg_max(nama_bank_normalized,coalesce(tanggal_debit,created_at::DATE)) bank_terakhir,
              arg_max(periode_debit,coalesce(tanggal_debit,created_at::DATE)) periode_terakhir,
              max(tanggal_debit) tanggal_debit_terakhir,max(tanggal_surat) tanggal_surat_terakhir,
              arg_max(status_debit,coalesce(tanggal_debit,created_at::DATE)) status_debit_terakhir,
              arg_max(nominal_debit_total,coalesce(tanggal_debit,created_at::DATE)) nominal_debit_terakhir,
              max(tahap) tahap_terakhir
            FROM tx GROUP BY obligation_id), base AS (
            SELECT o.*,coalesce(a.berhasil_tukin,0) sudah_debit_tukin,coalesce(a.berhasil_um,0) sudah_debit_uang_makan,
              coalesce(a.nominal_gagal,0) nominal_debit_gagal,coalesce(a.transaksi_berhasil,0) jumlah_transaksi_berhasil,
              coalesce(a.transaksi_gagal,0) jumlah_transaksi_gagal,a.bank_terakhir,a.periode_terakhir,a.tanggal_debit_terakhir,
              a.tanggal_surat_terakhir,a.status_debit_terakhir,a.nominal_debit_terakhir,
              coalesce(a.nominal_reversal,0) nominal_reversal,a.tahap_terakhir
            FROM obligation_scope o LEFT JOIN agg a ON a.obligation_id=o.obligation_id), calc AS (
            SELECT *,greatest(final_tukin-sudah_debit_tukin,0) sisa_tukin,
              greatest(final_uang_makan-sudah_debit_uang_makan,0) sisa_uang_makan,
              sudah_debit_tukin+sudah_debit_uang_makan total_sudah_dikembalikan,
              greatest(final_tukin-sudah_debit_tukin,0)+greatest(final_uang_makan-sudah_debit_uang_makan,0) total_sisa_piutang,
              greatest(sudah_debit_tukin-final_tukin,0)+greatest(sudah_debit_uang_makan-final_uang_makan,0) kelebihan_bayar,
              greatest(sudah_debit_tukin-final_tukin,0)+greatest(sudah_debit_uang_makan-final_uang_makan,0) kelebihan_bayar_komponen
            FROM base) SELECT *,
              CASE WHEN sudah_debit_tukin>final_tukin THEN 'OVERPAYMENT' WHEN sudah_debit_tukin=final_tukin THEN 'LUNAS' WHEN sudah_debit_tukin>0 THEN 'PARSIAL' ELSE 'BELUM ADA PENGEMBALIAN' END status_tukin,
              CASE WHEN sudah_debit_uang_makan>final_uang_makan THEN 'OVERPAYMENT' WHEN sudah_debit_uang_makan=final_uang_makan THEN 'LUNAS' WHEN sudah_debit_uang_makan>0 THEN 'PARSIAL' ELSE 'BELUM ADA PENGEMBALIAN' END status_uang_makan,
              CASE WHEN kelebihan_bayar>0 THEN 'OVERPAYMENT' WHEN total_sisa_piutang=0 THEN 'LUNAS'
              WHEN total_sudah_dikembalikan>0 THEN 'PARSIAL' ELSE 'BELUM ADA PENGEMBALIAN' END status_progress,
              CASE WHEN final_total>0 THEN least(greatest(total_sudah_dikembalikan/final_total*100,0),100) ELSE 0 END progress_percentage,
              CASE WHEN final_total>0 THEN total_sudah_dikembalikan/final_total*100 ELSE 0 END actual_progress_percentage,
              final_total-awal_total penyesuaian
            FROM calc"""
        return sql, op + tp, scope

    def filter_options(self, filters=None):
        """Return compact, database-derived values for the operational filters."""
        filters = dict(filters or {})
        option_filters = dict(filters)
        option_filters.pop("tahap", None)
        option_filters.pop("stage_mode", None)
        sql, params, scope = self._progress_sql(option_filters)
        conn = self.connect()
        try:
            years = [int(row[0]) for row in conn.execute(
                f"SELECT DISTINCT tahun_sp2d FROM ({sql}) q ORDER BY tahun_sp2d", params).fetchall()]
            provinces = [row[0] for row in conn.execute(
                f"SELECT DISTINCT provinsi FROM ({sql}) q WHERE provinsi IS NOT NULL AND trim(provinsi)<>'' ORDER BY provinsi", params).fetchall()]
            metadata_join = f"FROM ({sql}) q JOIN pengembalian_final f ON {_final_metadata_match('q')}"
            banks = [row[0] for row in conn.execute(
                f"""SELECT DISTINCT {_master_bank_sql(_master_bank_value())} {metadata_join}
                    WHERE trim({_master_bank_value()})<>'' ORDER BY 1""", params).fetchall()]
            cities = [row[0] for row in conn.execute(
                f"""SELECT DISTINCT f.kabupaten_kota {metadata_join}
                    WHERE f.kabupaten_kota IS NOT NULL AND trim(f.kabupaten_kota)<>'' ORDER BY 1""", params).fetchall()]
            bpk_batches = [row[0] for row in conn.execute(
                f"""SELECT DISTINCT f.batch {metadata_join}
                    WHERE f.batch IS NOT NULL AND trim(f.batch)<>'' ORDER BY 1""", params).fetchall()]
            components = [row[0] for row in conn.execute(
                f"""SELECT component FROM (SELECT 'TUKIN' component, sum(final_tukin) nominal FROM ({sql}) q
                    UNION ALL SELECT 'UANG_MAKAN', sum(final_uang_makan) FROM ({sql}) q)
                    WHERE coalesce(nominal,0)<>0 ORDER BY component""", params + params).fetchall()]
            stages = [int(row[0]) for row in conn.execute(f"""SELECT DISTINCT t.tahap
                FROM pengembalian_progress_transaction t
                JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id
                JOIN ({sql}) q ON q.obligation_id=t.obligation_id
                WHERE coalesce(t.is_active,true) AND b.status IN ('COMMITTED','PARTIAL')
                    AND t.tahap IS NOT NULL ORDER BY t.tahap""", params).fetchall()]
            return {"status": "ok", "scope": scope, "options": {
                "tahun_sp2d": years, "bank": banks, "provinsi": provinces,
                "kabupaten_kota": cities, "komponen": components, "tahap": stages,
                "batch_bpk": bpk_batches,
            }}
        finally:
            conn.close()

    def progress(self, filters=None, limit=50, offset=0, cursor=None):
        sql, params, scope = self._progress_sql(filters)
        status = (filters or {}).get("status_progress")
        wrapped = f"SELECT q.*, q.obligation_id AS record_id FROM ({sql}) q"
        all_params = list(params)
        if status:
            wrapped += " WHERE status_progress=?"
            all_params.append(status)
        conn = self.connect()
        try:
            total = conn.execute(f"SELECT count(*) FROM ({wrapped}) z",all_params).fetchone()[0]
            summary = conn.execute(f"""SELECT count(*),sum(awal_tukin),sum(awal_uang_makan),sum(awal_total),
                sum(final_tukin),sum(final_uang_makan),sum(final_total),sum(penyesuaian),
                sum(sudah_debit_tukin),sum(sudah_debit_uang_makan),sum(total_sudah_dikembalikan),sum(nominal_debit_gagal),
                sum(nominal_reversal),sum(sisa_tukin),sum(sisa_uang_makan),sum(total_sisa_piutang),sum(kelebihan_bayar),
                count(*) FILTER(status_progress='LUNAS'),count(*) FILTER(status_progress='PARSIAL'),
                count(*) FILTER(status_progress='BELUM ADA PENGEMBALIAN'),count(*) FILTER(status_progress='OVERPAYMENT'),
                sum(jumlah_transaksi_berhasil),sum(jumlah_transaksi_gagal),max(tahap_terakhir)
                FROM ({wrapped}) s""",all_params).fetchone()
            page_sql, page_params = wrapped, list(all_params)
            decoded = _decode_cursor(cursor)
            if decoded:
                page_sql += " AND" if status else " WHERE"
                page_sql += " (nip > ? OR (nip = ? AND record_id > ?))"
                page_params += [decoded[0], decoded[0], decoded[1]]
                page_suffix = " LIMIT ?"
                page_params.append(limit + 1)
            else:
                page_suffix = " LIMIT ? OFFSET ?"
                page_params += [limit + 1, offset]
            frame = conn.execute(page_sql+" ORDER BY nip,record_id"+page_suffix, page_params).fetchdf()
            names=["total_sdm","awal_tukin","awal_uang_makan","total_awal","kewajiban_tukin",
                   "kewajiban_uang_makan","total_kewajiban","penyesuaian","berhasil_tukin",
                   "berhasil_uang_makan","total_berhasil","total_gagal","total_reversal",
                   "sisa_tukin","sisa_uang_makan","total_sisa","overpayment","sdm_lunas",
                   "sdm_parsial","sdm_belum","sdm_overpayment","transaksi_berhasil",
                   "transaksi_gagal","tahap_terakhir_committed"]
            integer_names={"total_sdm","sdm_lunas","sdm_parsial","sdm_belum","sdm_overpayment",
                           "transaksi_berhasil","transaksi_gagal","tahap_terakhir_committed"}
            sm={k:int(v or 0) if k in integer_names else float(v or 0) for k,v in zip(names,summary)}
            actual=(sm["total_berhasil"]/sm["total_kewajiban"]*100) if sm["total_kewajiban"] else 0
            sm["actual_progress_percentage"]=actual
            sm["progress_percentage"]=min(max(actual,0),100)
            rows = json.loads(frame.to_json(orient="records",date_format="iso"))
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = _encode_cursor(rows[-1]["nip"], rows[-1]["record_id"]) if has_more else None
            return {"status":"ok","rows":rows,"count":total,"total":total,"limit":limit,
                    "offset":offset if not decoded else 0,"cursor":cursor,"next_cursor":next_cursor,
                    "has_more": has_more,"summary":sm,"scope":scope}
        finally: conn.close()

    def wide_progress(self, filters=None, limit=50, offset=0):
        """Return one UI row per Master period + NIP with dynamic year/stage cells."""
        filters = dict(filters or {})
        sql, params, scope = self._progress_sql(filters)
        if filters.get("status_progress"):
            sql = f"SELECT * FROM ({sql}) wide_status WHERE status_progress=?"
            params = list(params) + [filters["status_progress"]]
        conn = self.connect()
        try:
            total = conn.execute(f"SELECT count(*) FROM (SELECT DISTINCT periode_id,nip FROM ({sql}) q)", params).fetchone()[0]
            keys = conn.execute(f"SELECT DISTINCT periode_id,nip FROM ({sql}) q ORDER BY nip,periode_id LIMIT ? OFFSET ?", list(params)+[limit,offset]).fetchall()
            summary = self.progress(filters, limit=1)["summary"]
            if not keys:
                return {"status":"ok","rows":[],"total":int(total),"limit":limit,"offset":offset,
                        "summary":summary,"stages":[],"available_stages":[],"years":[],"scope":scope}
            predicate = " OR ".join("(periode_id=? AND nip=?)" for _ in keys)
            key_params = [value for key in keys for value in key]
            obligations = conn.execute(f"SELECT * FROM ({sql}) q WHERE {predicate} ORDER BY nip,tahun_sp2d",list(params)+key_params).fetchdf()
            obligation_ids = obligations["obligation_id"].astype(str).tolist()
            transaction_sql, transaction_params = self._scoped_transaction_sql(filters)
            placeholders = ",".join("?" for _ in obligation_ids)
            tx = conn.execute(f"""SELECT obligation_id,komponen_debit,tahap,tahun_sp2d,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) amount,
                count(DISTINCT ntpn) FILTER(status_debit='BERHASIL' AND ntpn IS NOT NULL) ntpn_count
                FROM ({transaction_sql}) t WHERE obligation_id IN ({placeholders}) AND tahap IS NOT NULL
                GROUP BY obligation_id,komponen_debit,tahap,tahun_sp2d""",transaction_params+obligation_ids).fetchall()
            availability_filters = {key:value for key,value in filters.items() if key not in {"tahap","stage_mode"}}
            availability_sql, availability_params = self._scoped_transaction_sql(availability_filters)
            available_stages = [int(row[0]) for row in conn.execute(
                f"SELECT DISTINCT tahap FROM ({availability_sql}) available WHERE tahap IS NOT NULL ORDER BY tahap",
                availability_params,
            ).fetchall()]
        finally:
            conn.close()
        stage_lookup={(str(r[0]),str(r[1]),int(r[2]),int(r[3])):{"amount":float(r[4] or 0),"ntpn_count":int(r[5] or 0)} for r in tx}
        # Render only stages that actually exist in the normalized ledger.
        # This keeps the wide view database-driven and avoids invented columns.
        observed_stages = {key[2] for key in stage_lookup if key[2] > 0}
        stages = sorted(observed_stages)
        years=sorted({int(value) for value in obligations["tahun_sp2d"].tolist()})
        grouped={}
        for record in json.loads(obligations.to_json(orient="records",date_format="iso")):
            group_key=(record.get("periode_id"),record["nip"])
            item=grouped.setdefault(group_key,{"periode_id":record.get("periode_id"),"nip":record["nip"],
                "nama_sdm":record.get("nama_sdm"),"provinsi":record.get("provinsi"),
                "initials":{"TUKIN":{},"UANG_MAKAN":{}},"finals":{"TUKIN":{},"UANG_MAKAN":{}},
                "stages":{"TUKIN":{},"UANG_MAKAN":{}},"total_awal":0,"total_kewajiban":0,
                "total_realisasi":0,"total_sisa":0,"overpayment":0})
            year=int(record["tahun_sp2d"]);obligation_id=str(record["obligation_id"])
            item["initials"]["TUKIN"][str(year)]=float(record.get("awal_tukin") or 0)
            item["initials"]["UANG_MAKAN"][str(year)]=float(record.get("awal_uang_makan") or 0)
            item["finals"]["TUKIN"][str(year)]=float(record.get("final_tukin") or 0)
            item["finals"]["UANG_MAKAN"][str(year)]=float(record.get("final_uang_makan") or 0)
            item["total_awal"]+=float(record.get("awal_total") or 0)
            item["total_kewajiban"]+=float(record.get("final_total") or 0)
            item["total_realisasi"]+=float(record.get("total_sudah_dikembalikan") or 0)
            item["total_sisa"]+=float(record.get("total_sisa_piutang") or 0)
            item["overpayment"]+=float(record.get("kelebihan_bayar") or 0)
            for component in COMPONENTS:
                for stage in stages:
                    cell=stage_lookup.get((obligation_id,component,stage,year))
                    if cell:
                        item["stages"][component].setdefault(str(stage),{})[str(year)]=cell
        for item in grouped.values():
            def component_totals(component):
                obligation=sum(item["finals"][component].values())
                realized=sum(cell["amount"] for stage in item["stages"][component].values() for cell in stage.values())
                return obligation,realized
            tukin_ob,tukin_paid=component_totals("TUKIN");um_ob,um_paid=component_totals("UANG_MAKAN")
            status=lambda ob,paid: "OVERPAYMENT" if paid>ob else "LUNAS" if paid==ob else "PARSIAL" if paid>0 else "BELUM ADA PENGEMBALIAN"
            item["status_tukin"]=status(tukin_ob,tukin_paid);item["status_uang_makan"]=status(um_ob,um_paid)
            item["status_akhir"]="OVERPAYMENT" if item["total_realisasi"]>item["total_kewajiban"] else "LUNAS" if item["total_sisa"]==0 else "PARSIAL" if item["total_realisasi"]>0 else "BELUM ADA PENGEMBALIAN"
            actual=(item["total_realisasi"]/item["total_kewajiban"]*100) if item["total_kewajiban"] else 0
            item["actual_progress_percentage"]=actual
            item["progress_percentage"]=min(max(actual,0),100)
        return {"status":"ok","rows":list(grouped.values()),"total":int(total),"limit":limit,"offset":offset,
                "summary":summary,"stages":stages,"available_stages":available_stages,"years":years,"scope":scope}

    def history(self, filters=None, limit=100, offset=0):
        filters=dict(filters or {}); where=[]; params=[]
        for key in ("nip","tahun_sp2d","nama_bank_normalized","periode_debit","status_debit","import_batch_id","tahap","komponen_debit"):
            value=filters.get("nama_bank" if key=="nama_bank_normalized" else key)
            if value not in (None,""): where.append(f"{key}=?");params.append(normalize_bank(value) if key=="nama_bank_normalized" else value)
        clause=" WHERE "+" AND ".join(where) if where else ""
        conn=self.connect()
        try:
            total=conn.execute("SELECT count(*) FROM pengembalian_progress_transaction"+clause,params).fetchone()[0]
            frame=conn.execute("SELECT * FROM pengembalian_progress_transaction"+clause+" ORDER BY coalesce(tanggal_debit,created_at::DATE) DESC,created_at DESC LIMIT ? OFFSET ?",params+[limit,offset]).fetchdf()
            return {"status":"ok","rows":json.loads(frame.to_json(orient="records",date_format="iso")),"total":total,"limit":limit,"offset":offset}
        finally: conn.close()

    def transactions(self, filters=None, limit=100, offset=0):
        """Committed transaction ledger constrained to the canonical dashboard scope."""
        sql, params = self._scoped_transaction_sql(filters)
        conn = self.connect()
        try:
            total = conn.execute(f"SELECT count(*) FROM ({sql}) committed_scope", params).fetchone()[0]
            frame = conn.execute(f"""SELECT * FROM ({sql}) committed_scope
                ORDER BY coalesce(tanggal_debit,created_at::DATE) DESC,created_at DESC
                LIMIT ? OFFSET ?""", list(params)+[limit,offset]).fetchdf()
            return {"status":"ok","rows":json.loads(frame.to_json(orient="records",date_format="iso")),
                    "total":int(total),"limit":limit,"offset":offset}
        finally:
            conn.close()

    def _scoped_transaction_sql(self, filters=None):
        """Return active transactions constrained to the same obligation/filter scope as Progress SDM."""
        filters = dict(filters or {})
        progress_sql, params, _ = self._progress_sql(filters)
        scoped = f"SELECT * FROM ({progress_sql}) progress_scope"
        if filters.get("status_progress"):
            scoped += " WHERE status_progress=?"
            params = list(params) + [filters["status_progress"]]
        transaction_where = ["coalesce(t.is_active,true)", "b.status IN ('COMMITTED','PARTIAL')"]
        transaction_params = []
        for key, column in (("nama_bank", "t.nama_bank_normalized"), ("bank", "t.nama_bank_normalized"),
                            ("periode_debit", "t.periode_debit"),
                            ("bulan_debit", "t.bulan_debit"), ("tahun_debit", "t.tahun_debit"),
                            ("komponen_debit", "t.komponen_debit"), ("status_debit", "t.status_debit"),
                            ("status", "t.status_debit"), ("import_batch_id", "t.import_batch_id"),
                            ("batch_id", "t.import_batch_id"), ("tanggal_proses", "t.tanggal_debit")):
            value = filters.get(key)
            if value not in (None, ""):
                transaction_where.append(f"{column}=?")
                transaction_params.append(normalize_bank(value) if key in {"nama_bank", "bank"} else value)
        mode = str(filters.get("stage_mode") or ("single" if filters.get("tahap") not in (None, "") else "all")).lower()
        if mode == "single":
            transaction_where.append("t.tahap=?"); transaction_params.append(int(filters["tahap"]))
        elif mode == "cumulative":
            transaction_where.append("t.tahap<=?"); transaction_params.append(int(filters["tahap"]))
        sql = f"""WITH scoped AS ({scoped})
            SELECT t.* FROM pengembalian_progress_transaction t
            JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id
            JOIN scoped s ON s.obligation_id=t.obligation_id
            WHERE {' AND '.join(transaction_where)}"""
        return sql, list(params) + transaction_params

    def recaps(self, filters=None):
        sql,params,scope=self._progress_sql(filters)
        if (filters or {}).get("status_progress"):
            sql=f"SELECT * FROM ({sql}) recap_scope WHERE status_progress=?"
            params=list(params)+[filters["status_progress"]]
        conn=self.connect()
        dimensions={"sp2d":["tahun_sp2d"],"provinsi":["provinsi"]}
        result={}
        try:
            for name,dims in dimensions.items():
                cols=",".join(dims); group=",".join(str(i+1) for i in range(len(dims)))
                q=f"""SELECT {cols},count(DISTINCT periode_id || '|' || nip) jumlah_sdm,
                    sum(awal_tukin) awal_tukin,sum(awal_uang_makan) awal_uang_makan,
                    sum(awal_total) awal,sum(final_tukin) kewajiban_tukin,
                    sum(final_uang_makan) kewajiban_uang_makan,sum(final_total) final,
                    sum(penyesuaian) penyesuaian,
                    sum(total_sudah_dikembalikan)+sum(nominal_reversal) berhasil,
                    sum(nominal_debit_gagal) gagal,sum(nominal_reversal) reversal,
                    sum(total_sudah_dikembalikan) netto,sum(total_sisa_piutang) sisa,
                    sum(kelebihan_bayar) overpayment,
                    count(*) FILTER(status_progress='LUNAS') sdm_lunas,
                    count(*) FILTER(status_progress='PARSIAL') sdm_parsial,
                    count(*) FILTER(status_progress='BELUM ADA PENGEMBALIAN') sdm_belum,
                    count(*) FILTER(status_progress='OVERPAYMENT') sdm_overpayment,
                    max(tahap_terakhir) tahap_terakhir_committed,
                    CASE WHEN sum(final_total)>0 THEN least(greatest(sum(total_sudah_dikembalikan)/sum(final_total)*100,0),100) ELSE 0 END progress_percentage,
                    CASE WHEN sum(final_total)>0 THEN sum(total_sudah_dikembalikan)/sum(final_total)*100 ELSE 0 END actual_progress_percentage
                    FROM ({sql}) q GROUP BY {group} ORDER BY {group}"""
                frame=conn.execute(q,params).fetchdf();result[name]=json.loads(frame.to_json(orient="records",date_format="iso"))
            transaction_sql, transaction_params = self._scoped_transaction_sql(filters)
            period=conn.execute(f"""SELECT periode_debit,min(tahun_debit) tahun_debit,min(bulan_debit) bulan_debit,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_tukin WHEN status_debit='REVERSAL' THEN -nominal_debit_tukin ELSE 0 END) berhasil_tukin,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_uang_makan WHEN status_debit='REVERSAL' THEN -nominal_debit_uang_makan ELSE 0 END) berhasil_uang_makan,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) total_berhasil,
                sum(CASE WHEN status_debit='GAGAL' THEN nominal_debit_total ELSE 0 END) total_gagal
                FROM ({transaction_sql}) scoped_transactions
                GROUP BY periode_debit ORDER BY min(tahun_debit),min(bulan_debit),periode_debit""",transaction_params).fetchdf()
            cumulative=0; rows=json.loads(period.to_json(orient="records"))
            obligation_total=self.progress(filters,1,0)["summary"]["total_kewajiban"]
            for row in rows: cumulative+=row["total_berhasil"] or 0;row["akumulasi_berhasil"]=cumulative;row["sisa_piutang"]=max(obligation_total-cumulative,0)
            result["periode"]=rows
            stage_year=conn.execute(f"""SELECT tahap,tahun_sp2d,
                count(DISTINCT nip) jumlah_sdm,sum(coalesce(nominal_diajukan,0)) diajukan,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total ELSE 0 END) berhasil,
                sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) gagal,
                sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) reversal,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) netto
                FROM ({transaction_sql}) scoped_transactions WHERE tahap IS NOT NULL
                GROUP BY tahap,tahun_sp2d ORDER BY tahap,tahun_sp2d""",transaction_params).fetchdf()
            stage_rows=json.loads(stage_year.to_json(orient="records"))
            years=sorted({int(row["tahun_sp2d"]) for row in stage_rows})
            by_stage={}
            for row in stage_rows:
                item=by_stage.setdefault(int(row["tahap"]),{"tahap":int(row["tahap"]),"total":0})
                item[str(int(row["tahun_sp2d"]))]=float(row["netto"] or 0);item["total"]+=float(row["netto"] or 0)
            result["tahap_sp2d"]={"years":years,"rows":list(by_stage.values())}
            result["detail_tahap"]=stage_rows
            for key, groups in (("tahap_bank_sp2d", "tahap,tahun_sp2d,nama_bank_normalized"),
                                ("tahap_provinsi_sp2d", "tahap,tahun_sp2d,provinsi"),
                                ("bank", "nama_bank_normalized,tahun_sp2d")):
                frame=conn.execute(f"""SELECT {groups},count(DISTINCT nip) jumlah_sdm,
                    sum(coalesce(nominal_diajukan,0)) diajukan,
                    sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total ELSE 0 END) berhasil,
                    sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) gagal,
                    sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) reversal,
                    sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) netto
                    FROM ({transaction_sql}) scoped_transactions GROUP BY {groups} ORDER BY {groups}""",
                    transaction_params).fetchdf()
                result[key]=json.loads(frame.to_json(orient="records",date_format="iso"))
            return {"status":"ok","scope":scope,"available_stages":sorted({int(row["tahap"]) for row in stage_rows}),**result}
        finally: conn.close()

    def kpi_summary(self, filters=None):
        """Canonical KPI response grouped by SP2D year."""
        recap = self.recaps(filters)
        return {"status":"ok","scope":recap.get("scope",{}),
                "available_stages":recap.get("available_stages",[]),
                "rows":recap.get("sp2d",[])}

    def operational_dashboard(self, filters=None):
        """One SQL aggregation over the canonical obligation/ledger calculation."""
        filters = dict(filters or {})
        # A stage selects SDM with activity in that stage, but their KPI remains cumulative.
        stage = filters.pop("tahap", None)
        stage_mode = filters.pop("stage_mode", None)
        sql, params, scope = self._progress_sql(filters)
        if stage not in (None, ""):
            mode = str(stage_mode or "single").lower()
            operator = "<=" if mode == "cumulative" else "="
            # Stage labels in the operational dashboard represent the staged Tukin
            # payment workflow unless the caller explicitly selects another component.
            component = _component(filters.get("komponen") or filters.get("komponen_debit")) or "TUKIN"
            component_clause = " AND t.komponen_debit=?"
            sql = f"SELECT * FROM ({sql}) canonical WHERE EXISTS (SELECT 1 FROM pengembalian_progress_transaction t JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id WHERE t.obligation_id=canonical.obligation_id AND coalesce(t.is_active,true) AND b.status IN ('COMMITTED','PARTIAL'){component_clause} AND t.tahap {operator} ?)"
            params = list(params) + [component, int(stage)]
        conn = self.connect()
        try:
            row = conn.execute(f"""SELECT
                coalesce(sum(final_total),0), coalesce(sum(total_sudah_dikembalikan),0),
                coalesce(sum(total_sisa_piutang),0), coalesce(sum(kelebihan_bayar),0),
                count(*) FILTER (WHERE status_progress='LUNAS'),
                count(*) FILTER (WHERE status_progress='PARSIAL'),
                count(*) FILTER (WHERE status_progress='BELUM ADA PENGEMBALIAN'),
                count(*) FILTER (WHERE status_progress='OVERPAYMENT')
                FROM ({sql}) dashboard""", params).fetchone()
            names=("total_kewajiban","total_realisasi_netto","total_sisa","total_kelebihan_bayar",
                   "lunas","sebagian","belum","overpaid")
            return {"status":"ok","scope":scope,"kpi":{name:int(value or 0) for name,value in zip(names,row)}}
        finally:
            conn.close()

    def batches(self, filters=None, limit=100):
        filters, scope = self._resolve_scope(filters)
        where=[];params=[]
        if filters.get("periode_id") not in (None,""):
            where.append("periode_id=?");params.append(filters["periode_id"])
        if filters.get("batch_status") not in (None,""):
            where.append("status=?");params.append(filters["batch_status"])
        clause=" WHERE "+" AND ".join(where) if where else ""
        conn=self.connect()
        try:
            frame=conn.execute("SELECT * FROM pengembalian_progress_import_batch"+clause+
                               " ORDER BY imported_at DESC LIMIT ?",params+[limit]).fetchdf()
            return {"status":"ok","scope":scope,
                    "rows":json.loads(frame.to_json(orient="records",date_format="iso"))}
        finally: conn.close()

    def template_xlsx(self):
        columns=["NIP","Nama","Provinsi","Kab/Kota","Bank","Nomor Rekening","Tahun SP2D","Komponen","Tahap","Nominal Diajukan","Nominal Berhasil","Status","NTPN","Tanggal Proses","Alasan Gagal","Keterangan"]
        guide=[["Kolom","Petunjuk"],["NIP","Wajib; format TEXT dan harus cocok dengan Final Pengembalian."],["Tahun SP2D","Wajib; 4 digit dan harus cocok dengan Final Pengembalian."],["Komponen","TUKIN atau UANG_MAKAN."],["Tahap","Bilangan bulat bebas lebih dari 0; tidak dibatasi jumlah tahap."],["Nominal Diajukan","Angka non-negatif."],["Nominal Berhasil","Hanya dihitung bila Status BERHASIL."],["Status","BERHASIL, GAGAL, atau PENDING."],["NTPN","Melekat pada transaksi; satu tahap boleh memiliki beberapa baris/NTPN."],["Tanggal Proses","Gunakan tanggal Excel atau DD/MM/YYYY."],["Import","Setiap baris menambah ledger; tidak menimpa bank atau tahap sebelumnya."]]
        output=BytesIO()
        with pd.ExcelWriter(output,engine="openpyxl") as writer:
            pd.DataFrame(columns=columns).to_excel(writer,sheet_name="IMPORT_PROGRESS",index=False)
            pd.DataFrame(guide[1:],columns=guide[0]).to_excel(writer,sheet_name="PETUNJUK",index=False)
            for ws in writer.book.worksheets:
                ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
                for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=min(max(len(str(c.value or "")) for c in col)+2,50)
            writer.book["IMPORT_PROGRESS"].column_dimensions["A"].width=22
            from openpyxl.worksheet.datavalidation import DataValidation
            ws=writer.book["IMPORT_PROGRESS"]
            component_validation=DataValidation(type="list",formula1='"TUKIN,UANG_MAKAN"',allow_blank=False)
            status_validation=DataValidation(type="list",formula1='"BERHASIL,GAGAL,PENDING"',allow_blank=False)
            stage_validation=DataValidation(type="whole",operator="greaterThan",formula1="0",allow_blank=False)
            ws.add_data_validation(component_validation);component_validation.add("H2:H1048576")
            ws.add_data_validation(stage_validation);stage_validation.add("I2:I1048576")
            ws.add_data_validation(status_validation);status_validation.add("L2:L1048576")
        return output.getvalue()

    def export_xlsx(self, filters=None, official=False):
        """Build all sheets from one committed ledger snapshot and one scoped obligation result."""
        export_filters = dict(filters or {})
        if official:
            for key in ("tahap","stage_mode","nama_bank","bank","status_debit","status",
                        "import_batch_id","batch_id","tanggal_proses","periode_debit",
                        "bulan_debit","tahun_debit"):
                export_filters.pop(key, None)
            export_filters["stage_mode"] = "all"
        progress_sql, progress_params, scope = self._progress_sql(export_filters)
        if export_filters.get("status_progress"):
            progress_sql = f"SELECT * FROM ({progress_sql}) export_status WHERE status_progress=?"
            progress_params = list(progress_params) + [export_filters["status_progress"]]

        tx_where = ["coalesce(t.is_active,true)", "b.status IN ('COMMITTED','PARTIAL')"]
        tx_params = []
        for key,column in (("nama_bank","t.nama_bank_normalized"),("bank","t.nama_bank_normalized"),
                           ("status_debit","t.status_debit"),("status","t.status_debit"),
                           ("import_batch_id","t.import_batch_id"),("batch_id","t.import_batch_id"),
                           ("tanggal_proses","t.tanggal_debit"),("periode_debit","t.periode_debit"),
                           ("bulan_debit","t.bulan_debit"),("tahun_debit","t.tahun_debit")):
            value=export_filters.get(key)
            if value not in (None,""):
                tx_where.append(f"{column}=?")
                tx_params.append(normalize_bank(value) if key in {"nama_bank","bank"} else value)
        component=_component(export_filters.get("komponen") or export_filters.get("komponen_debit"))
        if component:
            tx_where.append("t.komponen_debit=?");tx_params.append(component)
        mode=str(export_filters.get("stage_mode") or ("single" if export_filters.get("tahap") else "all")).lower()
        if mode=="single": tx_where.append("t.tahap=?");tx_params.append(int(export_filters["tahap"]))
        elif mode=="cumulative": tx_where.append("t.tahap<=?");tx_params.append(int(export_filters["tahap"]))

        conn=self.connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute(f"CREATE TEMP TABLE export_progress AS {progress_sql}",progress_params)
            conn.execute(f"""CREATE TEMP TABLE export_transactions AS
                SELECT t.* FROM pengembalian_progress_transaction t
                JOIN pengembalian_progress_import_batch b ON b.import_batch_id=t.import_batch_id
                JOIN (SELECT DISTINCT obligation_id FROM export_progress) o ON o.obligation_id=t.obligation_id
                WHERE {' AND '.join(tx_where)}""",tx_params)
            kpi_sql="""SELECT tahun_sp2d,count(*) jumlah_sdm,sum(awal_total) awal,
                sum(final_total) final,sum(penyesuaian) penyesuaian,
                sum(total_sudah_dikembalikan)+sum(nominal_reversal) berhasil,
                sum(nominal_debit_gagal) gagal,sum(nominal_reversal) reversal,
                sum(total_sudah_dikembalikan) netto,sum(total_sisa_piutang) sisa,
                sum(kelebihan_bayar) overpayment,
                count(*) FILTER(status_progress='LUNAS') sdm_lunas,
                count(*) FILTER(status_progress='PARSIAL') sdm_parsial,
                count(*) FILTER(status_progress='BELUM ADA PENGEMBALIAN') sdm_belum,
                count(*) FILTER(status_progress='OVERPAYMENT') sdm_overpayment,
                max(tahap_terakhir) tahap_terakhir_committed,
                CASE WHEN sum(final_total)>0 THEN least(greatest(sum(total_sudah_dikembalikan)/sum(final_total)*100,0),100) ELSE 0 END progress_percentage,
                CASE WHEN sum(final_total)>0 THEN sum(total_sudah_dikembalikan)/sum(final_total)*100 ELSE 0 END actual_progress_percentage
                FROM export_progress GROUP BY tahun_sp2d ORDER BY tahun_sp2d"""
            kpi=conn.execute(kpi_sql).fetchdf()
            tx=conn.execute("SELECT * FROM export_transactions ORDER BY tahap,tahun_sp2d,nip,created_at").fetchdf()
            stage=conn.execute("""SELECT tahap,tahun_sp2d,count(DISTINCT nip) jumlah_sdm,
                sum(coalesce(nominal_diajukan,0)) diajukan,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total ELSE 0 END) berhasil,
                sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) gagal,
                sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) reversal,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) netto
                FROM export_transactions GROUP BY tahap,tahun_sp2d ORDER BY tahap,tahun_sp2d""").fetchdf()
            period_recap=conn.execute("""SELECT periode_debit,min(tahun_debit) tahun_debit,
                min(bulan_debit) bulan_debit,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total ELSE 0 END) berhasil,
                sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) gagal,
                sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) reversal,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total WHEN status_debit='REVERSAL' THEN -nominal_debit_total ELSE 0 END) netto
                FROM export_transactions GROUP BY periode_debit ORDER BY tahun_debit,bulan_debit,periode_debit""").fetchdf()
            province_recap=conn.execute("""SELECT provinsi,tahun_sp2d,count(*) jumlah_sdm,
                sum(awal_total) awal,sum(final_total) final,sum(total_sudah_dikembalikan) netto,
                sum(total_sisa_piutang) sisa FROM export_progress GROUP BY provinsi,tahun_sp2d
                ORDER BY provinsi,tahun_sp2d""").fetchdf()
            bank_recap=conn.execute("""SELECT nama_bank_normalized bank,tahun_sp2d,
                count(DISTINCT nip) jumlah_sdm,
                sum(CASE WHEN status_debit='BERHASIL' THEN nominal_debit_total ELSE 0 END) berhasil,
                sum(CASE WHEN status_debit='GAGAL' THEN coalesce(nominal_diajukan,nominal_debit_total,0) ELSE 0 END) gagal,
                sum(CASE WHEN status_debit='REVERSAL' THEN nominal_debit_total ELSE 0 END) reversal
                FROM export_transactions GROUP BY nama_bank_normalized,tahun_sp2d
                ORDER BY nama_bank_normalized,tahun_sp2d""").fetchdf()
            progress=conn.execute("SELECT * FROM export_progress ORDER BY tahun_sp2d,nip").fetchdf()
            period_id=scope.get("periode_id")
            import_where="status IN ('COMMITTED','PARTIAL')"
            import_params=[]
            if period_id:
                import_where+=" AND periode_id=?";import_params.append(period_id)
            imports=conn.execute(f"SELECT * FROM pengembalian_progress_import_batch WHERE {import_where} ORDER BY imported_at",import_params).fetchdf()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK");raise
        finally:
            conn.close()

        metadata=pd.DataFrame([
            {"KEY":"export_mode","VALUE":"LAPORAN_RESMI_TERKOMIT" if official else "TAMPILAN_SAAT_INI"},
            {"KEY":"periode_id","VALUE":scope.get("periode_id") or "SEMUA_PERIODE"},
            {"KEY":"scope","VALUE":scope.get("scope_label")},
            {"KEY":"filter","VALUE":json.dumps(export_filters,ensure_ascii=False,default=str)},
            {"KEY":"exported_at","VALUE":datetime.now().isoformat()},
        ])
        sheets={
            "RINGKASAN_KPI":kpi,
            "REKAP_SP2D":kpi[[column for column in ("tahun_sp2d","awal","final","penyesuaian","berhasil","gagal","reversal","netto","sisa","progress_percentage","actual_progress_percentage") if column in kpi]],
            "REKAP_TAHAP_SP2D":stage,
            "PROGRESS_SDM":progress,
            "TRANSAKSI_TERKOMIT":tx,
            "SISA_PIUTANG":progress[progress["total_sisa_piutang"]>0] if not progress.empty else progress,
            "DATA_LUNAS":progress[progress["status_progress"]=="LUNAS"] if not progress.empty else progress,
            "DEBIT_GAGAL":tx[tx["status_debit"]=="GAGAL"] if not tx.empty else tx,
            "OVERPAYMENT":progress[progress["status_progress"]=="OVERPAYMENT"] if not progress.empty else progress,
            "RIWAYAT_IMPORT":imports,
            "METADATA_EXPORT":metadata,
            # Backward-compatible aliases retained for existing operational workbooks.
            "SUMMARY":kpi,
            "HISTORY_DEBIT":tx,
            "REKAP_PROVINSI":province_recap,
            "REKAP_BANK":bank_recap,
            "REKAP_PERIODE":period_recap,
            "NEEDS_REVIEW":progress[progress["status_progress"]=="OVERPAYMENT"] if not progress.empty else progress,
            "MULTI_SP2D":progress[progress["status_sp2d"]=="MULTI_SP2D"] if not progress.empty else progress,
        }
        output=BytesIO()
        with pd.ExcelWriter(output,engine="openpyxl") as writer:
            for name,frame in sheets.items():
                frame.to_excel(writer,sheet_name=name,index=False)
                ws=writer.book[name];ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
                for index,column in enumerate(frame.columns,1):
                    sample=frame[column].head(200).astype(str).tolist() if len(frame) else []
                    ws.column_dimensions[ws.cell(1,index).column_letter].width=min(max([len(str(column))]+[len(str(x)) for x in sample])+2,45)
                    ws.cell(1,index).font=__import__('openpyxl').styles.Font(bold=True,color="FFFFFF")
                    ws.cell(1,index).fill=__import__('openpyxl').styles.PatternFill("solid",fgColor="1F4E78")
        return output.getvalue()
