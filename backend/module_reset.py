"""HTTP adapter for the canonical reset service."""
from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from backend.reset_service import MODULE_PROTECTED_TABLES, RESET_PROFILES, ResetService
from backend.security import require_api_key


# Backward-compatible imports; the registry itself lives in reset_service.py.
PROTECTED_TABLES = MODULE_PROTECTED_TABLES
MODULE_TABLES = {name: frozenset(spec.tables) for name, spec in RESET_PROFILES.items()}


class ModuleResetService(ResetService):
    def __init__(self, db_path):
        super().__init__(Path(db_path).resolve())

    def preview_module(self, module_name):
        return self.preview(module_name)

    def reset_module_data(self, module_name, payload):
        return self.execute(module_name, payload, source='MODULE_RESET_API')


def create_router(db_path):
    router = APIRouter(
        prefix='/api/admin/module-reset',
        tags=['Module data reset'],
        dependencies=[Depends(require_api_key)],
    )

    @router.get('/{module_name}/preview')
    def preview_module(module_name: str):
        try:
            return ModuleResetService(db_path()).preview_module(module_name)
        except (ValueError, OSError, duckdb.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post('/{module_name}')
    def reset_module(module_name: str, payload: dict | None = None):
        try:
            return ModuleResetService(db_path()).reset_module_data(module_name, payload or {})
        except (ValueError, OSError, duckdb.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
