"""Retention and remediation records owned by the CTMS coordination boundary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.ctms.coordination import JSONBType


def utc_now() -> datetime:
    return datetime.now(UTC)


class CTMSRetentionAction(Base):
    """Immutable actor/time/reason ledger for every retention lifecycle action."""

    __tablename__ = "ctms_retention_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module: Mapped[str] = mapped_column(String(20), nullable=False, default="CTMS")

    __table_args__ = (
        Index("ix_ctms_retention_actions_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_ctms_retention_actions_action", "action", "occurred_at"),
    )


class CTMSFailedEvent(Base):
    """Durable sanitized Failed_Event record retained independently of payloads."""

    __tablename__ = "ctms_failed_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_coordination_events.event_id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    sanitized_details_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("ix_ctms_failed_events_retention", "retention_state", "created_at"),)


class CTMSCoordinationConflict(Base):
    """Sanitized coordination conflict with independent retention state."""

    __tablename__ = "ctms_coordination_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    conflict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    field_path: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sanitized_details_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    source_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (Index("ix_ctms_coordination_conflicts_retention", "retention_state", "created_at"),)


# Public names matching the specification vocabulary.
FailedEvent = CTMSFailedEvent
CoordinationConflict = CTMSCoordinationConflict


def _reject_retention_action_mutation(_mapper: Any, connection: Any, target: CTMSRetentionAction) -> None:
    del connection, target
    raise ValueError("Retention action history is immutable")


event.listen(CTMSRetentionAction, "before_update", _reject_retention_action_mutation)
event.listen(CTMSRetentionAction, "before_delete", _reject_retention_action_mutation)


__all__ = [
    "CTMSCoordinationConflict",
    "CTMSFailedEvent",
    "CTMSRetentionAction",
    "CoordinationConflict",
    "FailedEvent",
]
