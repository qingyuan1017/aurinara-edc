"""Idempotency records for shared control-plane event projections."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformProjectionEvent(Base):
    __tablename__ = "platform_projection_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (Index("ix_platform_projection_events_aggregate", "aggregate_id"),)


class PlatformMembershipProjection(Base):
    """Last applied sequence for one membership scope."""

    __tablename__ = "platform_membership_projections"

    scope_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    study_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class PlatformRoleMapping(Base):
    """Reviewed least-privilege mapping from a platform role to one local role."""

    __tablename__ = "platform_role_mappings"

    platform_role_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    local_role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
