"""Subject routes — enrollment, lifecycle transitions, and casebook.

Satisfies Requirements:
  - 7.1: Persist subject metadata bound to the applicable published Study_Version.
  - 7.3: Enforce subject status transitions through the subject state machine.
  - 7.5: Return the subject casebook (visit/form structure with clinical status).
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return a pagination envelope.

Endpoints:
  - GET    /studies/{study_id}/subjects            list subjects (subject.read)
  - POST   /studies/{study_id}/subjects            create subject (subject.create)
  - GET    /subjects/{subject_id}                  get subject (subject.read)
  - PATCH  /subjects/{subject_id}                  update subject (subject.update)
  - POST   /subjects/{subject_id}/screen-fail      → Screen Failed (subject.update)
  - POST   /subjects/{subject_id}/randomize        → Randomized (subject.update)
  - POST   /subjects/{subject_id}/terminate        → Early Terminated (subject.update)
  - GET    /subjects/{subject_id}/casebook         get casebook (subject.read)
"""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.models.identity import User
from app.models.subject import SubjectStatus
from app.schemas.base import PaginatedResponse
from app.schemas.subject import (
    CasebookResponse,
    SubjectCreate,
    SubjectResponse,
    SubjectUpdate,
)
from app.services.subject_service import subject_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study-scoped subject collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_subjects_router = APIRouter(prefix="/studies", tags=["subjects"])


@study_subjects_router.get(
    "/{study_id}/subjects", response_model=PaginatedResponse[SubjectResponse]
)
async def list_subjects(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.read"))],
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    status: SubjectStatus | None = None,
) -> PaginatedResponse[SubjectResponse]:
    """List subjects for a study (paginated, optional site_id/status filters).

    Permission: subject.read
    Requirement 21.2: Paginated response envelope.
    """
    result = await subject_service.list_subjects(
        session, study_id, pagination, site_id=site_id, status=status
    )
    return PaginatedResponse[SubjectResponse](
        items=[SubjectResponse.model_validate(s) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_subjects_router.post(
    "/{study_id}/subjects", response_model=SubjectResponse, status_code=201
)
async def create_subject(
    study_id: UUID,
    body: SubjectCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.create"))],
) -> SubjectResponse:
    """Create (enroll) a new subject within a study.

    Permission: subject.create
    Requirement 7.1: Bind the subject to the applicable published Study_Version.
    """
    subject = await subject_service.create_subject(
        session=session, study_id=study_id, data=body, actor_id=current_user.id
    )
    return SubjectResponse.model_validate(subject)


# ---------------------------------------------------------------------------
# Single-subject operations (mounted at /subjects)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.read"))],
) -> SubjectResponse:
    """Get a subject by ID.

    Permission: subject.read
    """
    subject = await subject_service.get_subject(session, subject_id)
    return SubjectResponse.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: UUID,
    body: SubjectUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> SubjectResponse:
    """Update subject metadata (partial PATCH).

    Permission: subject.update
    Requirement 7.6: Subject metadata changes write Audit_Events.
    """
    subject = await subject_service.get_subject(session, subject_id)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return SubjectResponse.model_validate(subject)

    for field_name, new_value in update_data.items():
        old_value = getattr(subject, field_name, None)
        setattr(subject, field_name, new_value)

        if old_value != new_value:
            await audit_service.record(
                session,
                entity_type="subject",
                entity_id=subject.id,
                action="update",
                study_id=subject.study_id,
                site_id=subject.site_id,
                subject_id=subject.id,
                actor_id=current_user.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
            )

    subject.updated_at = datetime.now(UTC)
    await session.flush()

    logger.info("Subject updated: id=%s actor=%s", subject.id, current_user.id)
    return SubjectResponse.model_validate(subject)


# ---------------------------------------------------------------------------
# Status transition convenience endpoints (Requirement 7.3)
# ---------------------------------------------------------------------------


@router.post("/{subject_id}/screen-fail", response_model=SubjectResponse)
async def screen_fail_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> SubjectResponse:
    """Transition a subject to Screen Failed.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await subject_service.get_subject(session, subject_id)
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.screen_failed,
        actor_id=current_user.id,
    )
    return SubjectResponse.model_validate(updated)


@router.post("/{subject_id}/randomize", response_model=SubjectResponse)
async def randomize_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> SubjectResponse:
    """Transition a subject to Randomized.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await subject_service.get_subject(session, subject_id)
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.randomized,
        actor_id=current_user.id,
    )
    return SubjectResponse.model_validate(updated)


@router.post("/{subject_id}/terminate", response_model=SubjectResponse)
async def terminate_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.update"))],
) -> SubjectResponse:
    """Transition a subject to Early Terminated.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await subject_service.get_subject(session, subject_id)
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.early_terminated,
        actor_id=current_user.id,
    )
    return SubjectResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Casebook (Requirement 7.5)
# ---------------------------------------------------------------------------


@router.get("/{subject_id}/casebook", response_model=CasebookResponse)
async def get_subject_casebook(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("subject.read"))],
) -> CasebookResponse:
    """Get the subject casebook (visit/form structure with clinical status).

    Permission: subject.read
    Requirement 7.5: Return the subject casebook.
    """
    casebook = await subject_service.get_casebook(session, subject_id)
    return CasebookResponse.model_validate(casebook)
