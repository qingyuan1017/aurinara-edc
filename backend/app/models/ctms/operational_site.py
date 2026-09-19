"""CTMS operational site, readiness, and activation persistence.

These records reference the canonical EDC ``Site`` and ``Study`` identities.
They contain operational state only; no clinical site configuration is copied.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OperationalSiteStatus(enum.StrEnum):
    """CTMS-owned operational site lifecycle statuses."""

    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    READY_FOR_ACTIVATION = "Ready for Activation"
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    CLOSED = "Closed"
    SITE_ARCHIVED = "Site Archived"


class ActivationActionStatus(enum.StrEnum):
    """Lifecycle of a CTMS activation/readiness action."""

    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    ARCHIVED = "Archived"


class RetentionState(enum.StrEnum):
    """Retention state stored by Phase 1 CTMS tables."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


def utc_now() -> datetime:
    return datetime.now(UTC)


class OperationalSite(Base):
    """One CTMS operational profile for one canonical EDC site."""

    __tablename__ = "ctms_operational_sites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    monitoring_readiness: Mapped[str | None] = mapped_column(String(30), nullable=True)
    responsible_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    planned_activation_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=OperationalSiteStatus.NOT_STARTED.value
    )
    retention_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RetentionState.ACTIVE.value
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    study = relationship("Study", lazy="selectin")
    site = relationship("Site", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("site_id", name="uq_ctms_operational_sites_site_id"),
        Index("ix_ctms_operational_sites_study_site", "study_id", "site_id"),
        Index("ix_ctms_operational_sites_status", "study_id", "status"),
    )

    @property
    def operational_profile(self) -> dict[str, object | None]:
        """Expose the CTMS-owned profile fields as a stable read model."""

        return {
            "monitoring_readiness": self.monitoring_readiness,
            "responsible_role": self.responsible_role,
            "planned_activation_date": self.planned_activation_date,
            "status": self.status,
        }


class ActivationAction(Base):
    """A readiness or activation action scoped to one canonical EDC site."""

    __tablename__ = "ctms_activation_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    responsible_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    responsible_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    planned_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActivationActionStatus.OPEN.value
    )
    retention_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default=RetentionState.ACTIVE.value
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    study = relationship("Study", lazy="selectin")
    site = relationship("Site", lazy="selectin")

    __table_args__ = (
        Index("ix_ctms_activation_actions_study_site", "study_id", "site_id"),
        Index(
            "uq_ctms_activation_actions_active",
            "site_id",
            "action_type",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND status NOT IN ('Completed','Cancelled','Archived')"),
            postgresql_where=text("deleted_at IS NULL AND status NOT IN ('Completed','Cancelled','Archived')"),
        ),
    )

    @property
    def completion_evidence(self) -> str | None:
        """Compatibility name used by service/API contracts."""

        return self.evidence_reference

    @completion_evidence.setter
    def completion_evidence(self, value: str | None) -> None:
        self.evidence_reference = value


# Names used by API and coordination contracts.
OperationalSiteProfile = OperationalSite
CTMSOperationalSite = OperationalSite
SiteActivationAction = ActivationAction
CTMSActivationAction = ActivationAction

__all__ = [
    "ActivationAction",
    "ActivationActionStatus",
    "CTMSActivationAction",
    "CTMSOperationalSite",
    "OperationalSite",
    "OperationalSiteProfile",
    "OperationalSiteStatus",
    "RetentionState",
    "SiteActivationAction",
]
