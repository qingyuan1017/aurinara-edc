"""CTMS operational work, contacts, dependencies, and escalations."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class OperationalTaskStatus(enum.StrEnum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    BLOCKED = "Blocked"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    ARCHIVED = "Archived"


class OperationalTaskPriority(enum.StrEnum):
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"
    URGENT = "Urgent"


class OperationalContactStatus(enum.StrEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    ARCHIVED = "Archived"


class EscalationStatus(enum.StrEnum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    CANCELLED = "Cancelled"


class OperationalTask(Base):
    """A CTMS-owned actionable work item; clinical records are references only."""

    __tablename__ = "ctms_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=OperationalTaskPriority.NORMAL.value)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OperationalTaskStatus.OPEN.value)
    query_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )
    query_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    dependencies = relationship(
        "TaskDependency", foreign_keys="TaskDependency.task_id", back_populates="task", lazy="selectin"
    )
    dependents = relationship(
        "TaskDependency", foreign_keys="TaskDependency.depends_on_task_id", back_populates="depends_on", lazy="selectin"
    )
    escalations = relationship("TaskEscalation", back_populates="task", lazy="selectin")

    __table_args__ = (
        Index("ix_ctms_tasks_scope_status", "study_id", "site_id", "status"),
        Index("ix_ctms_tasks_owner_due_date", "owner_id", "due_date"),
    )


class OperationalContact(Base):
    """A CTMS operational contact scoped to a canonical study or site."""

    __tablename__ = "ctms_contacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channels: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=OperationalContactStatus.ACTIVE.value)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_ctms_contacts_scope_status", "study_id", "site_id", "status"),)


class TaskDependency(Base):
    """Directed prerequisite link: ``task_id`` depends on ``depends_on_task_id``."""

    __tablename__ = "ctms_task_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task = relationship("OperationalTask", foreign_keys=[task_id], back_populates="dependencies")
    depends_on = relationship("OperationalTask", foreign_keys=[depends_on_task_id], back_populates="dependents")

    __table_args__ = (
        Index("uq_ctms_task_dependency", "task_id", "depends_on_task_id", unique=True),
    )


class TaskEscalation(Base):
    """Environment-gated CTMS escalation for an operational task."""

    __tablename__ = "ctms_escalations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EscalationStatus.OPEN.value)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    task = relationship("OperationalTask", back_populates="escalations")

    __table_args__ = (Index("ix_ctms_escalations_task_status", "task_id", "status"),)


# Compatibility aliases used by integrations and schemas.
CTMSTask = OperationalTask
TaskStatus = OperationalTaskStatus
TaskPriority = OperationalTaskPriority
ContactStatus = OperationalContactStatus

__all__ = [
    "CTMSTask",
    "ContactStatus",
    "EscalationStatus",
    "OperationalContact",
    "OperationalContactStatus",
    "OperationalTask",
    "OperationalTaskPriority",
    "OperationalTaskStatus",
    "TaskDependency",
    "TaskEscalation",
    "TaskPriority",
    "TaskStatus",
]
