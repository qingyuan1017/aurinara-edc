"""Configurable CTMS reference values used by operational dropdowns."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReferenceCategory(enum.StrEnum):
    COUNTRY = "country"
    PARTICIPATING_ORGANIZATION_TYPE = "participating_organization_type"
    THERAPEUTIC_AREA = "therapeutic_area"
    INDICATION = "indication"
    MILESTONE_TYPE = "milestone_type"
    PROJECT_STATUS = "project_status"


class CTMSReferenceValue(Base):
    __tablename__ = "ctms_reference_values"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("category", "code", name="uq_ctms_reference_values_category_code"),
        Index("ix_ctms_reference_values_category_active_order", "category", "active", "sort_order"),
    )


__all__ = ["CTMSReferenceValue", "ReferenceCategory"]
