"""HTTP adapter for the canonical backed-up operational reset profile."""
import duckdb
from fastapi import APIRouter, Depends, HTTPException

from backend.reset_service import OPERATIONAL_CONFIRMATION, ResetService
from backend.security import require_api_key


CONFIRMATION = OPERATIONAL_CONFIRMATION


class ApplicationResetService(ResetService):
    def preview(self):
        return super().preview('operational')

    def confirm(self, payload):
        return self.execute('operational', payload, source='OPERATIONAL_RESET_API')


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
