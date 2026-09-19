"""Durable generation and watermark state for CTMS projection rebuilds."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectionRebuildStatus(enum.StrEnum):
    """Terminal state of one scope-limited rebuild generation."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(UTC)


class CTMSProjectionRebuildState(Base):
    """One immutable-ish execution record for a projection rebuild generation.

    The row is separate from authoritative EDC/CTMS tables and from the
    projection read model.  It records the scope and the last source watermark
    observed by the worker so a run can be resumed or audited without copying
    source payloads.
    """

    __tablename__ = "ctms_projection_rebuild_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    generation: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    projection_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_module: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_study_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    scope_site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ProjectionRebuildStatus] = mapped_column(
        String(20), nullable=False, default=ProjectionRebuildStatus.RUNNING
    )
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    watermark_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    watermark_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    watermark_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        Index(
            "ix_ctms_projection_rebuild_scope",
            "scope_study_id",
            "scope_site_id",
            "projection_type",
            "source_module",
            "started_at",
        ),
        Index(
            "ix_ctms_projection_rebuild_watermark",
            "scope_study_id",
            "scope_site_id",
            "watermark_timestamp",
        ),
    )

    @property
    def watermark(self) -> dict[str, object | None]:
        """Return sanitized watermark metadata without source payload content."""

        return {
            "version": self.watermark_version,
            "timestamp": self.watermark_timestamp,
            "record_id": self.watermark_record_id,
        }


# Compatibility aliases used by worker and API integrations.
ProjectionRebuildState = CTMSProjectionRebuildState
RebuildStatus = ProjectionRebuildStatus

__all__ = [
    "CTMSProjectionRebuildState",
    "ProjectionRebuildState",
    "ProjectionRebuildStatus",
    "RebuildStatus",
    "utc_now",
]
