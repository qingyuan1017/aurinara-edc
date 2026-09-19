"""Typed, minimized CTMS operational projection records.

Projection rows are read models only. Canonical identifiers refer to EDC or
shared identities; this table never copies or owns clinical records.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProjectionStatus(enum.StrEnum):
    """Lifecycle state of a persisted projection read model."""

    CURRENT = "current"
    STALE = "stale"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class CTMSOperationalProjection(Base):
    """A schema-validated, read-only projection of an authoritative record."""

    __tablename__ = "ctms_operational_projections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    projection_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_module: Mapped[str] = mapped_column(String(20), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    visit_instance_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    query_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rejected_fields_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ProjectionStatus] = mapped_column(String(20), nullable=False, default=ProjectionStatus.CURRENT)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rebuild_generation: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    __table_args__ = (
        UniqueConstraint("projection_type", "source_module", "source_record_id", name="uq_ctms_operational_projections_source"),
        CheckConstraint("source_module IN ('EDC', 'CTMS')", name="ck_ctms_operational_projections_source_module"),
        CheckConstraint("status IN ('current', 'stale', 'rejected', 'archived')", name="ck_ctms_operational_projections_status"),
        Index("ix_ctms_operational_projections_scope_status", "study_id", "site_id", "status"),
        Index("ix_ctms_operational_projections_source_version", "source_module", "source_record_id", "source_version"),
        Index("ix_ctms_operational_projections_projected_at", "projected_at"),
    )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def payload(self) -> dict[str, Any]:
        return self.payload_json


# Compatibility aliases used by existing CTMS consumers.
OperationalProjection = CTMSOperationalProjection
CTMSProjection = CTMSOperationalProjection
CTMSOperationalProjectionRecord = CTMSOperationalProjection
ProjectionState = ProjectionStatus

__all__ = [
    "CTMSOperationalProjection",
    "CTMSOperationalProjectionRecord",
    "CTMSProjection",
    "OperationalProjection",
    "ProjectionState",
    "ProjectionStatus",
    "utc_now",
]
