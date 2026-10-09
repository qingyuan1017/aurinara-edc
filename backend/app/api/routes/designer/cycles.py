"""Cycle definition authoring routes — Designer-owned.

Handlers for authoring ``Cycle_Definition`` records (repeating visit groups)
inside a Draft_Design, delegating to the Designer ``cycle_service``.

Satisfies Requirements:
  - 4.4: Persist a Cycle_Definition and its member Visit_Definitions within a
         Draft_Design.

Endpoints:
  - GET  /versions/{version_id}/cycles   list the version's cycle definitions
  - POST /versions/{version_id}/cycles   create a cycle definition
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.cycle_definition import (
    CycleDefinitionCreate,
    CycleDefinitionResponse,
)
from app.services.designer.cycle_service import cycle_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-cycles"])


@router.post(
    "/{version_id}/cycles", response_model=CycleDefinitionResponse, status_code=201
)
async def create_cycle(
    version_id: UUID,
    body: CycleDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.cycle.configure"))],
) -> CycleDefinitionResponse:
    """Create a Cycle_Definition within a draft Design_Version.

    Permission: study.configure
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    cycle = await cycle_service.create_cycle_definition(
        session,
        design_version_id=version.id,
        name=body.name,
        display_order=body.display_order,
        visit_definition_ids=body.visit_definition_ids,
        actor_id=current_user.id,
    )
    return CycleDefinitionResponse.model_validate(cycle)


@router.get(
    "/{version_id}/cycles", response_model=list[CycleDefinitionResponse]
)
async def list_cycles(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.cycle.read"))],
) -> list[CycleDefinitionResponse]:
    """List the Cycle_Definitions for a Design_Version.

    Permission: designer.cycle.read (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    return [
        CycleDefinitionResponse.model_validate(cycle)
        for cycle in await cycle_service.list_cycle_definitions(session, version.id)
    ]


__all__ = ["router"]
