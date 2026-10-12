"""CRF access definition authoring routes — Designer-owned.

Handlers for authoring ``Crf_Access_Definition`` records (per-role read/write
access to forms/fields) inside a Draft_Design, delegating to the Designer
``crf_access_service``.

Satisfies Requirements:
  - 4.6: Persist per-role read/write access for a form or field within a design
         version.

Endpoints:
  - GET  /versions/{version_id}/crf-access   list CRF access definitions
  - POST /versions/{version_id}/crf-access   create a CRF access definition
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.crf_access_definition import (
    CrfAccessDefinitionCreate,
    CrfAccessDefinitionResponse,
)
from app.services.designer.crf_access_service import crf_access_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-crf-access"])


@router.get(
    "/{version_id}/crf-access",
    response_model=list[CrfAccessDefinitionResponse],
)
async def list_crf_access(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.crf_access.configure"))],
) -> list[CrfAccessDefinitionResponse]:
    """List CRF access definitions for a draft or published Design_Version."""
    await study_version_service.get_version(session, version_id)
    return [
        CrfAccessDefinitionResponse.model_validate(item)
        for item in await crf_access_service.list_access_definitions(session, version_id)
    ]


@router.post(
    "/{version_id}/crf-access",
    response_model=CrfAccessDefinitionResponse,
    status_code=201,
)
async def create_crf_access(
    version_id: UUID,
    body: CrfAccessDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.crf_access.configure"))],
) -> CrfAccessDefinitionResponse:
    """Create a Crf_Access_Definition within a draft Design_Version.

    Permission: study.configure
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    access = await crf_access_service.create_access_definition(
        session,
        design_version_id=version.id,
        role=body.role,
        can_read=body.can_read,
        can_write=body.can_write,
        form_definition_id=body.form_definition_id,
        field_definition_id=body.field_definition_id,
        blinded=body.blinded,
        unblind_role=body.unblind_role,
        actor_id=current_user.id,
    )
    return CrfAccessDefinitionResponse.model_validate(access)


__all__ = ["router"]
