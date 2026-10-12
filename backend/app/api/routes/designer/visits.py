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
    VisitDefinitionUpdate,
)
from app.services.designer.study_version_service import study_version_service
from app.services.designer.visit_definition_service import visit_definition_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-visits"])


def _response(
    definition: object, member_visit_ids: list[UUID] | None = None
) -> VisitDefinitionResponse:
    response = VisitDefinitionResponse.model_validate(definition)
    return response.model_copy(update={"member_visit_ids": member_visit_ids or []})


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
    memberships = await visit_definition_service.cycle_memberships(session, version_id)
    return _response(definition, memberships.get(definition.id))


@router.post(
    "/{version_id}/cycles/{cycle_id}/visits",
    response_model=VisitDefinitionResponse,
    status_code=201,
)
async def create_cycle_visit(
    version_id: UUID,
    cycle_id: UUID,
    body: VisitDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.configure"))],
) -> VisitDefinitionResponse:
    """Create a child visit owned exclusively by one cycle."""
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)
    cycle = await visit_definition_service.get_definition(session, cycle_id)
    definition = await visit_definition_service.define_cycle_visit(
        session,
        version=version,
        cycle=cycle,
        data=body,
        actor_id=current_user.id,
    )
    return _response(definition)


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
    definitions = await visit_definition_service.list_definitions(session, version_id)
    memberships = await visit_definition_service.cycle_memberships(session, version_id)
    return [_response(definition, memberships.get(definition.id)) for definition in definitions]


@router.patch(
    "/{version_id}/visits/{visit_id}",
    response_model=VisitDefinitionResponse,
)
async def update_visit(
    version_id: UUID,
    visit_id: UUID,
    body: VisitDefinitionUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.visit.configure"))],
) -> VisitDefinitionResponse:
    """Update visit metadata or replace a cycle's selected visit members."""
    version = await study_version_service.get_version(session, version_id)
    definition = await visit_definition_service.get_definition(session, visit_id)
    if definition.study_version_id != version.id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(
            "Visit definition not found in this design version",
            details={"visit_definition_id": str(visit_id)},
        )
    updated = await visit_definition_service.update_definition(
        session, version, definition, body, current_user.id
    )
    memberships = await visit_definition_service.cycle_memberships(session, version_id)
    return _response(updated, memberships.get(updated.id))


__all__ = ["router"]
