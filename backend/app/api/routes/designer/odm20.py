"""ODM 2.0 JSON metadata interchange routes."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.core.exceptions import ValidationError
from app.models.shared.identity import User
from app.schemas.designer.odm20 import OdmDocument, OdmImportResult, OdmValidationReport
from app.services.designer.odm20_service import odm20_service
from app.services.shared.permission_service import PermissionService

router = APIRouter(prefix="/studies", tags=["designer-odm2"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]


@router.post("/{study_id}/odm2/validate", response_model=OdmValidationReport)
async def validate_odm_document(
    study_id: UUID,
    body: dict[str, Any],
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> OdmValidationReport:
    permission_service.require(current_user, "designer.odm.import", study_id=study_id)
    return await odm20_service.validate_document(body)


@router.post("/{study_id}/odm2/import", response_model=OdmImportResult, status_code=201)
async def import_odm_document(
    study_id: UUID,
    body: dict[str, Any],
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    target_version_id: Annotated[UUID | None, Query()] = None,
    version_number: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
) -> OdmImportResult:
    permission_service.require(current_user, "designer.odm.import", study_id=study_id)
    return await odm20_service.import_document(
        session,
        study_id=study_id,
        payload=body,
        actor_id=current_user.id,
        target_version_id=target_version_id,
        version_number=version_number,
    )


@router.get("/{study_id}/versions/{version_id}/odm2", response_model=OdmDocument)
async def export_odm_document(
    study_id: UUID,
    version_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    profile: Annotated[Literal["aurinara", "core"], Query()] = "aurinara",
) -> OdmDocument:
    permission_service.require(current_user, "designer.odm.export", study_id=study_id)
    document = await odm20_service.export_document(
        session, study_id=study_id, version_id=version_id
    )
    if profile == "core" and odm20_service._extensions_used(document):
        raise ValidationError(
            "The design contains behavior that is not portable in the core ODM profile",
            details={"profile": "core", "extensions": odm20_service._extensions_used(document)},
        )
    return document


__all__ = ["router"]
