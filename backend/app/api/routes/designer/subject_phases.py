"""Subject phase definition authoring routes — Designer-owned.

Handlers for authoring ``Subject_Phase_Definition`` records inside a
Draft_Design, delegating to the Designer ``subject_phase_service``.

Satisfies Requirements:
  - 3.1: Persist a phase definition (name 1-100, display_order 1-999) unique
         within its Design_Version.

Endpoints:
  - POST /versions/{version_id}/subject-phases   create a subject phase
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.subject_phase_definition import (
    SubjectPhaseDefinitionCreate,
    SubjectPhaseDefinitionResponse,
)
from app.services.designer.study_version_service import study_version_service
from app.services.designer.subject_phase_service import subject_phase_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-subject-phases"])


@router.post(
    "/{version_id}/subject-phases",
    response_model=SubjectPhaseDefinitionResponse,
    status_code=201,
)
async def create_subject_phase(
    version_id: UUID,
    body: SubjectPhaseDefinitionCreate,
    session: DbSession,
    current_user: Annotated[
        User, Depends(require_permission("designer.subject_phase.configure"))
    ],
) -> SubjectPhaseDefinitionResponse:
    """Create a Subject_Phase_Definition within a draft Design_Version.

    Permission: designer.subject_phase.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    phase = await subject_phase_service.create_phase_definition(
        session,
        design_version_id=version.id,
        name=body.name,
        display_order=body.display_order,
        actor_id=current_user.id,
    )
    return SubjectPhaseDefinitionResponse.model_validate(phase)


__all__ = ["router"]
