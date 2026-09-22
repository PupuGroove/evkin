"""Transactional, whitelist-only data reset for user-facing modules."""
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, HTTPException
from backend.security import require_api_key


PROTECTED_TABLES = frozenset({
    'master_data', 'master_sdm', 'master_unit_kerja', 'master_jabatan', 'master_tukin',
    'sdm_master', 'sdm_assignment_history', 'sdm_tukin_profile_history', 'sdm_bank_history',
    'sdm_temporary_assignment_history', 'sdm_change_request', 'sdm_active_history',
    'sdm_validation_issue', 'sdm_master_import_batch', 'skp_rule_config', 'master_skp_rules',
    'workflow_config', 'audit_log', 'application_reset_audit', 'final_tukin_schema',
    'skp_assessment_audit', 'skp_indicator_config', 'skp_indicator_config_audit',
    'skp_condition_decision_audit', 'tukin_period_audit', 'tukin_admin_audit',
    'pengembalian_tukin', 'pengembalian_uang_makan', 'rekap_pengembalian', 'rekonsiliasi',
    'bnba', 'pengembalian_period', 'pengembalian_archive_dataset', 'pengembalian_archive_dataset_row',
    'pengembalian_payment_transaction', 'pengembalian_final', 'pengembalian_obligation',
    'pengembalian_progress_import_batch', 'pengembalian_progress_transaction',
    'pengembalian_sp2d_lineage', 'pengembalian_master_obligation', 'pengembalian_period_audit',
})

MODULE_TABLES = {
    'workflow': frozenset({'raw_import', 'workflow_records', 'hitung_harian', 'rekap_sdm', 'anomali', 'final_absensi',
                           'final_skp', 'final_kombinasi', 'final_combined_skp'}),
    'skp': frozenset({'skp_assessment_monthly', 'skp_import_source', 'skp_import_batch', 'skp_import_batches', 'skp_results',
                      'skp_meeting_batch', 'skp_meeting_member',
                      'skp_assessment_exception', 'skp_condition_decision'}),
    'final_tukin': frozenset({'final_tukin_batches', 'final_tukin_results'}),
    'pengelolaan_tukin': frozenset({'tukin_period', 'tukin_import_batch', 'tukin_skp_monthly',
                                    'tukin_final_monthly', 'tukin_attendance_daily',
                                    'tukin_condition', 'tukin_payment_event', 'tukin_combined_adjustment'}),
    'workflow_results': frozenset({'hitung_harian', 'rekap_sdm', 'anomali', 'final_absensi'}),
}


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


class ModuleResetService:
    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()

    def _existing(self, conn):
        return {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()}

    def reset_module_data(self, module_name):
        if module_name not in MODULE_TABLES:
            raise ValueError(f'Modul reset tidak dikenal: {module_name}')
        targets = set(MODULE_TABLES[module_name])
        protected = targets & PROTECTED_TABLES
        if protected:
            raise ValueError(f'Reset dibatalkan; tabel protected terpetakan: {sorted(protected)}')
        deleted = {}
        with duckdb.connect(str(self.db_path)) as conn:
            existing = self._existing(conn)
            missing = targets - existing
            targets &= existing
            constraints = conn.execute("SELECT * FROM duckdb_constraints() WHERE constraint_type='FOREIGN KEY'").fetchall()
            referenced = {row[4] for row in constraints if len(row) > 4 and row[4] in targets}
            ordered = sorted(targets, key=lambda table: table in referenced)
            conn.execute('BEGIN TRANSACTION')
            try:
                for table in ordered:
                    count = int(conn.execute(f'SELECT COUNT(*) FROM {_quote(table)}').fetchone()[0])
                    conn.execute(f'DELETE FROM {_quote(table)}')
                    deleted[table] = count
                for table in missing:
                    deleted[table] = 0
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK')
                raise
        return {'status': 'ok', 'module': module_name, 'deleted': deleted,
                'deleted_rows': sum(deleted.values()), 'protected_tables': sorted(PROTECTED_TABLES)}


def create_router(db_path):
    router = APIRouter(
        prefix='/api/admin/module-reset',
        tags=['Module data reset'],
        dependencies=[Depends(require_api_key)],
    )

    @router.post('/{module_name}')
    def reset_module(module_name: str):
        try:
            return ModuleResetService(db_path()).reset_module_data(module_name)
        except (ValueError, OSError, duckdb.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
