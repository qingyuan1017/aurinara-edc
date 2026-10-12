"""Schedule_of_Assessment_Service — authoring of Schedule_of_Assessment matrices.

Owns creation of the design-time ``Schedule_of_Assessment`` (SoA) within a
``Draft_Design``. The SoA maps forms or named procedures to the visit
definitions at which they are collected (a cycle is now a visit of
``visit_type == 'cycle'``), and binds to exactly one ``Design_Version``.

Satisfies Requirements:
  - 4.1: Persist a schedule of assessment that maps forms/procedures to visit
         definitions within a design version.

Every mutation writes an Audit_Event inside the caller's transaction so the data
and audit commit (or roll back) atomically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import NotFoundError, ValidationError
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.schedule_of_assessment import (
    ScheduleOfAssessment,
    ScheduleOfAssessmentEntry,
)
from app.models.designer.visit import VisitDefinition

logger = logging.getLogger(__name__)

_PROCEDURE_NAME_MIN_LENGTH = 1
_PROCEDURE_NAME_MAX_LENGTH = 255


@dataclass(frozen=True)
class ScheduleEntryInput:
    """One form/procedure-to-visit mapping to persist in an SoA.

    Exactly one of ``form_definition_id`` or ``procedure_name`` identifies what
    is collected, and ``visit_definition_id`` (a plain visit or a cycle)
    identifies when it is collected (R4.1).
    """

    form_definition_id: UUID | None = None
    procedure_name: str | None = None
    visit_definition_id: UUID | None = None
    display_order: int = 1


class ScheduleOfAssessmentService:
    """Creates and validates Schedule_of_Assessment matrices for a Draft_Design."""

    async def create_schedule_of_assessment(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        entries: list[ScheduleEntryInput],
        actor_id: UUID | None = None,
    ) -> ScheduleOfAssessment:
        """Persist a Schedule_of_Assessment within one Design_Version (R4.1).

        Validates every entry *before* any write; a violation raises and
        persists nothing.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R4.1).
            entries: The form/procedure-to-visit/cycle mappings to persist.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted ScheduleOfAssessment with its ``entries`` eagerly loaded.

        Raises:
            ValidationError: If an entry does not identify exactly one of a form
                or a procedure, or does not identify at least one of a visit or a
                cycle, or carries an out-of-range procedure name.
        """
        for index, entry in enumerate(entries):
            self._validate_entry(entry, index)
        await self._validate_references(session, design_version_id, entries)

        # Idempotent replace (A.12): a design version holds at most one live SoA.
        # Soft-delete every existing live SoA (and each of its live entries)
        # before constructing the replacement, recording one 'delete' audit
        # event per replaced SoA — all in the caller's transaction so the
        # replacement and the retirement commit (or roll back) together.
        await self._retire_existing(session, design_version_id, actor_id)

        soa = ScheduleOfAssessment(design_version_id=design_version_id)
        session.add(soa)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="schedule_of_assessment",
            entity_id=soa.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"design_version_id={design_version_id}; entries={len(entries)}",
            actor_id=actor_id,
        )

        for entry in entries:
            await self._add_entry(session, soa, entry, actor_id)

        logger.info(
            "Schedule of assessment created: id=%s design_version_id=%s entries=%d",
            soa.id,
            design_version_id,
            len(entries),
        )
        return await self._get_with_entries(session, soa.id)

    async def _validate_references(
        self,
        session: AsyncSession,
        design_version_id: UUID,
        entries: list[ScheduleEntryInput],
    ) -> None:
        """Keep the SoA on eligible visit rows in the same design version.

        Standalone visits and cycle-owned child visits are eligible.
        Folder and cycle rows are organizational containers.
        """
        visit_ids = {entry.visit_definition_id for entry in entries if entry.visit_definition_id}
        form_ids = {entry.form_definition_id for entry in entries if entry.form_definition_id}
        visits = (
            list(
                (
                    await session.execute(
                        select(VisitDefinition).where(VisitDefinition.id.in_(visit_ids))
                    )
                )
                .scalars()
                .all()
            )
            if visit_ids
            else []
        )
        forms = (
            list(
                (
                    await session.execute(
                        select(FormDefinition).where(FormDefinition.id.in_(form_ids))
                    )
                )
                .scalars()
                .all()
            )
            if form_ids
            else []
        )
        valid_visits = {
            visit.id
            for visit in visits
            if visit.study_version_id == design_version_id
            and visit.definition_kind in {"visit", "cycle_visit"}
        }
        valid_forms = {form.id for form in forms if form.study_version_id == design_version_id}
        invalid_visits = sorted(str(visit_id) for visit_id in visit_ids - valid_visits)
        invalid_forms = sorted(str(form_id) for form_id in form_ids - valid_forms)
        if invalid_visits:
            raise ValidationError(
                "Schedule entries may reference only standalone visits or cycle-owned child "
                "entries (not folders or cycle containers) from the same design version",
                details={"field": "visit_definition_id", "invalid_ids": invalid_visits},
            )
        if invalid_forms:
            raise ValidationError(
                "Schedule entries may reference only forms from the same design version",
                details={"field": "form_definition_id", "invalid_ids": invalid_forms},
            )

    async def _retire_existing(
        self,
        session: AsyncSession,
        design_version_id: UUID,
        actor_id: UUID | None,
    ) -> None:
        """Soft-delete every live SoA (and its live entries) for a version.

        Records one 'delete' audit event per replaced SoA within the caller's
        transaction (A.12 idempotency).
        """
        result = await session.execute(
            select(ScheduleOfAssessment)
            .where(
                ScheduleOfAssessment.design_version_id == design_version_id,
                ScheduleOfAssessment.deleted_at.is_(None),
            )
            .options(selectinload(ScheduleOfAssessment.entries))
        )
        now = datetime.now(UTC)
        for soa in result.scalars().all():
            for entry in soa.entries:
                if entry.deleted_at is None:
                    entry.deleted_at = now
            soa.deleted_at = now
            await session.flush()
            await audit_service.record(
                session,
                entity_type="schedule_of_assessment",
                entity_id=soa.id,
                action="delete",
                module=Module.DESIGNER,
                old_value=(f"design_version_id={design_version_id}; replaced (idempotent save)"),
                actor_id=actor_id,
            )

    async def _add_entry(
        self,
        session: AsyncSession,
        soa: ScheduleOfAssessment,
        data: ScheduleEntryInput,
        actor_id: UUID | None,
    ) -> ScheduleOfAssessmentEntry:
        """Persist a single SoA entry and audit it."""
        procedure_name = data.procedure_name.strip() if data.procedure_name is not None else None
        entry = ScheduleOfAssessmentEntry(
            schedule_of_assessment_id=soa.id,
            form_definition_id=data.form_definition_id,
            procedure_name=procedure_name,
            visit_definition_id=data.visit_definition_id,
            display_order=data.display_order,
        )
        session.add(entry)
        await session.flush()

        what = (
            f"form_definition_id={data.form_definition_id}"
            if data.form_definition_id is not None
            else f"procedure_name={procedure_name}"
        )
        await audit_service.record(
            session,
            entity_type="schedule_of_assessment_entry",
            entity_id=entry.id,
            action="create",
            module=Module.DESIGNER,
            new_value=f"{what}; visit_definition_id={data.visit_definition_id}",
            actor_id=actor_id,
        )
        return entry

    @staticmethod
    def _validate_entry(entry: ScheduleEntryInput, index: int) -> None:
        """Validate a single SoA entry's what/when identity (R4.1).

        Exactly one of a form or a procedure identifies *what* is collected, and
        a ``visit_definition_id`` identifies *when* — required on every new
        entry (a cycle is a visit now, so the single ref always covers "when").
        """
        has_form = entry.form_definition_id is not None
        procedure = entry.procedure_name.strip() if entry.procedure_name is not None else None
        has_procedure = bool(procedure)

        if has_form == has_procedure:
            raise ValidationError(
                "Each schedule-of-assessment entry must map exactly one of a form "
                "or a named procedure",
                details={"entry_index": index},
            )
        if has_procedure and not (
            _PROCEDURE_NAME_MIN_LENGTH <= len(procedure or "") <= _PROCEDURE_NAME_MAX_LENGTH
        ):
            raise ValidationError(
                "Procedure name must be 1 to 255 characters",
                details={"entry_index": index, "field": "procedure_name"},
            )
        if entry.visit_definition_id is None:
            raise ValidationError(
                "Each schedule-of-assessment entry must map to a visit definition",
                details={"entry_index": index, "field": "visit_definition_id"},
            )

    async def _get_with_entries(self, session: AsyncSession, soa_id: UUID) -> ScheduleOfAssessment:
        """Load an SoA with its ``entries`` eagerly populated.

        A freshly created SoA has an unloaded ``entries`` collection; serializing
        it would emit a lazy load that raises ``MissingGreenlet`` on the async
        engine. Returning a loaded instance keeps serialization IO-free.
        """
        result = await session.execute(
            select(ScheduleOfAssessment)
            .where(ScheduleOfAssessment.id == soa_id)
            .options(selectinload(ScheduleOfAssessment.entries))
        )
        return result.scalars().one()

    async def get_schedule_of_assessment(
        self, session: AsyncSession, design_version_id: UUID
    ) -> ScheduleOfAssessment:
        """Retrieve a version's SoA, raising ``NotFoundError`` if missing."""
        result = await session.execute(
            select(ScheduleOfAssessment)
            .where(
                ScheduleOfAssessment.design_version_id == design_version_id,
                ScheduleOfAssessment.deleted_at.is_(None),
            )
            .options(selectinload(ScheduleOfAssessment.entries))
            .order_by(
                ScheduleOfAssessment.created_at.desc(),
                ScheduleOfAssessment.id.desc(),
            )
        )
        soa = result.scalars().first()
        if soa is None:
            raise NotFoundError(
                "Schedule of assessment not found for design version",
                details={"design_version_id": str(design_version_id)},
            )
        return soa


# Module-level singleton for convenience.
schedule_of_assessment_service = ScheduleOfAssessmentService()
