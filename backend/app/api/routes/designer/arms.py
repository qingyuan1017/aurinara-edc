"""Arm definition authoring routes — Designer-owned.

Handlers for authoring ``Arm_Definition`` records (study arms / treatment
groups) inside a Draft_Design, delegating to the Designer ``arm_service``. An
arm declares which real visit leaves (standalone or cycle-owned) occur in it.

Satisfies Requirements:
  - 4.5: Persist an Arm_Definition within a Draft_Design.

Endpoints:
  - GET  /versions/{version_id}/arms   list the version's arm definitions
  - POST /versions/{version_id}/arms   create an arm definition
  - PATCH /versions/{version_id}/arms/{arm_id} update an arm definition
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.exceptions import NotFoundError
from app.models.designer.arm_definition import ArmDefinition
from app.models.shared.identity import User
from app.schemas.designer.arm_definition import (
    ArmDefinitionCreate,
    ArmDefinitionResponse,
    ArmDefinitionUpdate,
)
from app.services.designer.arm_service import arm_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-arms"])


def _to_response(arm: ArmDefinition) -> ArmDefinitionResponse:
    """Build an arm response, populating member visit ids explicitly.

    ``model_validate(arm)`` cannot populate ``visit_definition_ids`` because the
    ORM relationship is named ``visits``; it is read from the eager-loaded
    ``arm.visits`` collection (loaded by the service's flush / selectinload).
    """
    return ArmDefinitionResponse(
        id=arm.id,
        study_version_id=arm.study_version_id,
        name=arm.name,
        display_order=arm.display_order,
        description=arm.description,
        visit_definition_ids=[v.id for v in arm.visits],
        created_at=arm.created_at,
        updated_at=arm.updated_at,
    )


@router.post("/{version_id}/arms", response_model=ArmDefinitionResponse, status_code=201)
async def create_arm(
    version_id: UUID,
    body: ArmDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.arm.configure"))],
) -> ArmDefinitionResponse:
    """Create an Arm_Definition within a draft Design_Version.

    Permission: designer.arm.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    arm = await arm_service.create_arm_definition(
        session,
        design_version_id=version.id,
        name=body.name,
        display_order=body.display_order,
        description=body.description,
        visit_definition_ids=body.visit_definition_ids,
        actor_id=current_user.id,
    )
    return _to_response(arm)


@router.get("/{version_id}/arms", response_model=list[ArmDefinitionResponse])
async def list_arms(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.arm.read"))],
) -> list[ArmDefinitionResponse]:
    """List the Arm_Definitions for a Design_Version.

    Permission: designer.arm.read (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    return [
        _to_response(arm) for arm in await arm_service.list_arm_definitions(session, version.id)
    ]


@router.patch("/{version_id}/arms/{arm_id}", response_model=ArmDefinitionResponse)
async def update_arm(
    version_id: UUID,
    arm_id: UUID,
    body: ArmDefinitionUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.arm.configure"))],
) -> ArmDefinitionResponse:
    """Update an Arm_Definition within a draft Design_Version."""
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)
    arm = await arm_service.get_arm_definition(session, arm_id)
    if arm.study_version_id != version.id:
        raise NotFoundError(
            "Arm definition not found",
            details={"arm_id": str(arm_id)},
        )
    return _to_response(
        await arm_service.update_arm_definition(
            session,
            arm_id,
            body,
            actor_id=current_user.id,
        )
    )


__all__ = ["router"]
