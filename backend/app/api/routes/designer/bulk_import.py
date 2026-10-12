"""Atomic JSON import endpoint for Designer definitions."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_permission_service
from app.models.shared.identity import User
from app.schemas.designer.bulk_import import (
    DesignerBulkImportRequest,
    DesignerBulkImportResponse,
)
from app.services.designer.bulk_import_service import designer_bulk_import_service
from app.services.edc.study_service import study_service
from app.services.shared.permission_service import PermissionService

router = APIRouter(prefix="/studies", tags=["designer-import"])


@router.post(
    "/{study_id}/bulk-import",
    response_model=DesignerBulkImportResponse,
    status_code=201,
)
async def bulk_import_designer_definitions(
    study_id: UUID,
    body: DesignerBulkImportRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    study_version_id: Annotated[
        UUID | None,
        Query(description="Target draft version; defaults to the latest draft."),
    ] = None,
) -> DesignerBulkImportResponse:
    """Validate and create all supplied definitions in one transaction."""
    await study_service.get_study(session, study_id)

    required_permissions: set[str] = set()
    if body.forms:
        required_permissions.add("designer.form.configure")
        if any(section.fields for form in body.forms for section in form.sections):
            required_permissions.add("designer.field.configure")
    if body.edit_checks:
        required_permissions.add("designer.editcheck.configure")
    if body.codelists:
        required_permissions.add("designer.codelist.configure")
    if body.visits:
        required_permissions.add("designer.visit.configure")
    for permission in sorted(required_permissions):
        permission_service.require(current_user, permission, study_id=study_id)

    version = await designer_bulk_import_service.get_target_version(
        session, study_id, study_version_id
    )
    return await designer_bulk_import_service.import_definitions(
        session, version, body, current_user.id
    )


__all__ = ["router"]
