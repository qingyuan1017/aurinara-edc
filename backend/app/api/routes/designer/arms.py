"""Arm definition authoring routes — Designer-owned.

Handlers for authoring ``Arm_Definition`` records (study arms / treatment
groups) inside a Draft_Design, delegating to the Designer ``arm_service``.

Satisfies Requirements:
  - 4.5: Persist an Arm_Definition within a Draft_Design.

Endpoints:
  - POST /versions/{version_id}/arms   create an arm definition
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.arm_definition import (
    ArmDefinitionCreate,
    ArmDefinitionResponse,
)
from app.services.designer.arm_service import arm_service
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-arms"])


@router.post(
    "/{version_id}/arms", response_model=ArmDefinitionResponse, status_code=201
)
async def create_arm(
    version_id: UUID,
    body: ArmDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.arm.configure"))],
) -> ArmDefinitionResponse:
    """Create an Arm_Definition within a draft Design_Version.

    Permission: study.configure
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    arm = await arm_service.create_arm_definition(
        session,
        design_version_id=version.id,
        name=body.name,
        display_order=body.display_order,
        description=body.description,
        actor_id=current_user.id,
    )
    return ArmDefinitionResponse.model_validate(arm)


__all__ = ["router"]
