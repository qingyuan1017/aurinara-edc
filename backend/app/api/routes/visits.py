"""Visit routes — visit instances, unscheduled visits, dates, and missed status.

Satisfies Requirements:
  - 8.1: Visit definition metadata surfaced through visit instances.
  - 8.3: Record a visit date and compute window status.
  - 8.4: Create an unscheduled Visit_Instance for a subject.
  - 8.5: Mark a Visit_Instance as missed.
  - 21.1: All endpoints mounted under /api/v1.

Endpoints:
  - GET   /subjects/{subject_id}/visits               list visit instances (subject.read)
  - POST  /subjects/{subject_id}/visits/unscheduled   create unscheduled visit (subject.update)
  - GET   /visits/{visit_id}                          get visit instance (subject.read)
  - PATCH /visits/{visit_id}                           record visit date (subject.update)
  - POST  /visits/{visit_id}/mark-missed              mark missed (subject.update)
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.identity import User
from app.models.visit import VisitInstance
from app.schemas.visit import (
    UnscheduledVisitCreate,
    VisitDateRecord,
    VisitInstanceResponse,
)
from app.services.subject_service import subject_service
from app.services.visit_service import visit_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Subject-scoped visit collection (mounted at /subjects)
# ---------------------------------------------------------------------------

subject_visits_router = APIRouter(prefix="/subjects", tags=["visits"])


@subject_visits_router.get(
    "/{subject_id}/visits", response_model=list[VisitInstanceResponse]
)
async def list_subject_visits(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.read"))],
) -> list[VisitInstanceResponse]:
    """List visit instances for a subject.

    Permission: subject.read
    Requirement 8.3/8.5: Returns each visit instance with window/lifecycle status.
    """
    # Validate the subject exists (and is not soft-deleted).
    await subject_service.get_subject(session, subject_id)

    result = await session.execute(
        select(VisitInstance)
        .where(VisitInstance.subject_id == subject_id)
        .order_by(VisitInstance.created_at)
    )
    instances = result.scalars().all()
    return [VisitInstanceResponse.model_validate(i) for i in instances]


@subject_visits_router.post(
    "/{subject_id}/visits/unscheduled",
    response_model=VisitInstanceResponse,
    status_code=201,
)
async def create_unscheduled_visit(
    subject_id: UUID,
    body: UnscheduledVisitCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> VisitInstanceResponse:
    """Create an unscheduled visit instance for a subject.

    Permission: subject.update
    Requirement 8.4: Create an unscheduled Visit_Instance.
    """
    subject = await subject_service.get_subject(session, subject_id)
    instance = await visit_service.create_unscheduled(
        session=session,
        subject=subject,
        data=body,
        actor_id=current_user.id,
    )
    return VisitInstanceResponse.model_validate(instance)


# ---------------------------------------------------------------------------
# Single visit-instance operations (mounted at /visits)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/visits", tags=["visits"])


@router.get("/{visit_id}", response_model=VisitInstanceResponse)
async def get_visit(
    visit_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.read"))],
) -> VisitInstanceResponse:
    """Get a visit instance by ID.

    Permission: subject.read
    """
    instance = await visit_service.get_instance(session, visit_id)
    return VisitInstanceResponse.model_validate(instance)


@router.patch("/{visit_id}", response_model=VisitInstanceResponse)
async def record_visit_date(
    visit_id: UUID,
    body: VisitDateRecord,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> VisitInstanceResponse:
    """Record a visit date and compute the window status.

    Permission: subject.update
    Requirement 8.3: Compute window status from the visit date relative to the
    owning definition's target day and window bounds.
    """
    instance = await visit_service.get_instance(session, visit_id)
    updated = await visit_service.record_visit_date(
        session=session,
        instance=instance,
        visit_date=body.visit_date,
        actor_id=current_user.id,
        baseline_date=body.baseline_date,
    )
    return VisitInstanceResponse.model_validate(updated)


@router.post("/{visit_id}/mark-missed", response_model=VisitInstanceResponse)
async def mark_visit_missed(
    visit_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> VisitInstanceResponse:
    """Mark a visit instance as missed.

    Permission: subject.update
    Requirement 8.5: Set the visit instance status to missed.
    """
    instance = await visit_service.get_instance(session, visit_id)
    updated = await visit_service.mark_missed(
        session=session,
        instance=instance,
        actor_id=current_user.id,
    )
    return VisitInstanceResponse.model_validate(updated)
