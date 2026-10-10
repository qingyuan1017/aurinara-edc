"""Subject-phase transition authoring routes — Designer-owned.

Handlers for authoring ``Subject_Phase_Transition`` edges (phase-to-phase
transitions) inside a Draft_Design, delegating to the Designer
``subject_phase_transition_service``.

Endpoints:
  - POST   /versions/{version_id}/subject-phase-transitions
  - GET    /versions/{version_id}/subject-phase-transitions
  - DELETE /versions/{version_id}/subject-phase-transitions/{transition_id}
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.subject_phase_transition import (
    SubjectPhaseTransitionCreate,
    SubjectPhaseTransitionResponse,
)
from app.services.designer.study_version_service import study_version_service
from app.services.designer.subject_phase_transition_service import (
    subject_phase_transition_service,
)

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-subject-phase-transitions"])


@router.post(
    "/{version_id}/subject-phase-transitions",
    response_model=SubjectPhaseTransitionResponse,
    status_code=201,
)
async def create_subject_phase_transition(
    version_id: UUID,
    body: SubjectPhaseTransitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.configure"))],
) -> SubjectPhaseTransitionResponse:
    """Create a subject-phase transition edge within a draft Design_Version.

    Permission: designer.subject_phase.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    transition = await subject_phase_transition_service.create_transition(
        session,
        design_version_id=version.id,
        from_phase_id=body.from_phase_id,
        to_phase_id=body.to_phase_id,
        label=body.label,
        condition_expression=body.condition_expression,
        actor_id=current_user.id,
    )
    return SubjectPhaseTransitionResponse.model_validate(transition)


@router.get(
    "/{version_id}/subject-phase-transitions",
    response_model=list[SubjectPhaseTransitionResponse],
)
async def list_subject_phase_transitions(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.read"))],
) -> list[SubjectPhaseTransitionResponse]:
    """List a Design_Version's subject-phase transition edges.

    Permission: designer.subject_phase.read (Designer_Role only)
    """
    return [
        SubjectPhaseTransitionResponse.model_validate(t)
        for t in await subject_phase_transition_service.list_transitions(session, version_id)
    ]


@router.delete(
    "/{version_id}/subject-phase-transitions/{transition_id}",
    status_code=204,
)
async def delete_subject_phase_transition(
    version_id: UUID,
    transition_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.configure"))],
) -> None:
    """Delete a subject-phase transition edge from a draft Design_Version.

    Permission: designer.subject_phase.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    await subject_phase_transition_service.delete_transition(
        session,
        transition_id,
        actor_id=current_user.id,
    )


__all__ = ["router"]
