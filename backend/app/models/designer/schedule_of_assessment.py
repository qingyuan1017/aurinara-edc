"""Schedule_of_Assessment models — a NEW Designer-owned design-time table.

A ``Schedule_of_Assessment`` (SoA) is the design-time matrix that maps forms or
named procedures to the visit definitions at which they are collected, authored
inside a ``Draft_Design`` and consumed downstream read-only through the
Design_Consumption_Contract. These are **new** designer tables (not a
reassignment of an existing EDC table), each bound to exactly one
``Design_Version`` through ``design_version_id``.

The SoA is modelled as a parent ``ScheduleOfAssessment`` (one per
``Design_Version``) holding an ordered collection of ``ScheduleOfAssessmentEntry``
rows. Each entry maps a form (``form_definitions``) **or** a named procedure to a
single ``visit_definitions`` row (a plain visit or a cycle — a cycle is now a
visit of ``visit_type == 'cycle'``):

  - ``form_definition_id`` XOR ``procedure_name`` identifies *what* is collected.
  - ``visit_definition_id`` identifies *when*.

Satisfies Requirements:
  - 4.1: Persist a schedule of assessment that maps forms/procedures to visit
         definitions within a design version.

Conventions (matching the designer/edc models):
  - UUID primary keys.
  - Timezone-aware ``created_at`` / ``updated_at`` timestamps.
  - Soft-delete via a nullable ``deleted_at`` column.
  - FKs by table name so the shared ORM registry resolves them; referenced
    designer models (FormDefinition / VisitDefinition) are *not* imported at
    runtime to avoid coupling — relationships are declared by string against the
    shared registry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:  # avoid runtime import cycles; resolved via the shared registry
    from app.models.designer.study_version import StudyVersion


class ScheduleOfAssessment(Base):
    """The schedule-of-assessment matrix for one ``Design_Version`` (R4.1).

    One SoA binds to exactly one ``Design_Version`` via ``design_version_id`` and
    owns an ordered collection of :class:`ScheduleOfAssessmentEntry` mappings.
    """

    __tablename__ = "schedule_of_assessment"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning Design_Version (R4.1 — binds to exactly one design version)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("study_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationships (resolved by string against the shared ORM registry)
    design_version: Mapped[StudyVersion] = relationship("StudyVersion", lazy="selectin")
    entries: Mapped[list[ScheduleOfAssessmentEntry]] = relationship(
        "ScheduleOfAssessmentEntry",
        back_populates="schedule_of_assessment",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ScheduleOfAssessmentEntry.display_order",
    )

    __table_args__ = (
        Index(
            "ix_schedule_of_assessment_design_version_id",
            "design_version_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<ScheduleOfAssessment(id={self.id}, design_version_id={self.design_version_id})>"


class ScheduleOfAssessmentEntry(Base):
    """One form/procedure-to-visit mapping within an SoA (R4.1).

    ``form_definition_id`` *or* ``procedure_name`` identifies what is collected,
    and ``visit_definition_id`` identifies when (a cycle is now a visit of
    ``visit_type == 'cycle'``). The FKs to ``form_definitions`` and
    ``visit_definitions`` are declared by table name only (no runtime import of
    those designer models) so the relationship is resolved lazily through the
    shared ORM registry.
    """

    __tablename__ = "schedule_of_assessment_entries"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Owning schedule of assessment
    schedule_of_assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schedule_of_assessment.id", ondelete="CASCADE"),
        nullable=False,
    )

    # What is collected — a form OR a named procedure (one of the two is set).
    form_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )
    procedure_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # When it is collected — a single visit (a plain visit or a cycle). Nullable
    # only to preserve pre-migration rows; the service requires it on new writes.
    visit_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("visit_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Presentation order within the SoA
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Soft-delete timestamp"
    )

    # Relationship back to the owning SoA
    schedule_of_assessment: Mapped[ScheduleOfAssessment] = relationship(
        "ScheduleOfAssessment", back_populates="entries"
    )

    __table_args__ = (
        Index(
            "ix_schedule_of_assessment_entries_schedule_id",
            "schedule_of_assessment_id",
        ),
        Index(
            "ix_schedule_of_assessment_entries_form_definition_id",
            "form_definition_id",
        ),
        Index(
            "ix_schedule_of_assessment_entries_visit_definition_id",
            "visit_definition_id",
        ),
    )

    def __repr__(self) -> str:
        what = (
            f"form_definition_id={self.form_definition_id}"
            if self.form_definition_id is not None
            else f"procedure_name={self.procedure_name!r}"
        )
        return (
            f"<ScheduleOfAssessmentEntry(id={self.id}, {what}, "
            f"visit_definition_id={self.visit_definition_id})>"
        )
