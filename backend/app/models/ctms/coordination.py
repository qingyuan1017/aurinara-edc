"""CTMS coordination events, transactional outbox, and immutable outcomes."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class CoordinationEventStatus(enum.StrEnum):
    """Durable lifecycle states for one accepted coordination event."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    FAILED = "failed"
    CONFLICT = "conflict"


_TERMINAL_EVENT_STATUSES = frozenset(
    {
        CoordinationEventStatus.SUCCEEDED.value,
        CoordinationEventStatus.SKIPPED.value,
        CoordinationEventStatus.FAILED.value,
        CoordinationEventStatus.CONFLICT.value,
        # Existing CTMS rows use title-case publication statuses.
        "Published",
        "Failed",
        "Conflict",
    }
)


class CTMSStatusHistory(Base):
    """Append-only operational status transition history."""

    __tablename__ = "ctms_status_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        Index("ix_ctms_status_history_entity", "entity_type", "entity_id", "changed_at"),
        Index("ix_ctms_status_history_correlation", "correlation_id"),
    )


class CTMSCoordinationEvent(Base):
    """Immutable source event metadata and its current processing state."""

    __tablename__ = "ctms_coordination_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_module: Mapped[str] = mapped_column(String(20), nullable=False)
    target_module: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    target_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    target_projection_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    allowlist_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CoordinationEventStatus.ACCEPTED.value)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resulting_projection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    current_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sanitized_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_module", "idempotency_key", name="uq_ctms_coordination_event_idempotency"),
        CheckConstraint("source_module IN ('EDC', 'CTMS')", name="ck_ctms_coordination_event_source_module"),
        CheckConstraint("target_module IN ('EDC', 'CTMS')", name="ck_ctms_coordination_event_target_module"),
        CheckConstraint("source_sequence IS NULL OR source_sequence >= 0", name="ck_ctms_coordination_event_source_sequence"),
        CheckConstraint("rule_version > 0", name="ck_ctms_coordination_event_rule_version"),
        CheckConstraint(
            "status IN ('accepted', 'queued', 'processing', 'succeeded', 'skipped', 'retrying', 'failed', 'conflict')",
            name="ck_ctms_coordination_event_status",
        ),
        Index("ix_ctms_coordination_event_order", "source_module", "entity_type", "source_record_id", "source_sequence", "source_version"),
        Index("ix_ctms_coordination_event_status", "status", "accepted_at"),
        Index("ix_ctms_coordination_event_correlation", "correlation_id"),
    )


# Short names are the public model contract used by services and tests.
CoordinationEvent = CTMSCoordinationEvent


class CTMSEventAttempt(Base):
    """One sanitized worker attempt for a coordination event."""

    __tablename__ = "ctms_event_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_coordination_events.event_id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sanitized_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "attempt_number", name="uq_ctms_event_attempt_number"),
        Index("ix_ctms_event_attempt_event", "event_id", "attempt_number"),
    )


EventAttempt = CTMSEventAttempt


class CTMSCoordinationEventLog(Base):
    """Immutable completed processing record for one coordination event."""

    __tablename__ = "ctms_coordination_event_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_coordination_events.event_id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    source_module: Mapped[str] = mapped_column(String(20), nullable=False)
    target_module: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    target_projection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    current_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    sanitized_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint("outcome IN ('succeeded', 'skipped', 'retrying', 'failed', 'conflict')", name="ck_ctms_event_log_outcome"),
        Index("ix_ctms_event_log_source", "source_module", "entity_type", "source_record_id", "source_sequence"),
        Index("ix_ctms_event_log_correlation", "correlation_id"),
    )


CoordinationEventLog = CTMSCoordinationEventLog


def _reject_completed_log_mutation(_mapper: Any, connection: Any, target: CTMSCoordinationEventLog) -> None:
    del connection
    if target.completed_at is not None:
        raise ValueError("Completed coordination event logs are immutable")


def _reject_event_log_delete(_mapper: Any, connection: Any, target: CTMSCoordinationEventLog) -> None:
    del connection
    if target.completed_at is not None:
        raise ValueError("Completed coordination event logs cannot be deleted")


event.listen(CTMSCoordinationEventLog, "before_update", _reject_completed_log_mutation)
event.listen(CTMSCoordinationEventLog, "before_delete", _reject_event_log_delete)


class CTMSOutbox(Base):
    """Transactional delivery row retained for existing CTMS producers."""

    __tablename__ = "ctms_outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    coordination_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False, default="CTMS")
    source_module: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_module: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    target_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    target_projection_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowlist_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    payload_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resulting_projection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    current_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sanitized_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_ctms_outbox_status_available", "status", "available_at"),
        Index("ix_ctms_outbox_correlation", "correlation_id"),
        Index("ix_ctms_outbox_source_order", "source_module", "aggregate_type", "source_record_id", "source_sequence", "source_version", "event_id"),
    )


__all__ = [
    "CTMSCoordinationEvent",
    "CTMSCoordinationEventLog",
    "CTMSEventAttempt",
    "CTMSOutbox",
    "CTMSStatusHistory",
    "CoordinationEvent",
    "CoordinationEventLog",
    "CoordinationEventStatus",
    "EventAttempt",
]
