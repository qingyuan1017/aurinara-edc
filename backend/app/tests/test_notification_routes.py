"""Focused route tests for the authenticated notification inbox.

Validates Requirements 28.4, 28.5, and 21.1-21.3.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.api.deps import PaginationParams
from app.api.routes.notifications import (
    archive_notification,
    list_notifications,
    mark_notification_read,
)
from app.main import create_app
from app.models.notification import Notification, NotificationStatus
from app.schemas.base import PaginatedResponse


def _notification(user_id, *, status=NotificationStatus.unread):
    return Notification(
        id=uuid4(),
        user_id=user_id,
        type="query_assigned",
        payload_json={"query_id": str(uuid4())},
        status=status,
        created_at=datetime.now(UTC),
    )


async def test_list_route_delegates_current_user_and_returns_pagination(monkeypatch):
    user = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    item = _notification(user.id)
    result = PaginatedResponse(
        items=[item],
        page=2,
        page_size=1,
        total=3,
    )
    service = SimpleNamespace(list_unread_paginated=AsyncMock(return_value=result))
    monkeypatch.setattr(
        "app.api.routes.notifications.notification_service", service
    )

    response = await list_notifications(
        session, user, PaginationParams(page=2, page_size=1)
    )

    assert response.page == 2
    assert response.page_size == 1
    assert response.total == 3
    assert response.items[0].user_id == user.id
    service.list_unread_paginated.assert_awaited_once_with(
        session, user, PaginationParams(page=2, page_size=1)
    )


async def test_read_and_archive_routes_delegate_current_user(monkeypatch):
    user = SimpleNamespace(id=uuid4())
    session = AsyncMock()
    notification_id = uuid4()
    read_item = _notification(user.id, status=NotificationStatus.read)
    archived_item = _notification(user.id, status=NotificationStatus.archived)
    service = SimpleNamespace(
        mark_read=AsyncMock(return_value=read_item),
        archive=AsyncMock(return_value=archived_item),
    )
    monkeypatch.setattr(
        "app.api.routes.notifications.notification_service", service
    )

    read_response = await mark_notification_read(notification_id, session, user)
    archive_response = await archive_notification(notification_id, session, user)

    assert read_response.status == NotificationStatus.read
    assert archive_response.status == NotificationStatus.archived
    service.mark_read.assert_awaited_once_with(session, notification_id, user)
    service.archive.assert_awaited_once_with(session, notification_id, user)


def test_notification_routes_are_registered_under_api_v1():
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/api/v1/notifications" in paths
    assert "/api/v1/notifications/{notification_id}/read" in paths
    assert "/api/v1/notifications/{notification_id}/archive" in paths
    assert "get" in paths["/api/v1/notifications"]
    assert "post" in paths["/api/v1/notifications/{notification_id}/read"]
    assert "post" in paths["/api/v1/notifications/{notification_id}/archive"]
