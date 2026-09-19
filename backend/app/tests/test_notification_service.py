"""Focused tests for NotificationService and workflow event payloads.

Validates Requirements 28.1-28.5.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AuthorizationError, BusinessRuleError
from app.models.export import Export, ExportStatus, ExportType
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.notification import Notification, NotificationStatus
from app.models.query import Query, QueryTargetType, QueryType
from app.services.notification_service import NotificationService


@pytest.fixture
def service():
    return NotificationService()


def _session_with_scalar_rows(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.scalars.return_value.first.return_value = rows[0] if rows else None
    session.execute = AsyncMock(return_value=result)
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    return session


def _query(*, assigned_role: str | None = "Medical Reviewer") -> Query:
    return Query(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        target_type=QueryTargetType.form_instance,
        target_id=uuid.uuid4(),
        text="Please clarify",
        query_type=QueryType.manual,
        assigned_role=assigned_role,
        created_by=uuid.uuid4(),
    )


async def test_query_assignment_creates_unread_notifications(service):
    """Assigned role members receive one unread notification each (28.1)."""
    recipient_ids = [uuid.uuid4(), uuid.uuid4()]
    session = _session_with_scalar_rows(recipient_ids)
    query = _query()

    notifications = await service.on_query_assigned(session, query)

    assert [item.user_id for item in notifications] == recipient_ids
    assert all(item.status == NotificationStatus.unread for item in notifications)
    assert all(item.type == "query_assigned" for item in notifications)
    assert notifications[0].payload_json["query_id"] == str(query.id)
    session.add_all.assert_called_once_with(notifications)
    session.flush.assert_awaited_once()


async def test_unassigned_query_does_not_guess_recipients(service):
    """Queries without an assigned role do not notify an unrelated role."""
    session = _session_with_scalar_rows([uuid.uuid4()])
    query = _query(assigned_role=None)

    assert await service.on_query_assigned(session, query) == []
    session.execute.assert_not_awaited()
    session.add_all.assert_not_called()


async def test_form_submission_notifies_reviewers(service):
    """Medical reviewers in the form's scope receive a submission event (28.2)."""
    reviewer_id = uuid.uuid4()
    session = _session_with_scalar_rows([reviewer_id])
    form = FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=FormInstanceStatus.submitted,
        submitted_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    form.__dict__["subject"] = SimpleNamespace(
        study_id=uuid.uuid4(), site_id=uuid.uuid4()
    )

    notifications = await service.on_form_submitted(session, form)

    assert len(notifications) == 1
    assert notifications[0].user_id == reviewer_id
    assert notifications[0].type == "form_submitted"
    assert notifications[0].payload_json["form_instance_id"] == str(form.id)


async def test_export_completion_notifies_requester(service):
    """The requesting user receives an export completion event (28.3)."""
    requester_id = uuid.uuid4()
    session = _session_with_scalar_rows([])
    export = Export(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        export_type=ExportType.csv,
        status=ExportStatus.completed,
        requested_by=requester_id,
        file_path="exports/result.csv",
        file_size=42,
        created_at=datetime.now(UTC),
    )

    notifications = await service.on_export_completed(session, export)

    assert len(notifications) == 1
    assert notifications[0].user_id == requester_id
    assert notifications[0].type == "export_completed"
    assert notifications[0].payload_json["export_id"] == str(export.id)


async def test_list_unread_is_recipient_and_status_scoped(service):
    """Unread listing queries only the requested user's unread records (28.5)."""
    user_id = uuid.uuid4()
    unread = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type="export_completed",
        payload_json={},
        status=NotificationStatus.unread,
        created_at=datetime.now(UTC),
    )
    session = _session_with_scalar_rows([unread])

    result = await service.list_unread(session, user_id)

    assert result == [unread]
    statement = session.execute.call_args.args[0]
    assert "notifications" in str(statement)
    assert "status" in str(statement)


async def test_notification_state_transitions_enforce_ownership(service):
    """Read and archive transitions preserve ownership and lifecycle rules (28.4)."""
    user_id = uuid.uuid4()
    notification = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type="query_assigned",
        payload_json={},
        status=NotificationStatus.unread,
        created_at=datetime.now(UTC),
    )
    session = AsyncMock()
    session.flush = AsyncMock()

    await service.mark_read(session, notification, user_id)
    assert notification.status == NotificationStatus.read
    assert notification.read_at is not None

    await service.archive(session, notification, user_id)
    assert notification.status == NotificationStatus.archived

    with pytest.raises(BusinessRuleError):
        await service.mark_read(session, notification, user_id)

    with pytest.raises(AuthorizationError):
        await service.archive(session, notification, uuid.uuid4())
