"""Study and Study Version routes.

Satisfies Requirements:
  - 4.1: CRUD for study metadata (code, protocol, title, sponsor, phase, etc.).
  - 4.3: Study status transitions via POST /studies/{study_id}/transition.
  - 5.1: Publish a draft Study_Version via POST /versions/{version_id}/publish.
  - 21.1: All endpoints mounted under /api/v1.
  - 21.2: List endpoints return pagination envelope.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_permission
from app.core.audit import audit_service
from app.schemas.base import PaginatedResponse
from app.schemas.study import (
    StudyAmendmentCreate,
    StudyCreate,
    StudyResponse,
    StudyStatusTransition,
    StudyUpdate,
    StudyVersionCreate,
    StudyVersionResponse,
)
from app.services.study_service import study_service
from app.services.study_version_service import study_version_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/studies", tags=["studies"])

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Study CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedResponse[StudyResponse])
async def list_studies(
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.read"))],
    pagination: Annotated[PaginationParams, Depends()],
) -> PaginatedResponse[StudyResponse]:
    """List all active studies (paginated).

    Permission: study.read
    Requirement 21.2: Paginated response envelope.
    """
    result = await study_service.list_studies(session, pagination)
    return PaginatedResponse[StudyResponse](
        items=[StudyResponse.model_validate(s) for s in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.post("", response_model=StudyResponse, status_code=201)
async def create_study(
    body: StudyCreate,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.create"))],
) -> StudyResponse:
    """Create a new study.

    Permission: study.create
    Requirement 4.1: Persist study metadata.
    """
    study = await study_service.create_study(
        session=session, data=body, actor_id=current_user.id
    )
    # The initial version is created by the service, but the relationship is
    # not guaranteed to be loaded on this newly-created ORM instance. Load it
    # explicitly before Pydantic reads the response model so async SQLAlchemy
    # does not attempt implicit I/O during serialization.
    await session.refresh(study, attribute_names=["versions"])
    return StudyResponse.model_validate(study)


@router.get("/{study_id}", response_model=StudyResponse)
async def get_study(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.read"))],
) -> StudyResponse:
    """Get a study by ID.

    Permission: study.read
    """
    study = await study_service.get_study(session, study_id)
    return StudyResponse.model_validate(study)


@router.patch("/{study_id}", response_model=StudyResponse)
async def update_study(
    study_id: UUID,
    body: StudyUpdate,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.configure"))],
) -> StudyResponse:
    """Update study metadata (partial PATCH).

    Permission: study.configure
    Requirement 4.5: Write Audit_Event on study metadata changes.
    """
    study = await study_service.get_study(session, study_id)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return StudyResponse.model_validate(study)

    for field_name, new_value in update_data.items():
        old_value = getattr(study, field_name, None)
        setattr(study, field_name, new_value)

        # Audit each changed field (Req 4.5)
        if old_value != new_value:
            await audit_service.record(
                session,
                entity_type="study",
                entity_id=study.id,
                action="update",
                study_id=study.id,
                actor_id=current_user.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
            )

    study.updated_at = datetime.now(UTC)
    await session.flush()

    logger.info("Study updated: id=%s actor=%s", study.id, current_user.id)
    return StudyResponse.model_validate(study)


@router.delete("/{study_id}", status_code=204)
async def delete_study(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.configure"))],
) -> None:
    """Soft-delete a study.

    Permission: study.configure
    Requirement 22.5: Soft-delete via deleted_at timestamp.
    """
    study = await study_service.get_study(session, study_id)

    study.deleted_at = datetime.now(UTC)
    study.updated_at = datetime.now(UTC)
    await session.flush()

    await audit_service.record(
        session,
        entity_type="study",
        entity_id=study.id,
        action="delete",
        study_id=study.id,
        actor_id=current_user.id,
    )

    logger.info("Study soft-deleted: id=%s actor=%s", study.id, current_user.id)


# ---------------------------------------------------------------------------
# Study status transition
# ---------------------------------------------------------------------------


@router.post("/{study_id}/transition", response_model=StudyResponse)
async def transition_study_status(
    study_id: UUID,
    body: StudyStatusTransition,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.configure"))],
) -> StudyResponse:
    """Transition a study's status along the allowed state machine.

    Permission: study.configure
    Requirement 4.3: Draft → UAT → Active → Enrollment Closed → Locked → Archived.
    """
    study = await study_service.get_study(session, study_id)
    updated = await study_service.transition_status(
        session=session,
        study=study,
        target_status=body.target_status,
        actor_id=current_user.id,
    )
    return StudyResponse.model_validate(updated)


# ---------------------------------------------------------------------------
# Study Versions
# ---------------------------------------------------------------------------


@router.get("/{study_id}/versions", response_model=list[StudyVersionResponse])
async def list_versions(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.read"))],
) -> list[StudyVersionResponse]:
    """List all versions of a study.

    Permission: study.read
    Requirement 5.4: Retain all prior published versions for traceability.
    """
    # Ensure study exists
    study = await study_service.get_study(session, study_id)
    return [StudyVersionResponse.model_validate(v) for v in study.versions]


@router.post(
    "/{study_id}/versions", response_model=StudyVersionResponse, status_code=201
)
async def create_version(
    study_id: UUID,
    body: StudyVersionCreate,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.configure"))],
) -> StudyVersionResponse:
    """Create a new draft Study_Version for a study.

    Permission: study.configure
    Requirement 5.3: Create a new draft version (amendment) with reason.
    """
    # Ensure study exists
    await study_service.get_study(session, study_id)

    version = await study_version_service.create_version(
        session=session,
        study_id=study_id,
        version_number=body.version_number,
        amendment_reason=body.amendment_reason,
        actor_id=current_user.id,
    )
    return StudyVersionResponse.model_validate(version)


@router.post(
    "/{study_id}/amend", response_model=StudyVersionResponse, status_code=201
)
async def create_amendment(
    study_id: UUID,
    body: StudyAmendmentCreate,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("study.configure"))],
) -> StudyVersionResponse:
    """Create a draft amendment from the latest published version.

    Permission: study.configure
    Requirements 5.3 and 5.4: retain published history and record the reason.
    """
    study = await study_service.get_study(session, study_id)
    version = await study_version_service.create_amendment(
        session=session,
        study=study,
        reason=body.reason,
        actor_id=current_user.id,
    )
    return StudyVersionResponse.model_validate(version)


# ---------------------------------------------------------------------------
# Version publish (separate prefix — mounted at /versions)
# ---------------------------------------------------------------------------

versions_router = APIRouter(prefix="/versions", tags=["versions"])


@versions_router.post("/{version_id}/publish", response_model=StudyVersionResponse)
async def publish_version(
    version_id: UUID,
    session: DbSession,
    current_user: Annotated[..., Depends(require_permission("version.publish"))],
) -> StudyVersionResponse:
    """Publish a draft Study_Version (draft → published).

    Permission: version.publish
    Requirement 5.1: Transition draft → published, recording actor and timestamp.
    """
    version = await study_version_service.get_version(session, version_id)
    published = await study_version_service.publish(
        session=session, version=version, actor_id=current_user.id
    )
    return StudyVersionResponse.model_validate(published)
