"""Notification routes for the authenticated user's workflow inbox.

The NotificationService owns recipient filtering, ownership checks, and state
transitions. These handlers only resolve the current user, pass validated input
to that service, and serialize the standard API responses.

Satisfies Requirements 28.4, 28.5, and 21.1-21.3.

Endpoints:
  - GET  /notifications                         list unread notifications
  - POST /notifications/{notification_id}/read  mark an owned notification read
  - POST /notifications/{notification_id}/archive archive an owned notification
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db
from app.models.identity import User
from app.models.notification import NotificationStatus
from app.schemas.base import PaginatedResponse
from app.schemas.notification import NotificationResponse
from app.services.notification_service import notification_service

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedResponse[NotificationResponse])
async def list_notifications(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: NotificationStatus | None = None,
    study_id: UUID | None = None,
    site_id: UUID | None = None,
) -> PaginatedResponse[NotificationResponse]:
    """List owned notifications, optionally filtered by CTMS scope/state."""
    if status is None and study_id is None and site_id is None:
        result = await notification_service.list_unread_paginated(
            session, current_user, pagination
        )
    else:
        notifications = await notification_service.list_for_user(
            session,
            current_user,
            statuses={status} if status is not None else None,
            study_id=study_id,
            site_id=site_id,
        )
        start = pagination.offset
        result = PaginatedResponse(
            items=notifications[start : start + pagination.page_size],
            page=pagination.page,
            page_size=pagination.page_size,
            total=len(notifications),
        )
    return PaginatedResponse[NotificationResponse](
        items=[NotificationResponse.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
async def mark_notification_read(
    notification_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> NotificationResponse:
    """Mark an owned unread notification as read."""
    notification = await notification_service.mark_read(
        session, notification_id, current_user
    )
    return NotificationResponse.model_validate(notification)


@router.post(
    "/{notification_id}/archive",
    response_model=NotificationResponse,
)
async def archive_notification(
    notification_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> NotificationResponse:
    """Archive an owned unread or read notification."""
    notification = await notification_service.archive(
        session, notification_id, current_user
    )
    return NotificationResponse.model_validate(notification)


__all__ = ["router"]
