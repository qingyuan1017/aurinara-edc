"""Focused tests for CTMS task 5.5 notifications and resilience."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.metrics import get_metrics
from app.models.ctms.coordination import CTMSOutbox
from app.models.notification import NotificationStatus
from app.services.coordination_service import BoundedCoordinationQueue, CoordinationService
from app.services.ctms_health_service import CTMSHealthService
from app.services.notification_service import NotificationService
from app.workers.coordination_worker import CoordinationWorker


def _session(rows=()):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    result.scalars.return_value.first.return_value = next(iter(rows), None)
    session.execute = AsyncMock(return_value=result)
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_monitoring_notifications_use_assignee_and_scope():
    service = NotificationService()
    cra_id, operations_id = uuid4(), uuid4()
    study_id, site_id = uuid4(), uuid4()
    activity = SimpleNamespace(
        id=uuid4(), study_id=study_id, site_id=site_id, assigned_cra_id=cra_id,
        planned_date=datetime.now(UTC), correlation_id="corr",
    )

    direct = await service.on_monitoring_assigned(_session(), activity)
    assert [item.user_id for item in direct] == [cra_id]
    assert direct[0].status == NotificationStatus.unread
    assert direct[0].type == "ctms_monitoring_assigned"

    scoped = await service.on_monitoring_overdue(_session([operations_id]), activity)
    assert [item.user_id for item in scoped] == [operations_id]
    assert scoped[0].study_id == study_id
    assert scoped[0].site_id == site_id
    assert scoped[0].type == "ctms_monitoring_overdue"


@pytest.mark.asyncio
async def test_failed_event_notification_redacts_payload():
    service = NotificationService()
    admin_id, study_id = uuid4(), uuid4()
    event = SimpleNamespace(
        id=uuid4(), event_id=uuid4(), event_type="projection",
        correlation_id="corr", last_error_category="RECORD_NOT_FOUND",
        payload_json={"study_id": str(study_id), "clinical_value": "must-not-leak"},
    )
    notifications = await service.on_failed_event(_session([admin_id]), event)
    assert notifications[0].user_id == admin_id
    assert notifications[0].payload_json["reason_code"] == "RECORD_NOT_FOUND"
    assert "clinical_value" not in str(notifications[0].payload_json)


def test_bounded_queue_applies_backpressure_without_rejecting_durable_ids():
    queue = BoundedCoordinationQueue(capacity=1)
    first, second = uuid4(), uuid4()
    assert queue.try_enqueue(first)
    assert not queue.try_enqueue(second)
    assert queue.saturated
    queue.complete(first)
    assert queue.try_enqueue(second)


def test_health_snapshot_is_sanitized_and_reports_queue_state():
    health = CTMSHealthService()
    health.set_worker_status("unavailable")
    health.set_queue_state(2, 2, saturated=True)
    snapshot = health.snapshot()
    assert snapshot["worker_status"] == "unavailable"
    assert snapshot["queue"] == {"queued_count": 2, "capacity": 2, "backpressure": True}
    assert "payload" not in str(snapshot).lower()
    assert "clinical" not in str(snapshot).lower()


@pytest.mark.asyncio
async def test_worker_outage_leaves_event_pending_and_failed_is_bounded():
    get_metrics().reset()
    service = CoordinationService(queue=BoundedCoordinationQueue(capacity=2))
    worker = CoordinationWorker(max_attempts=2)
    event = CTMSOutbox(
        event_id=uuid4(), aggregate_type="subject", aggregate_id=uuid4(),
        event_type="projection", module="EDC", correlation_id="corr",
        payload_json={}, available_at=datetime.now(UTC), attempt_count=2,
        status="Pending",
    )
    worker.unavailable()
    assert service.queue.size == 0
    assert event.status == "Pending"
    session = _session()
    failed = await worker.mark_failed(session, event, reason="RETRY_EXHAUSTED")
    assert failed.status == "Failed"
    assert failed.last_error_category == "RETRY_EXHAUSTED"
    assert get_metrics().ctms_snapshot()["failed_event_count"] == 1
    worker.available()
