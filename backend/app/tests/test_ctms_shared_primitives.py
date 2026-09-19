"""Unit coverage for shared CTMS audit and transaction primitives."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.audit import AuditService
from app.core.ctms import Module
from app.services.ctms_atomicity_service import CTMSAtomicityService


@pytest.mark.asyncio
async def test_audit_record_preserves_ctms_actor_scope_and_changed_fields():
    session = AsyncMock()
    session.add = MagicMock()
    event = await AuditService().record(
        session,
        entity_type="operational_task",
        entity_id=uuid4(),
        action="update",
        module=Module.CTMS,
        actor_kind="worker",
        worker_id="ctms-worker-1",
        correlation_id="corr-123",
        scope={"study_id": uuid4(), "site_id": uuid4()},
        changed_fields=["status", "due_date"],
        actor_id=uuid4(),
    )

    assert event.module == "CTMS"
    assert event.actor_kind == "worker"
    assert event.worker_id == "ctms-worker-1"
    assert event.correlation_id == "corr-123"
    assert set(event.scope_json) == {"study_id", "site_id"}
    assert event.changed_fields == ["status", "due_date"]
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_ctms_mutation_writes_history_audit_and_outbox_without_commit(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    audit_event = object()
    audit_record = AsyncMock(return_value=audit_event)
    monkeypatch.setattr("app.services.ctms_atomicity_service.audit_service.record", audit_record)

    history, outbox, audit = await CTMSAtomicityService().record_mutation(
        session,
        entity_type="operational_study",
        entity_id=uuid4(),
        study_id=uuid4(),
        site_id=None,
        actor_id=uuid4(),
        correlation_id="corr-456",
        action="status_transition",
        previous_status="Planning",
        status="Ready",
        reason="Readiness criteria met",
        changed_fields=["status"],
        payload={"status": "Ready", "clinical_value": {"must": "not persist"}},
    )

    assert history is not None
    assert outbox.module == "CTMS"
    assert outbox.correlation_id == "corr-456"
    assert outbox.payload_json == {"status": "Ready"}
    assert audit is audit_event
    assert session.add.call_count == 2
    session.commit.assert_not_called()
    audit_record.assert_awaited_once()
    assert audit_record.await_args.kwargs["module"] is Module.CTMS
    assert audit_record.await_args.kwargs["correlation_id"] == "corr-456"
