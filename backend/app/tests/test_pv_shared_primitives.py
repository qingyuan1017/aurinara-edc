"""Unit coverage for PV shared-primitive integration and atomic audit writes.

These tests exercise the real ``PVAtomicityService``, ``AuditService``, and the
``PVSharedIntegrationService`` facade against a deterministic in-memory
transaction fake. No database, queue, object storage, or other external service
is used.

Covers task 1.6 behavior for Requirements 11.1, 11.2, 11.3, 11.6, 11.7, 16.4,
18.1, 18.2, 18.3:

* a PV Safety_Data mutation and its PV safety Audit_Event commit or roll back
  together;
* a forced audit-write failure leaves no PV state and no Audit_Event;
* PV Audit_Events are tagged ``module="PV"`` and carry actor/UTC-timestamp/
  entity/action plus applicable old/new values and reason;
* completed Audit_Events are immutable;
* shared notification/file/export/coordination primitives are reused with PV
  content semantics kept separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.pv import ActorContext, Module
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CTMSOutbox
from app.models.notification import Notification, NotificationStatus
from app.services.pv_atomicity_service import PVAtomicityService, pv_atomicity_service
from app.services.pv_shared_integration import PVSharedIntegrationService


class ExpectedFlushError(RuntimeError):
    """Raised by the fake at a chosen transaction boundary."""


@dataclass
class InMemoryTransaction:
    """Small unit-of-work fake with commit/rollback semantics."""

    failure_flush: int | None = None
    pending: list[Any] = field(default_factory=list)
    committed: list[Any] = field(default_factory=list)
    flush_count: int = 0
    commit_count: int = 0
    rollback_count: int = 0

    def add(self, value: Any) -> None:
        self.pending.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.failure_flush == self.flush_count:
            raise ExpectedFlushError(f"injected flush failure {self.flush_count}")

    async def commit(self) -> None:
        self.commit_count += 1
        self.committed.extend(self.pending)
        self.pending.clear()

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()


def _actor() -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        request_id=str(uuid4()),
        correlation_id=f"corr-{uuid4()}",
    )


def _rows(transaction: InMemoryTransaction, row_type: type[Any]) -> list[Any]:
    return [row for row in transaction.committed if isinstance(row, row_type)]


@pytest.mark.asyncio
async def test_pv_mutation_writes_audit_event_with_pv_content() -> None:
    """A valid PV mutation records exactly one PV-tagged Audit_Event."""

    transaction = InMemoryTransaction()
    actor = _actor()
    entity_id = uuid4()
    study_id = uuid4()
    site_id = uuid4()
    subject_id = uuid4()

    record = await pv_atomicity_service.record_mutation(
        transaction,
        entity_type="safety_case",
        entity_id=entity_id,
        action="update",
        actor=actor,
        study_id=study_id,
        site_id=site_id,
        subject_id=subject_id,
        changed_fields=["lifecycle_state"],
        field_name="lifecycle_state",
        old_value="Open",
        new_value="In Review",
        reason="Post-submission correction",
    )
    await transaction.commit()

    audits = _rows(transaction, AuditEvent)
    assert len(audits) == 1
    audit = audits[0]
    assert audit is record.audit
    assert record.outbox is None

    # PV content: module, actor, UTC timestamp, entity, action, old/new, reason.
    assert audit.module == "PV"
    assert audit.source_module == "PV"
    assert audit.actor_kind == "user"
    assert audit.actor_id == actor.user_id
    assert audit.entity_type == "safety_case"
    assert audit.entity_id == entity_id
    assert audit.action == "update"
    assert audit.study_id == study_id
    assert audit.site_id == site_id
    assert audit.subject_id == subject_id
    assert audit.old_value == "Open"
    assert audit.new_value == "In Review"
    assert audit.reason == "Post-submission correction"
    assert audit.correlation_id == actor.correlation_id
    assert audit.timestamp.tzinfo is not None
    assert audit.timestamp.utcoffset() == UTC.utcoffset(audit.timestamp)


@pytest.mark.asyncio
async def test_pv_mutation_emits_outbox_row_in_same_transaction() -> None:
    """When coordination is required, the outbox row commits with the audit."""

    transaction = InMemoryTransaction()
    actor = _actor()
    entity_id = uuid4()

    record = await pv_atomicity_service.record_mutation(
        transaction,
        entity_type="safety_case",
        entity_id=entity_id,
        action="projection_request",
        actor=actor,
        emit_outbox=True,
        event_type="PV_SAFETY_PROJECTION_REQUEST",
        payload={
            "case_id": str(entity_id),
            # Nested/structured content is dropped from the shared outbox row.
            "prohibited": {"clinical": "secret"},
        },
    )
    await transaction.commit()

    outboxes = _rows(transaction, CTMSOutbox)
    audits = _rows(transaction, AuditEvent)
    assert len(outboxes) == 1
    assert len(audits) == 1
    outbox = outboxes[0]
    assert record.outbox is outbox
    assert outbox.module == "PV"
    assert outbox.source_module == "PV"
    assert outbox.correlation_id == actor.correlation_id
    # Only scalar payload survives sanitization.
    assert outbox.payload_json == {"case_id": str(entity_id)}


@pytest.mark.asyncio
async def test_pv_mutation_rolls_back_when_audit_write_fails() -> None:
    """A forced audit-flush failure leaves no PV state and no Audit_Event."""

    # Two flush boundaries occur: the aggregate flush the caller performs, then
    # the audit flush inside record_mutation. Fail the audit flush.
    transaction = InMemoryTransaction(failure_flush=2)
    actor = _actor()
    entity_id = uuid4()

    @dataclass
    class FakeSafetyCase:
        id: UUID
        lifecycle_state: str

    aggregate = FakeSafetyCase(id=entity_id, lifecycle_state="In Review")
    transaction.add(aggregate)
    await transaction.flush()  # flush #1: aggregate

    with pytest.raises(ExpectedFlushError):
        await pv_atomicity_service.record_mutation(
            transaction,
            entity_type="safety_case",
            entity_id=entity_id,
            action="update",
            actor=actor,
            old_value="Open",
            new_value="In Review",
        )
    await transaction.rollback()

    assert transaction.committed == []
    assert transaction.pending == []
    assert transaction.commit_count == 0
    assert transaction.rollback_count == 1
    assert _rows(transaction, AuditEvent) == []


@pytest.mark.asyncio
async def test_completed_pv_audit_event_is_immutable() -> None:
    """A recorded PV Audit_Event cannot be updated or deleted."""

    audit = AuditEvent(
        actor_id=uuid4(),
        entity_type="safety_case",
        entity_id=uuid4(),
        module="PV",
        action="create",
        request_id=uuid4(),
    )

    from app.models.audit import _reject_audit_mutation

    with pytest.raises(ValueError, match="immutable"):
        _reject_audit_mutation(None, None, audit)


@pytest.mark.asyncio
async def test_pv_notification_reuses_shared_state_with_pv_module() -> None:
    """PV notifications reuse the shared table and delivery statuses, tagged PV."""

    transaction = InMemoryTransaction()
    integration = PVSharedIntegrationService()
    user_id = uuid4()
    study_id = uuid4()

    notifications = await integration.create_pv_notification(
        transaction,
        user_ids=[user_id, user_id],  # duplicate recipient collapses to one
        notification_type="pv_serious_case_created",
        payload={"case_id": uuid4(), "count": 1},
        study_id=study_id,
    )
    await transaction.commit()

    assert len(notifications) == 1
    notification = notifications[0]
    assert isinstance(notification, Notification)
    assert notification.module == Module.PV.value
    assert notification.status == NotificationStatus.unread
    assert notification.study_id == study_id
    # UUID payload values are stringified for safe JSON storage.
    assert isinstance(notification.payload_json["case_id"], str)


@pytest.mark.asyncio
async def test_pv_attachment_action_records_atomic_audit_event() -> None:
    """A completed attachment action records exactly one PV Audit_Event."""

    transaction = InMemoryTransaction()
    integration = PVSharedIntegrationService()
    actor = _actor()
    attachment_id = uuid4()
    case_id = uuid4()

    record = await integration.record_attachment_action(
        transaction,
        attachment_id=attachment_id,
        action="upload",
        actor=actor,
        study_id=uuid4(),
        site_id=uuid4(),
        case_id=case_id,
    )
    await transaction.commit()

    audits = _rows(transaction, AuditEvent)
    assert len(audits) == 1
    audit = audits[0]
    assert audit is record.audit
    assert audit.module == "PV"
    assert audit.entity_type == "safety_attachment"
    assert audit.entity_id == attachment_id
    assert audit.action == "upload"
    assert audit.new_value == str(case_id)


@pytest.mark.asyncio
async def test_pv_export_download_records_audit_event() -> None:
    """An authorized export download records one PV download Audit_Event."""

    transaction = InMemoryTransaction()
    integration = PVSharedIntegrationService()
    actor = _actor()
    job_id = uuid4()

    await integration.record_export_download(
        transaction,
        export_job_id=job_id,
        actor=actor,
    )
    await transaction.commit()

    audits = _rows(transaction, AuditEvent)
    assert len(audits) == 1
    assert audits[0].module == "PV"
    assert audits[0].entity_type == "safety_export_job"
    assert audits[0].action == "download"


@pytest.mark.asyncio
async def test_service_singletons_are_shared_instances() -> None:
    """The module exposes reusable singletons of the concrete service types."""

    assert isinstance(pv_atomicity_service, PVAtomicityService)
    from app.services.pv_shared_integration import pv_shared_integration_service

    assert isinstance(pv_shared_integration_service, PVSharedIntegrationService)
