"""Additional ODM 2.0 metadata owned by the Designer module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.odm_oid import new_odm_oid

JSONBType = JSONB().with_variant(JSON(), "sqlite")


class MeasurementUnitDefinition(Base):
    __tablename__ = "measurement_unit_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )
    odm_oid: Mapped[str] = mapped_column(
        String(255), nullable=False, default=lambda: new_odm_oid("MU")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str] = mapped_column(String(100), nullable=False)
    conversion_factor: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    conversion_offset: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    study_version = relationship("StudyVersion", lazy="selectin")

    __table_args__ = (
        Index("ix_measurement_units_version", "study_version_id"),
        Index("ix_measurement_units_oid", "odm_oid"),
    )


class DerivationDefinition(Base):
    __tablename__ = "derivation_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )
    target_field_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("field_definitions.id", ondelete="CASCADE"), nullable=False
    )
    odm_oid: Mapped[str] = mapped_column(
        String(255), nullable=False, default=lambda: new_odm_oid("METHOD")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expression_json: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    needs_retesting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retesting_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    study_version = relationship("StudyVersion", lazy="selectin")
    target_field = relationship("FieldDefinition", lazy="selectin")

    __table_args__ = (
        Index("ix_derivations_version", "study_version_id"),
        Index("ix_derivations_target", "target_field_definition_id"),
        Index("ix_derivations_oid", "odm_oid"),
    )


__all__ = ["DerivationDefinition", "MeasurementUnitDefinition"]
