"""Operational EDC quality and controlled-lock records.

These tables keep source-data review and maker-checker clinical controls in
the EDC ownership boundary. They intentionally reference canonical clinical
identities without creating competing subject, visit, or form records.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class SDRSelectionStrategy(enum.StrEnum):
    all = "all"
    percentage = "percentage"
    targeted = "targeted"


class SDRStatus(enum.StrEnum):
    pending = "Pending"
    in_review = "In Review"
    complete = "Complete"


class ClinicalControlAction(enum.StrEnum):
    freeze = "freeze"
    unfreeze = "unfreeze"
    lock = "lock"
    unlock = "unlock"


class ClinicalControlRequestStatus(enum.StrEnum):
    pending_approval = "Pending Approval"
    approved = "Approved"
    executed = "Executed"
    rejected = "Rejected"
    cancelled = "Cancelled"
    failed = "Failed"


class SDRSetting(Base):
    """Designer-owned, version-bound SDR selection configuration."""

    __tablename__ = "sdr_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    targeted_field_ids: Mapped[list[str] | None] = mapped_column(JSONBType, nullable=True)
    is_required_for_lock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("study_version_id", name="uq_sdr_settings_study_version"),
        Index("ix_sdr_settings_study_version", "study_version_id"),
    )


class SDRSelection(Base):
    """Persisted, reproducible form selection for operational SDR."""

    __tablename__ = "sdr_selections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    form_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("form_instances.id", ondelete="CASCADE"), nullable=False
    )
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="RESTRICT"), nullable=False
    )
    selection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selection_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "form_instance_id", "design_version_id", name="uq_sdr_selection_form_design"
        ),
        Index("ix_sdr_selections_study_status", "study_id", "site_id"),
    )


class SDRResult(Base):
    """Current SDR decision, retained and made stale through revision comparison."""

    __tablename__ = "sdr_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    selection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sdr_selections.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    reviewed_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("selection_id", name="uq_sdr_result_selection"),
        Index("ix_sdr_results_status", "status"),
    )


class ClinicalControlRequest(Base):
    """Maker-checker request for scoped clinical freeze/lock changes."""

    __tablename__ = "clinical_control_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ClinicalControlRequestStatus.pending_approval.value
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    readiness_snapshot: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    readiness_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_details: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_clinical_control_requests_active_action_scope",
            "study_id",
            "scope_type",
            "scope_id",
            "action",
            unique=True,
            postgresql_where=text("status IN ('Pending Approval', 'Approved')"),
            sqlite_where=text("status IN ('Pending Approval', 'Approved')"),
        ),
        Index(
            "ix_clinical_control_requests_scope",
            "study_id",
            "scope_type",
            "scope_id",
            "status",
        ),
        Index("ix_clinical_control_requests_requested_at", "requested_at"),
    )


__all__ = [
    "ClinicalControlAction",
    "ClinicalControlRequest",
    "ClinicalControlRequestStatus",
    "SDRResult",
    "SDRSelection",
    "SDRSelectionStrategy",
    "SDRSetting",
    "SDRStatus",
]
