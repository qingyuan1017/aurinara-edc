"""Authenticated sanitized CTMS operational health route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import require_ctms_permission
from app.models.identity import User
from app.services.ctms_health_service import ctms_health_service

router = APIRouter(tags=["ctms-health"])
AdminGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]


@router.get("/health", response_model=dict[str, object])
async def ctms_health(current_user: AdminGuard) -> dict[str, object]:
    return ctms_health_service.snapshot()
