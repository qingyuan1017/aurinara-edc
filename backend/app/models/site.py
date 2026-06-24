"""Site and study-site-user assignment models.

Satisfies Requirements:
  - 6.1: Site metadata — site number, name, PI, country, region, address, status.
  - 6.2: Site number unique within the study.
  - 6.5: Site-level user assignment.
  - 22.5: Soft-delete via deleted_at column.
  - 22.6: Indexed for efficient querying.
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# --- Enums ---


class SiteStatus(enum.StrEnum):
    """Site lifecycle status (Requirement 6.4)."""

    active = "active"
    inactive = "inactive"


# --- Models ---


class Site(Base):
    """Clinical trial site — organizational unit within a study."""

    __tablename__ = "sites"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Parent study
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )

    # Site identifiers
    site_number: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Unique within the study"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Site details
    principal_investigator: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle
    status: Mapped[SiteStatus] = mapped_column(
        String(20), nullable=False, default=SiteStatus.active
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft-delete (Requirement 22.5)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationships
    study: Mapped["Study"] = relationship("Study", lazy="selectin")  # noqa: F821
    site_users: Mapped[list["StudySiteUser"]] = relationship(
        "StudySiteUser", back_populates="site", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("study_id", "site_number", name="uq_study_site_number"),
        Index("ix_sites_study_id_site_number", "study_id", "site_number"),
        Index("ix_sites_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Site(id={self.id}, study_id={self.study_id}, "
            f"site_number={self.site_number!r}, status={self.status!r})>"
        )


class StudySiteUser(Base):
    """Assignment of a user to a specific site within a study (Requirement 6.5)."""

    __tablename__ = "study_site_users"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Composite reference
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Assignment metadata
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="site_users")
    user: Mapped["User"] = relationship(  # noqa: F821
        "User", foreign_keys=[user_id], lazy="selectin"
    )
    assigner: Mapped["User | None"] = relationship(  # noqa: F821
        "User", foreign_keys=[assigned_by], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "study_id", "site_id", "user_id", name="uq_study_site_user"
        ),
        Index("ix_study_site_users_study_site_user", "study_id", "site_id", "user_id"),
        Index("ix_study_site_users_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudySiteUser(id={self.id}, study_id={self.study_id}, "
            f"site_id={self.site_id}, user_id={self.user_id})>"
        )
