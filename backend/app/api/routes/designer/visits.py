"""Visit definition authoring routes — Designer-owned.

Handlers for authoring ``Visit_Definition`` records inside a Draft_Design,
delegating to the Designer ``visit_definition_service``.

Satisfies Requirements:
  - 4.2: Persist a Visit_Definition within a draft Design_Version.
  - 4.3: Reject a Visit_Definition whose window bounds are inverted.

Endpoints:
  - GET  /versions/{version_id}/visits   list the version's visit definitions
  - POST /versions/{version_id}/visits   create a visit definition
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.visit import (
    VisitDefinitionCreate,
    VisitDefinitionResponse,
)
from app.services.designer.study_version_service import study_version_service
from app.services.designer.visit_definition_service import visit_definition_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-visits"])


@router.post(
    "/{version_id}/visits",
    response_model=VisitDefinitionResponse,
    status_code=201,
)
async def create_visit(
    version_id: UUID,
    body: VisitDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.configure"))],
) -> VisitDefinitionResponse:
    """Create a Visit_Definition within a draft Design_Version.

    Permission: designer.visit.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    definition = await visit_definition_service.define_visit(
        session,
        version=version,
        data=body,
        actor_id=current_user.id,
    )
    return VisitDefinitionResponse.model_validate(definition)


@router.get(
    "/{version_id}/visits",
    response_model=list[VisitDefinitionResponse],
)
async def list_visits(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.read"))],
) -> list[VisitDefinitionResponse]:
    """List the Visit_Definitions for a Design_Version.

    Permission: designer.visit.read (Designer_Role only)
    """
    await study_version_service.get_version(session, version_id)
    return [
        VisitDefinitionResponse.model_validate(definition)
        for definition in await visit_definition_service.list_definitions(session, version_id)
    ]


__all__ = ["router"]
