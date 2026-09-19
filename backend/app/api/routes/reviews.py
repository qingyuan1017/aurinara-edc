"""Clinical review routes.

Review mutations load the target form first, then enforce ``review.manage``
against the form's owning study and site before delegating to ReviewService.
The service uses the injected session for both the review row and its audit
event; the get_db dependency commits or rolls back that transaction.

Endpoints:
  - POST /form-instances/{form_instance_id}/review
  - POST /form-instances/{form_instance_id}/unreview
  - GET  /studies/{study_id}/review-progress
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db, get_permission_service, require_permission
from app.models.form_data import FormInstance
from app.models.identity import User
from app.schemas.review import ReviewProgressResponse, ReviewStatusResponse
from app.services.data_capture_service import data_capture_service
from app.services.permission_service import PermissionService
from app.services.review_service import review_service

DbSession = Annotated[AsyncSession, Depends(get_db)]

router = APIRouter(prefix="/form-instances", tags=["review"])
study_router = APIRouter(prefix="/studies", tags=["review"])


async def _load_authorized_form(
    session: AsyncSession,
    form_instance_id: UUID,
    current_user: User,
    permission_service: PermissionService,
) -> FormInstance:
    """Load a form and enforce review permission at its object scope."""
    form_instance = await data_capture_service.load(session, form_instance_id)
    subject = form_instance.subject
    permission_service.require(
        current_user,
        "review.manage",
        study_id=subject.study_id,
        site_id=subject.site_id,
    )
    return form_instance


@router.post(
    "/{form_instance_id}/review",
    response_model=ReviewStatusResponse,
)
async def mark_form_reviewed(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: Annotated[
        PermissionService, Depends(get_permission_service)
    ],
) -> ReviewStatusResponse:
    """Mark a form instance as reviewed."""
    form_instance = await _load_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    status = await review_service.mark_reviewed(
        session, form_instance, actor_id=current_user
    )
    return ReviewStatusResponse.model_validate(status)


@router.post(
    "/{form_instance_id}/unreview",
    response_model=ReviewStatusResponse,
)
async def unreview_form(
    form_instance_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: Annotated[
        PermissionService, Depends(get_permission_service)
    ],
) -> ReviewStatusResponse:
    """Clear review state for a form instance."""
    form_instance = await _load_authorized_form(
        session, form_instance_id, current_user, permission_service
    )
    status = await review_service.clear_review(
        session, form_instance, actor_id=current_user
    )
    return ReviewStatusResponse.model_validate(status)


@study_router.get(
    "/{study_id}/review-progress",
    response_model=ReviewProgressResponse,
)
async def get_review_progress(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("review.manage"))],
) -> ReviewProgressResponse:
    """Return reviewed and not-reviewed form counts for a study."""
    counts = await review_service.progress(session, study_id=study_id)
    return ReviewProgressResponse.model_validate(counts)


__all__ = ["router", "study_router"]
