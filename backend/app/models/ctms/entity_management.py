"""Reusable CTMS entity catalog and study assignments."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class ManagedEntityType(enum.StrEnum):
    COUNTRY = "country"
    SITE = "site"
    DEPOT = "depot"
    STAFF = "staff"
    PARTICIPATING_ORGANIZATION = "participating_organization"
    INVESTIGATIONAL_PRODUCT = "investigational_product"


def utc_now() -> datetime:
    return datetime.now(UTC)


class ManagedEntity(Base):
    """A reusable CTMS master-data entity that can be assigned to studies."""

    __tablename__ = "ctms_managed_entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("entity_type", "code", name="uq_ctms_managed_entities_type_code"),
        UniqueConstraint("canonical_site_id", name="uq_ctms_managed_entities_canonical_site"),
        Index("ix_ctms_managed_entities_type_active", "entity_type", "active"),
    )


class StudyEntityAssignment(Base):
    """Assignment of one configured entity to one canonical study."""

    __tablename__ = "ctms_study_entity_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT"), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entity: Mapped[ManagedEntity] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("study_id", "entity_id", name="uq_ctms_study_entity_assignment"),
        Index("ix_ctms_study_entity_assignments_study", "study_id", "deleted_at"),
    )


__all__ = ["ManagedEntity", "ManagedEntityType", "StudyEntityAssignment"]
