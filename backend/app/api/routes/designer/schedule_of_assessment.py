"""Schedule-of-assessment authoring routes — Designer-owned.

Handlers for authoring the ``Schedule_of_Assessment`` matrix inside a
Draft_Design, delegating to the Designer ``schedule_of_assessment_service``.

Satisfies Requirements:
  - 4.1: Persist a schedule of assessment that maps forms/procedures to visit
         definitions within a design version.

Endpoints:
  - GET  /versions/{version_id}/schedule-of-assessment   get the version's SoA
  - POST /versions/{version_id}/schedule-of-assessment   create the version's SoA
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.designer.schedule_of_assessment import (
    ScheduleOfAssessmentCreate,
    ScheduleOfAssessmentResponse,
)
from app.services.designer.schedule_of_assessment_service import (
    ScheduleEntryInput,
    schedule_of_assessment_service,
)
from app.services.designer.study_version_service import study_version_service

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/versions", tags=["designer-schedule-of-assessment"])


@router.get(
    "/{version_id}/schedule-of-assessment",
    response_model=ScheduleOfAssessmentResponse,
)
async def get_schedule_of_assessment(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.soa.read"))],
    arm_definition_id: UUID | None = None,
) -> ScheduleOfAssessmentResponse:
    """Get the schedule of assessment for a Design_Version.

    Permission: designer.soa.read (Designer_Role only)
    """
    await study_version_service.get_version(session, version_id)
    soa = await schedule_of_assessment_service.get_schedule_of_assessment(
        session, version_id, arm_definition_id
    )
    return ScheduleOfAssessmentResponse.model_validate(soa)


@router.post(
    "/{version_id}/schedule-of-assessment",
    response_model=ScheduleOfAssessmentResponse,
    status_code=201,
)
async def create_schedule_of_assessment(
    version_id: UUID,
    body: ScheduleOfAssessmentCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("designer.soa.configure"))],
) -> ScheduleOfAssessmentResponse:
    """Create the schedule of assessment for a draft Design_Version.

    Permission: designer.soa.configure (Designer_Role only)
    """
    version = await study_version_service.get_version(session, version_id)
    study_version_service.guard_mutable(version)

    entries = [
        ScheduleEntryInput(
            form_definition_id=entry.form_definition_id,
            procedure_name=entry.procedure_name,
            visit_definition_id=entry.visit_definition_id,
            display_order=entry.display_order,
        )
        for entry in body.entries
    ]

    soa = await schedule_of_assessment_service.create_schedule_of_assessment(
        session,
        design_version_id=version.id,
        arm_definition_id=body.arm_definition_id,
        entries=entries,
        actor_id=current_user.id,
    )
    return ScheduleOfAssessmentResponse.model_validate(soa)


__all__ = ["router"]
