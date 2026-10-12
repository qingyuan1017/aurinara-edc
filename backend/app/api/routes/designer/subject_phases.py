"""Subject phase definition authoring routes — Designer-owned.

Handlers for authoring ``Subject_Phase_Definition`` records inside a
Draft_Design, delegating to the Designer ``subject_phase_service``.

Satisfies Requirements:
  - 3.1: Persist a phase definition (name 1-100, display_order 1-999) unique
         within its Design_Version.

Endpoints:
  - GET    /versions/{version_id}/subject-phases   list a version's phases
  - POST   /versions/{version_id}/subject-phases   create a subject phase
  - PATCH  /subject-phases/{phase_id}              update a subject phase
  - DELETE /subject-phases/{phase_id}              delete a subject phase (cascade)
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
    SubjectPhaseDefinitionUpdate,
)
from app.services.designer.study_version_service import study_version_service
from app.services.designer.subject_phase_service import subject_phase_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-subject-phases"])


@router.get(
    "/{version_id}/subject-phases",
    response_model=list[SubjectPhaseDefinitionResponse],
)
async def list_subject_phases(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.read"))],
) -> list[SubjectPhaseDefinitionResponse]:
    """List a Design_Version's subject phase definitions.

    Permission: designer.subject_phase.read (Designer_Role only)
    """
    return [
        SubjectPhaseDefinitionResponse.model_validate(phase)
        for phase in await subject_phase_service.list_phase_definitions(session, version_id)
    ]


@router.post(
    "/{version_id}/subject-phases",
    response_model=SubjectPhaseDefinitionResponse,
    status_code=201,
)
async def create_subject_phase(
    version_id: UUID,
    body: SubjectPhaseDefinitionCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.configure"))],
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
        phase_type=body.phase_type,
        display_order=body.display_order,
        visit_definition_ids=body.visit_definition_ids,
        actor_id=current_user.id,
    )
    return SubjectPhaseDefinitionResponse.model_validate(phase)


# ---------------------------------------------------------------------------
# Single phase operations (mounted at /subject-phases), mirroring /forms+/fields
# ---------------------------------------------------------------------------

subject_phases_router = APIRouter(prefix="/subject-phases", tags=["designer-subject-phases"])


@subject_phases_router.patch(
    "/{phase_id}",
    response_model=SubjectPhaseDefinitionResponse,
)
async def update_subject_phase(
    phase_id: UUID,
    body: SubjectPhaseDefinitionUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.configure"))],
) -> SubjectPhaseDefinitionResponse:
    """Update a Subject_Phase_Definition (partial PATCH).

    Permission: designer.subject_phase.configure (Designer_Role only)
    """
    phase = await subject_phase_service.get_phase_definition(session, phase_id)
    version = await study_version_service.get_version(session, phase.design_version_id)
    study_version_service.guard_mutable(version)

    updated = await subject_phase_service.update_phase_definition(
        session,
        phase_id,
        name=body.name,
        phase_type=body.phase_type,
        display_order=body.display_order,
        visit_definition_ids=body.visit_definition_ids,
        actor_id=current_user.id,
    )
    return SubjectPhaseDefinitionResponse.model_validate(updated)


@subject_phases_router.delete("/{phase_id}", status_code=204)
async def delete_subject_phase(
    phase_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.subject_phase.configure"))],
) -> None:
    """Delete a Subject_Phase_Definition, cascading its transition edges.

    Permission: designer.subject_phase.configure (Designer_Role only)
    """
    phase = await subject_phase_service.get_phase_definition(session, phase_id)
    version = await study_version_service.get_version(session, phase.design_version_id)
    study_version_service.guard_mutable(version)

    await subject_phase_service.delete_phase_definition(
        session,
        phase_id,
        actor_id=current_user.id,
    )


__all__ = ["router", "subject_phases_router"]
