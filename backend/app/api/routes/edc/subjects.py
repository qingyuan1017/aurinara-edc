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
  - DELETE /subjects/{subject_id}                  remove entered-in-error subject (subject.delete)
  - POST   /subjects/{subject_id}/restore          restore removed subject (subject.restore)
  - POST   /subjects/{subject_id}/screen-fail      → Screen Failed (subject.update)
  - POST   /subjects/{subject_id}/randomize        → Randomized (subject.update)
  - POST   /subjects/{subject_id}/terminate        → Early Terminated (subject.update)
  - POST   /subjects/{subject_id}/deactivate       → Inactive (subject.update)
  - POST   /subjects/{subject_id}/discontinue      → Discontinued (subject.update)
  - POST   /subjects/{subject_id}/phase/reverse    reverse one audited phase (subject.update)
  - POST   /subjects/{subject_id}/switch-site      change an eligible subject's Site (subject.transfer)
  - GET    /subjects/{subject_id}/casebook         get casebook (subject.read)
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.core.audit import audit_service
from app.models.edc.subject import SubjectStatus
from app.models.shared.identity import User
from app.schemas.edc.subject import (
    CasebookResponse,
    SubjectCreate,
    SubjectDelete,
    SubjectEnrollmentReadinessResponse,
    SubjectLifecycleChange,
    SubjectListResponse,
    SubjectPhaseReverse,
    SubjectPhaseStateResponse,
    SubjectPhaseUpdate,
    SubjectResponse,
    SubjectRestore,
    SubjectSiteTransfer,
    SubjectUpdate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.operational_service import edc_operational_service
from app.services.edc.scope_service import edc_scope_service
from app.services.edc.sdr_service import sdr_service
from app.services.edc.subject_service import subject_service
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _authorized_subject(
    session: AsyncSession,
    subject_id: UUID,
    current_user: User,
    permission_service: PermissionService,
    permission: str,
    *,
    include_deleted: bool = False,
):
    subject = await subject_service.get_subject(
        session,
        subject_id,
        include_deleted=include_deleted,
    )
    edc_scope_service.require_subject(current_user, permission_service, permission, subject)
    return subject


# ---------------------------------------------------------------------------
# Study-scoped subject collection (mounted at /studies)
# ---------------------------------------------------------------------------

study_subjects_router = APIRouter(prefix="/studies", tags=["subjects"])


@study_subjects_router.get(
    "/{study_id}/subjects", response_model=PaginatedResponse[SubjectListResponse]
)
async def list_subjects(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[PaginationParams, Depends()],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
    site_id: UUID | None = None,
    status: SubjectStatus | None = None,
    search: str | None = None,
    phase_id: UUID | None = None,
    quality_state: Literal["queried", "incomplete", "stale_review", "clean"] | None = None,
    sort: str = "created_desc",
    include_deleted: bool = False,
) -> PaginatedResponse[SubjectListResponse]:
    """List subjects for a study (paginated, optional site_id/status filters).

    Permission: subject.read
    Requirement 21.2: Paginated response envelope.
    """
    list_permission = "subject.restore" if include_deleted else "subject.read"
    authorized_site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, list_permission, study_id
    )
    result = await subject_service.list_subjects(
        session,
        study_id,
        pagination,
        site_id=site_id,
        status=status,
        search=search,
        phase_id=phase_id,
        authorized_site_ids=authorized_site_ids,
        quality_state=quality_state,
        sort=sort,
        include_deleted=include_deleted,
    )
    summaries = await edc_operational_service.subject_summaries(session, list(result.items))
    return PaginatedResponse[SubjectListResponse](
        items=[
            SubjectListResponse(
                **SubjectResponse.model_validate(subject).model_dump(),
                site_name=subject.site.name if subject.site else None,
                current_phase_name=(
                    subject.current_phase_definition.name
                    if subject.current_phase_definition
                    else None
                ),
                current_phase_type=(
                    subject.current_phase_definition.phase_type
                    if subject.current_phase_definition
                    else None
                ),
                **summaries.get(subject.id, {}),
            )
            for subject in result.items
        ],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@study_subjects_router.post("/{study_id}/subjects", response_model=SubjectResponse, status_code=201)
async def create_subject(
    study_id: UUID,
    body: SubjectCreate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Create (enroll) a new subject within a study.

    Permission: subject.create
    Requirement 7.1: Bind the subject to the applicable published Study_Version.
    """
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "subject.create",
        study_id=study_id,
        site_id=body.site_id,
    )
    subject = await subject_service.create_subject(
        session=session, study_id=study_id, data=body, actor_id=current_user.id
    )
    await sdr_service.materialize(session, study_id)
    return SubjectResponse.model_validate(subject)


@study_subjects_router.get(
    "/{study_id}/subjects/enrollment-readiness",
    response_model=SubjectEnrollmentReadinessResponse,
)
async def subject_enrollment_readiness(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectEnrollmentReadinessResponse:
    """Return prerequisites for enrolling a subject in this study."""
    authorized_site_ids = edc_scope_service.authorized_site_ids(
        current_user,
        permission_service,
        "subject.create",
        study_id,
    )
    readiness = await subject_service.enrollment_readiness(
        session,
        study_id,
        authorized_site_ids=authorized_site_ids,
    )
    return SubjectEnrollmentReadinessResponse.model_validate(readiness)


# ---------------------------------------------------------------------------
# Single-subject operations (mounted at /subjects)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("/{subject_id}", response_model=SubjectResponse)
async def get_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Get a subject by ID.

    Permission: subject.read
    """
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.read"
    )
    return SubjectResponse.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: UUID,
    body: SubjectUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Update subject metadata (partial PATCH).

    Permission: subject.update
    Requirement 7.6: Subject metadata changes write Audit_Events.
    """
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )

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


@router.delete("/{subject_id}", response_model=SubjectResponse)
async def delete_subject(
    subject_id: UUID,
    body: SubjectDelete,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Soft-delete a Screening subject that was entered in error."""
    subject = await _authorized_subject(
        session,
        subject_id,
        current_user,
        permission_service,
        "subject.delete",
    )
    removed = await subject_service.soft_delete(
        session,
        subject,
        body.reason,
        current_user.id,
        subject_number_confirmation=body.subject_number_confirmation,
    )
    return SubjectResponse.model_validate(removed)


@router.post("/{subject_id}/restore", response_model=SubjectResponse)
async def restore_subject(
    subject_id: UUID,
    body: SubjectRestore,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Restore a retained subject after an erroneous removal."""
    subject = await _authorized_subject(
        session,
        subject_id,
        current_user,
        permission_service,
        "subject.restore",
        include_deleted=True,
    )
    restored = await subject_service.restore(
        session,
        subject,
        body.reason,
        current_user.id,
    )
    return SubjectResponse.model_validate(restored)


@router.post("/{subject_id}/switch-site", response_model=SubjectResponse)
async def switch_subject_site(
    subject_id: UUID,
    body: SubjectSiteTransfer,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Move an eligible Screening subject between active Sites in one Study."""
    subject = await _authorized_subject(
        session,
        subject_id,
        current_user,
        permission_service,
        "subject.transfer",
    )
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "subject.transfer",
        study_id=subject.study_id,
        site_id=body.site_id,
    )
    transferred = await subject_service.switch_site(
        session,
        subject,
        site_id=body.site_id,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return SubjectResponse.model_validate(transferred)


@router.get("/{subject_id}/phase", response_model=SubjectPhaseStateResponse)
async def get_subject_phase(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectPhaseStateResponse:
    """Return the subject's phase/arm state and published configuration."""
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.read"
    )
    return SubjectPhaseStateResponse.model_validate(
        await subject_service.get_phase_state(session, subject)
    )


@router.patch("/{subject_id}/phase", response_model=SubjectPhaseStateResponse)
async def update_subject_phase(
    subject_id: UUID,
    body: SubjectPhaseUpdate,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectPhaseStateResponse:
    """Update the current phase, requiring an arm choice for arm phases."""
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
    await subject_service.update_phase(
        session,
        subject,
        phase_definition_id=body.phase_definition_id,
        arm_definition_id=body.arm_definition_id,
        actor_id=current_user.id,
    )
    return SubjectPhaseStateResponse.model_validate(
        await subject_service.get_phase_state(session, subject)
    )


@router.post("/{subject_id}/phase/reverse", response_model=SubjectPhaseStateResponse)
async def reverse_subject_phase(
    subject_id: UUID,
    body: SubjectPhaseReverse,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectPhaseStateResponse:
    """Reverse the subject to the immediately preceding audited phase."""
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
    await subject_service.reverse_phase(
        session,
        subject,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return SubjectPhaseStateResponse.model_validate(
        await subject_service.get_phase_state(session, subject)
    )


# ---------------------------------------------------------------------------
# Status transition convenience endpoints (Requirement 7.3)
# ---------------------------------------------------------------------------


@router.post("/{subject_id}/screen-fail", response_model=SubjectResponse)
async def screen_fail_subject(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Transition a subject to Screen Failed.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Transition a subject to Randomized.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
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
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Transition a subject to Early Terminated.

    Permission: subject.update
    Requirement 7.3: Enforced via the subject state machine.
    """
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.early_terminated,
        actor_id=current_user.id,
    )
    return SubjectResponse.model_validate(updated)


@router.post("/{subject_id}/deactivate", response_model=SubjectResponse)
async def deactivate_subject(
    subject_id: UUID,
    body: SubjectLifecycleChange,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Transition a subject to Inactive with an audited reason."""
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.inactive,
        actor_id=current_user.id,
        reason=body.reason,
    )
    return SubjectResponse.model_validate(updated)


@router.post("/{subject_id}/discontinue", response_model=SubjectResponse)
async def discontinue_subject(
    subject_id: UUID,
    body: SubjectLifecycleChange,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> SubjectResponse:
    """Transition a subject to Discontinued with an audited reason."""
    subject = await _authorized_subject(
        session, subject_id, current_user, permission_service, "subject.update"
    )
    updated = await subject_service.transition_status(
        session=session,
        subject=subject,
        target_status=SubjectStatus.discontinued,
        actor_id=current_user.id,
        reason=body.reason,
    )
    return SubjectResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Casebook (Requirement 7.5)
# ---------------------------------------------------------------------------


@router.get("/{subject_id}/casebook", response_model=CasebookResponse)
async def get_subject_casebook(
    subject_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(get_current_user)],
    permission_service: Annotated[PermissionService, Depends(get_permission_service)],
) -> CasebookResponse:
    """Get the subject casebook (visit/form structure with clinical status).

    Permission: subject.read
    Requirement 7.5: Return the subject casebook.
    """
    await _authorized_subject(session, subject_id, current_user, permission_service, "subject.read")
    casebook = await subject_service.get_casebook(session, subject_id)
    return CasebookResponse.model_validate(casebook)
