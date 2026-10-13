"""CTMS-owned records for study-operation domains introduced after the core phases."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class StudyOperationResource(enum.StrEnum):
    CONTRACT = "contract"
    PRICING_TEMPLATE = "pricing_template"
    PAYMENT = "payment"
    RACT = "ract"
    KRI = "kri"
    MONITORING_ISSUE = "monitoring_issue"
    PROTOCOL_DEVIATION = "protocol_deviation"
    ICF = "icf"
    TRACKING_LOG = "tracking_log"


class StudyOperationRecord(Base):
    """Auditable CTMS record with a typed domain discriminator.

    ``subject_id`` and ``reference_id`` are references only. This record never
    mutates EDC subjects, visits, forms, field values, queries, or signatures.
    """

    __tablename__ = "ctms_study_operation_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    record_subtype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Draft")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    retention_state: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('contract','pricing_template','payment','ract','kri','monitoring_issue','protocol_deviation','icf','tracking_log')",
            name="ck_ctms_study_operation_resource_type",
        ),
        Index(
            "ix_ctms_study_operation_resource_status",
            "study_id",
            "resource_type",
            "status",
        ),
        Index("ix_ctms_study_operation_site_resource", "site_id", "resource_type"),
        Index("ix_ctms_study_operation_owner_due", "owner_id", "end_at"),
    )


__all__ = ["StudyOperationRecord", "StudyOperationResource"]
