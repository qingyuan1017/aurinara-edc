"""Audit events model — append-only, immutable at the database layer.

Satisfies Requirements:
  - 18.1: Captures actor, timestamp, entity, study, site, subject, action,
           field, old/new value, reason, request_id, ip/user-agent.
  - 18.2: UPDATE/DELETE revoked from app role; trigger raises on modification.
  - 22.4: UUID primary keys.
  - 22.6: Indexed for efficient querying.
  - 25.2: Timestamps are timezone-aware UTC (server clock).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditEvent(Base):
    """Append-only audit event record.

    No service or repository exposes update/delete on this model (application layer).
    The database layer additionally enforces immutability via a BEFORE UPDATE OR DELETE
    trigger and revoked UPDATE/DELETE privileges on the application role.
    """

    __tablename__ = "audit_events"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )

    # Actor
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, comment="FK to users; nullable for system events"
    )
    actor_email: Mapped[str | None] = mapped_column(
        String(320), nullable=True, comment="Denormalized for long-term retention"
    )

    # Timestamp — always UTC server clock
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="UTC server clock at event creation",
    )

    # Target entity
    entity_type: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="e.g. form_instance, subject, study"
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="PK of the affected entity"
    )

    # Scoping — nullable to support system-level events
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # Action
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="e.g. create, update, delete, submit, sign",
    )

    # Field-level detail (for data changes)
    field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reason for change (required post-submission edits)
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Reason_For_Change"
    )

    # Request tracing
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, comment="Correlates to X-Request-ID header"
    )

    # Client metadata
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_timestamp", "timestamp"),
        Index("ix_audit_events_study_id", "study_id"),
        Index("ix_audit_events_subject_id", "subject_id"),
        Index("ix_audit_events_request_id", "request_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEvent(id={self.id}, action={self.action!r}, "
            f"entity={self.entity_type}:{self.entity_id}, "
            f"actor={self.actor_email})>"
        )
