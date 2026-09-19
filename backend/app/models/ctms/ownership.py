"""Versioned CTMS ownership policy records.

A status ownership rule is configuration owned by CTMS.  It identifies one
authoritative writer for a field and the explicitly typed fields that may cross
the module boundary as a read-only projection.
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
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class OwnershipRuleStatus(enum.StrEnum):
    """Lifecycle state of a versioned ownership rule."""

    ACTIVE = "active"
    RETIRED = "retired"


class ProjectionType(enum.StrEnum):
    """Supported schema-specific projection contracts."""

    SUBJECT_STATUS = "subject_status"
    QUERY_SUMMARY = "query_summary"
    DATA_QUALITY_SIGNAL = "data_quality_signal"
    COORDINATED_TRANSITION = "coordinated_transition"


class StatusOwnershipRule(Base):
    """One version of a field ownership and projection policy.

    ``allowlist_json`` stores only validated field/type declarations; source
    records and arbitrary event payloads are never stored in this table.
    """

    __tablename__ = "ctms_status_ownership_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    authoritative_module: Mapped[str] = mapped_column(String(20), nullable=False)
    writable_module: Mapped[str] = mapped_column(String(20), nullable=False)
    projection_target: Mapped[str | None] = mapped_column(String(20), nullable=True)
    projection_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    allowed_transitions: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    allowlist_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[OwnershipRuleStatus] = mapped_column(
        String(20), nullable=False, default=OwnershipRuleStatus.ACTIVE
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retirement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "authoritative_module IN ('EDC', 'CTMS')",
            name="ck_ctms_status_ownership_authoritative_module",
        ),
        CheckConstraint(
            "writable_module = authoritative_module",
            name="ck_ctms_status_ownership_single_writer",
        ),
        CheckConstraint(
            "projection_target IS NULL OR projection_target <> authoritative_module",
            name="ck_ctms_status_ownership_projection_target",
        ),
        Index(
            "ix_ctms_status_ownership_rules_lookup",
            "entity_type",
            "field_path",
            "status",
            "effective_from",
        ),
        UniqueConstraint(
            "entity_type",
            "field_path",
            "version",
            name="uq_ctms_status_ownership_rules_version",
        ),
    )

    @property
    def allowlist(self) -> dict[str, Any]:
        """Compatibility name used by the service and API contracts."""

        return self.allowlist_json


# Specification-compatible alias for callers that use the singular record name.
StatusOwnershipRuleRecord = StatusOwnershipRule


__all__ = [
    "OwnershipRuleStatus",
    "ProjectionType",
    "StatusOwnershipRule",
    "StatusOwnershipRuleRecord",
]
