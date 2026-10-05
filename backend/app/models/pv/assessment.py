"""PV safety assessment persistence.

Assessments reference an ``Adverse_Event_Record`` owned by PV. A serious
determination requires at least one seriousness criterion; that rule is
enforced by the ``Assessment_Service`` and, defensively, by a database check
constraint.

Beyond seriousness, PV records:

  - ``Causality_Assessment``    the assessed relationship between a suspect
    product and an adverse event (suspect product, causality category, and the
    assessing actor and timestamp).
  - ``Expectedness_Assessment`` whether an adverse event is expected or
    unexpected against referenced safety information.
  - ``Severity_Grade``          the configured severity classification.

Every assessment is PV-owned Safety_Data: it references a PV
``Adverse_Event_Record`` and never duplicates or mutates an EDC clinical record.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.pv.common import PVBase

JSONBType = JSONB().with_variant(JSON(), "sqlite")

_NOT_DELETED = text("deleted_at IS NULL")

# Field bounds mirrored from the persistence layer and enforced by the service.
_SUSPECT_PRODUCT_MAX_LENGTH = 200
_CAUSALITY_CATEGORY_MAX_LENGTH = 100
_SEVERITY_GRADE_MAX_LENGTH = 100


class SeriousnessCriterion(enum.StrEnum):
    """Regulatory seriousness criteria for an adverse event."""

    DEATH = "death"
    LIFE_THREATENING = "life-threatening"
    HOSPITALIZATION = "hospitalization"
    DISABILITY = "disability"
    CONGENITAL_ANOMALY = "congenital anomaly"
    OTHER_MEDICALLY_IMPORTANT = "other medically important"


class SeriousnessAssessment(PVBase):
    """A seriousness determination for one Adverse_Event_Record.

    When ``serious`` is true, ``criteria`` holds a non-empty subset of
    :class:`SeriousnessCriterion` values; when false, ``criteria`` is empty. The
    ``serious``/``criteria`` invariant is enforced in the service layer and by a
    database check constraint.
    """

    __tablename__ = "pv_seriousness_assessments"

    ae_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    serious: Mapped[bool] = mapped_column(Boolean, nullable=False)
    criteria: Mapped[list[str]] = mapped_column(JSONBType, nullable=False, default=list)

    adverse_event = relationship("AdverseEventRecord", lazy="selectin")

    # The "serious requires at least one criterion" invariant is enforced by the
    # Assessment_Service and, on PostgreSQL, by a jsonb_array_length check
    # constraint added in the Phase 1 migration. It is omitted from the ORM
    # metadata so the portable test harness (SQLite) can create the schema.
    __table_args__ = (
        Index(
            "ix_pv_seriousness_assessments_ae",
            "ae_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class CausalityAssessment(PVBase):
    """An assessed relationship between a suspect product and an adverse event.

    Persists the assessed ``suspect_product`` and ``causality_category`` together
    with the assessing actor (``created_by``) and timestamp (``assessed_at``).
    """

    __tablename__ = "pv_causality_assessments"

    ae_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    suspect_product: Mapped[str] = mapped_column(
        String(_SUSPECT_PRODUCT_MAX_LENGTH), nullable=False
    )
    causality_category: Mapped[str] = mapped_column(
        String(_CAUSALITY_CATEGORY_MAX_LENGTH), nullable=False
    )
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    adverse_event = relationship("AdverseEventRecord", lazy="selectin")

    __table_args__ = (
        Index(
            "ix_pv_causality_assessments_ae",
            "ae_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class ExpectednessAssessment(PVBase):
    """Whether an adverse event is expected or unexpected.

    ``expected`` records the determination against the referenced safety
    information (``reference_safety_information``).
    """

    __tablename__ = "pv_expectedness_assessments"

    ae_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reference_safety_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    adverse_event = relationship("AdverseEventRecord", lazy="selectin")

    __table_args__ = (
        Index(
            "ix_pv_expectedness_assessments_ae",
            "ae_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


class SeverityGrade(PVBase):
    """A configured severity classification for an Adverse_Event_Record."""

    __tablename__ = "pv_severity_grades"

    ae_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    grade: Mapped[str] = mapped_column(String(_SEVERITY_GRADE_MAX_LENGTH), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    adverse_event = relationship("AdverseEventRecord", lazy="selectin")

    __table_args__ = (
        Index(
            "ix_pv_severity_grades_ae",
            "ae_id",
            postgresql_where=_NOT_DELETED,
        ),
    )


__all__ = [
    "CausalityAssessment",
    "ExpectednessAssessment",
    "SeriousnessAssessment",
    "SeriousnessCriterion",
    "SeverityGrade",
]
