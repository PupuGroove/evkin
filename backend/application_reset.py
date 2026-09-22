"""Explicit, backed-up operational reset. Never removes the SDM master."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from backend.security import require_api_key

CONFIRMATION = "RESET TOTAL TANPA MASTER SDM"
PRESERVED = {"master_data", "master_sdm", "master_unit_kerja", "master_jabatan", "master_skp_rules", "final_tukin_schema",
             "master_tukin", "skp_rule_config", "audit_log", "application_reset_audit"}
OPERATIONAL = {"raw_import", "hitung_harian", "rekap_sdm", "anomali", "bnba",
               "rekonsiliasi", "import_batch", "processing_jobs", "rounding_jobs",
               "rekap_pengembalian"}
PREFIXES = ("workflow_", "absensi_", "final_", "skp_", "tukin_", "pengembalian_", "generic_compare_")


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def preserve(name):
    return name in PRESERVED or name.startswith("sdm_") or name.startswith("schema_migration")


class ApplicationResetService:
    def __init__(self, db_path, jobs_path=None):
        self.db_path = Path(db_path).resolve()
        self.jobs_path = Path(jobs_path).resolve() if jobs_path else None

    def _inventory(self, conn):
        result = []
        for schema, name in conn.execute("""SELECT table_schema,table_name FROM information_schema.tables
                WHERE table_catalog=current_database() AND table_type='BASE TABLE'
                ORDER BY table_schema,table_name""").fetchall():
            table = f"{quote(schema)}.{quote(name)}"
            count, xor_hash, sum_hash = conn.execute(f"SELECT count(*),coalesce(bit_xor(hash(t)),0)::VARCHAR,coalesce(sum(hash(t)::HUGEINT),0)::VARCHAR FROM {table} t").fetchone()
            digest = f'{xor_hash}:{sum_hash}'
            action = "KEEP" if preserve(name) else "DELETE" if schema == "main" and (name in OPERATIONAL or name.startswith(PREFIXES)) else "UNKNOWN"
            result.append({"schema": schema, "table": name, "rows": count, "digest": digest, "action": action})
        return result

    def _blockers(self, conn, inventory):
        blockers = [f"Tabel belum dipetakan: {r['schema']}.{r['table']}" for r in inventory if r['action'] == 'UNKNOWN' and r['rows']]
        for item in inventory:
            if item['action'] != 'DELETE' or not item['rows']:
                continue
            name = item['table']
            columns = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?", [item['schema'], name]).fetchall()}
            for column in ('status', 'payment_status'):
                if column in columns and (name.startswith(('tukin_', 'pengembalian_')) or name == 'master_tukin'):
                    count = conn.execute(f"SELECT count(*) FROM {quote(name)} WHERE upper(trim({quote(column)}::VARCHAR)) IN ('LOCKED','HISTORICAL_LOCKED','CLOSED','ARCHIVED','PAID','TERKUNCI','SUDAH DIBAYAR','DIBAYARKAN')").fetchone()[0]
                    if count:
                        blockers.append(f"{name}: {count} data terkunci/sudah dibayar")
        if self.jobs_path and self.jobs_path.exists():
            with sqlite3.connect(str(self.jobs_path)) as jobs:
                if jobs.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
                    count = jobs.execute("SELECT count(*) FROM jobs WHERE lower(status) IN ('queued','pending','running')").fetchone()[0]
                    if count:
                        blockers.append(f"{count} proses backend masih aktif")
        return blockers

    def _plan(self, conn):
        inventory = self._inventory(conn)
        blockers = self._blockers(conn, inventory)
        token = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
        return {"status": "ok", "preview_token": token, "tables": inventory,
                "deleted_rows": sum(r['rows'] for r in inventory if r['action'] == 'DELETE'),
                "blockers": blockers, "can_reset": not blockers,
                "preserved_note": "Master SDM dan riwayat, aturan potongan SKP, audit sistem, riwayat job, backup dan file ekspor tetap disimpan."}

    def preview(self):
        if not self.db_path.is_file():
            raise ValueError("Database aplikasi tidak ditemukan")
        with duckdb.connect(str(self.db_path)) as conn:
            return self._plan(conn)

    def _backup(self, conn, plan, reset_id):
        # Logical copy avoids Windows' exclusive file lock on the live database.
        # The runtime database gate excludes writers while the snapshot is made.
        folder = self.db_path.parent / 'reset-backups' / reset_id
        folder.mkdir(parents=True, exist_ok=False)
        target = folder / self.db_path.name
        source_name = conn.execute('SELECT current_database()').fetchone()[0]
        conn.execute("ATTACH '" + str(target).replace("'", "''") + "' AS reset_backup")
        try:
            conn.execute(f'COPY FROM DATABASE {quote(source_name)} TO reset_backup')
        except Exception:
            try:
                conn.execute('ROLLBACK')
            except duckdb.Error:
                pass
            raise
        finally:
            conn.execute('DETACH reset_backup')
        with duckdb.connect(str(target), read_only=True) as backup:
            if self._inventory(backup) != plan['tables']:
                raise ValueError("Verifikasi backup gagal; reset dibatalkan")
        if self.jobs_path and self.jobs_path.exists():
            with sqlite3.connect(str(self.jobs_path)) as source, sqlite3.connect(str(folder / 'jobs.sqlite')) as dest:
                source.backup(dest)
        return folder

    def _delete_table(self, conn, item):
        conn.execute(f"DELETE FROM {quote(item['schema'])}.{quote(item['table'])}")

    def confirm(self, payload):
        actor, reason = str(payload.get('actor') or '').strip(), str(payload.get('reason') or '').strip()
        if payload.get('confirmation') != CONFIRMATION or not actor or not reason:
            raise ValueError("Frasa konfirmasi, nama petugas, dan alasan reset wajib diisi")
        with duckdb.connect(str(self.db_path)) as conn:
            plan = self._plan(conn)
            if plan['blockers']:
                raise ValueError('; '.join(plan['blockers']))
            if payload.get('preview_token') != plan['preview_token']:
                raise ValueError("Data berubah atau preview belum dilakukan. Preview ulang sebelum reset")
            reset_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
            folder = self._backup(conn, plan, reset_id)
            # Backup/manifest must be durable before the first DELETE.
            manifest = {**plan, "reset_id": reset_id, "actor": actor, "reason": reason,
                        "backup_path": str(folder), "state": "BACKUP_VERIFIED"}
            (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            conn.execute("BEGIN TRANSACTION")
            try:
                if self._plan(conn)['preview_token'] != plan['preview_token']:
                    raise ValueError("Data berubah setelah backup; reset dibatalkan")
                for item in plan['tables']:
                    if item['action'] == 'DELETE':
                        self._delete_table(conn, item)
                conn.execute("""CREATE TABLE IF NOT EXISTS application_reset_audit (
                    id VARCHAR PRIMARY KEY, created_at TIMESTAMP DEFAULT now(),
                    actor VARCHAR, reason VARCHAR, backup_path VARCHAR, manifest_json VARCHAR)""")
                conn.execute("INSERT INTO application_reset_audit(id,actor,reason,backup_path,manifest_json) VALUES (?,?,?,?,?)",
                             [reset_id, actor, reason, str(folder), json.dumps(plan)])
                after = {r['table']: r for r in self._inventory(conn)}
                for item in plan['tables']:
                    if item['action'] == 'DELETE' and after[item['table']]['rows']:
                        raise ValueError("Verifikasi penghapusan gagal")
                    if item['action'] == 'KEEP' and item['table'] != 'application_reset_audit' and after[item['table']] != item:
                        raise ValueError("Verifikasi pelestarian Master/aturan gagal")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {"status": "ok", "reset_id": reset_id, "deleted_rows": plan['deleted_rows'],
                "backup_path": str(folder), "preserved_note": plan['preserved_note']}


def create_router(db_path, jobs_path):
    router = APIRouter(
        prefix='/api/admin/reset-operational',
        tags=['Administrative reset'],
        dependencies=[Depends(require_api_key)],
    )

    @router.get('/preview')
    def preview():
        try:
            return ApplicationResetService(db_path(), jobs_path()).preview()
        except (ValueError, OSError, duckdb.Error) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/confirm')
    def confirm(payload: dict):
        try:
            return ApplicationResetService(db_path(), jobs_path()).confirm(payload)
        except (ValueError, OSError, duckdb.Error) as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
