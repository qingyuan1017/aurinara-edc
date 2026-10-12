"""Subject_Phase_Service — authoring of Subject_Phase_Definitions.

Owns creation of design-time ``Subject_Phase_Definition`` records within a
``Draft_Design``. The service enforces name uniqueness within a single design
version and binds every definition to exactly one ``Design_Version``.

Satisfies Requirements:
  - 3.1: Persist a Subject_Phase_Definition with a name of 1-100 characters that
         is unique within its design version and a display order of 1-999.
  - 3.2: Reject a non-unique name, persist nothing, and return an error that
         identifies the duplicate name.
  - 3.3: Associate each Subject_Phase_Definition with exactly one Design_Version.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseType,
    SubjectPhaseVisitDefinition,
)
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.designer.visit import VisitDefinition

logger = logging.getLogger(__name__)

_NAME_MIN_LENGTH = 1
_NAME_MAX_LENGTH = 100
_DISPLAY_ORDER_MIN = 1
_DISPLAY_ORDER_MAX = 999
_VISIT_PHASE_TYPES = {
    SubjectPhaseType.registered,
    SubjectPhaseType.screen_failure,
    SubjectPhaseType.common,
}


class SubjectPhaseService:
    """Creates and validates Subject_Phase_Definitions for a Draft_Design."""

    async def create_phase_definition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        name: str,
        display_order: int,
        phase_type: SubjectPhaseType = SubjectPhaseType.common,
        visit_definition_ids: list[UUID] | None = None,
        actor_id: UUID | None = None,
    ) -> SubjectPhaseDefinition:
        """Persist a Subject_Phase_Definition within one Design_Version.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version (R3.3).
            name: Phase name; 1-100 characters, unique within the design version.
            display_order: Presentation order; 1-999.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted SubjectPhaseDefinition.

        Raises:
            ValidationError: If the name length or display order is out of range.
            ConflictError: If the name already exists within the design version;
                the error details identify the duplicate name (R3.2).
        """
        normalized_name = name.strip()
        if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
            raise ValidationError(
                "Subject phase name must be 1 to 100 characters",
                details={"field": "name"},
            )
        if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
            raise ValidationError(
                "Subject phase display order must be between 1 and 999",
                details={"field": "display_order"},
            )

        # Uniqueness within the design version (R3.2). A case-insensitive match
        # treats "Screening" and "screening" as the same phase name within one
        # design version.
        existing = await session.execute(
            select(SubjectPhaseDefinition.id).where(
                SubjectPhaseDefinition.design_version_id == design_version_id,
                func.lower(SubjectPhaseDefinition.name) == normalized_name.lower(),
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "A subject phase definition with this name already exists in the design version",
                details={
                    "duplicate_name": normalized_name,
                    "design_version_id": str(design_version_id),
                },
            )

        phase_type = SubjectPhaseType(phase_type)
        visit_ids = visit_definition_ids or []
        self._validate_visit_membership(phase_type, visit_ids)

        phase = SubjectPhaseDefinition(
            design_version_id=design_version_id,
            name=normalized_name,
            phase_type=phase_type,
            display_order=display_order,
        )
        session.add(phase)
        await session.flush()

        await self._replace_visits(session, phase, visit_ids)

        await audit_service.record(
            session,
            entity_type="subject_phase_definition",
            entity_id=phase.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"name={normalized_name}; phase_type={phase_type}; "
                f"display_order={display_order}; "
                f"visit_definition_ids={[str(value) for value in visit_ids]}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Subject phase definition created: id=%s design_version_id=%s name=%r",
            phase.id,
            design_version_id,
            normalized_name,
        )
        return await self._get_live_phase(session, phase.id)

    async def list_phase_definitions(
        self,
        session: AsyncSession,
        design_version_id: UUID,
    ) -> list[SubjectPhaseDefinition]:
        """List a version's live phase definitions ordered for display."""
        result = await session.execute(
            select(SubjectPhaseDefinition)
            .where(
                SubjectPhaseDefinition.design_version_id == design_version_id,
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
            .options(selectinload(SubjectPhaseDefinition.visits))
            .order_by(SubjectPhaseDefinition.display_order, SubjectPhaseDefinition.id)
        )
        return list(result.scalars().all())

    async def get_phase_definition(
        self, session: AsyncSession, phase_id: UUID
    ) -> SubjectPhaseDefinition:
        """Fetch a live phase by id, raising ``NotFoundError`` if missing."""
        return await self._get_live_phase(session, phase_id)

    async def _get_live_phase(
        self, session: AsyncSession, phase_id: UUID
    ) -> SubjectPhaseDefinition:
        """Fetch a live phase by id, raising ``NotFoundError`` if missing."""
        result = await session.execute(
            select(SubjectPhaseDefinition)
            .where(
                SubjectPhaseDefinition.id == phase_id,
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
            .options(selectinload(SubjectPhaseDefinition.visits))
        )
        phase = result.scalars().first()
        if phase is None:
            raise NotFoundError(
                "Subject phase definition not found",
                details={"phase_id": str(phase_id)},
            )
        return phase

    async def update_phase_definition(
        self,
        session: AsyncSession,
        phase_id: UUID,
        *,
        name: str | None = None,
        phase_type: SubjectPhaseType | None = None,
        display_order: int | None = None,
        visit_definition_ids: list[UUID] | None = None,
        actor_id: UUID | None = None,
    ) -> SubjectPhaseDefinition:
        """Edit a Subject_Phase_Definition (partial update).

        Re-runs the case-insensitive uniqueness check on a rename and audits the
        update. Raises ``NotFoundError`` if the phase is missing/soft-deleted,
        ``ValidationError`` on out-of-range values, or ``ConflictError`` on a
        colliding rename.
        """
        phase = await self._get_live_phase(session, phase_id)

        changes: dict[str, object] = {}

        if name is not None:
            normalized_name = name.strip()
            if not (_NAME_MIN_LENGTH <= len(normalized_name) <= _NAME_MAX_LENGTH):
                raise ValidationError(
                    "Subject phase name must be 1 to 100 characters",
                    details={"field": "name"},
                )
            if normalized_name.lower() != phase.name.lower():
                existing = await session.execute(
                    select(SubjectPhaseDefinition.id).where(
                        SubjectPhaseDefinition.design_version_id == phase.design_version_id,
                        func.lower(SubjectPhaseDefinition.name) == normalized_name.lower(),
                        SubjectPhaseDefinition.id != phase.id,
                        SubjectPhaseDefinition.deleted_at.is_(None),
                    )
                )
                if existing.first() is not None:
                    raise ConflictError(
                        "A subject phase definition with this name already "
                        "exists in the design version",
                        details={
                            "duplicate_name": normalized_name,
                            "design_version_id": str(phase.design_version_id),
                        },
                    )
            changes["name"] = normalized_name

        if display_order is not None:
            if not (_DISPLAY_ORDER_MIN <= display_order <= _DISPLAY_ORDER_MAX):
                raise ValidationError(
                    "Subject phase display order must be between 1 and 999",
                    details={"field": "display_order"},
                )
            changes["display_order"] = display_order

        if phase_type is not None:
            phase_type = SubjectPhaseType(phase_type)
            changes["phase_type"] = phase_type

        if visit_definition_ids is not None:
            changes["visit_definition_ids"] = visit_definition_ids

        resulting_type = SubjectPhaseType(phase_type or phase.phase_type)
        resulting_visit_ids = (
            visit_definition_ids
            if visit_definition_ids is not None
            else list(phase.visit_definition_ids)
        )
        self._validate_visit_membership(resulting_type, resulting_visit_ids)

        old_values = {
            key: (
                list(phase.visit_definition_ids)
                if key == "visit_definition_ids"
                else getattr(phase, key)
            )
            for key in changes
        }
        visit_changes = changes.pop("visit_definition_ids", None)
        for key, value in changes.items():
            setattr(phase, key, value)
        if visit_changes is not None:
            await self._replace_visits(session, phase, visit_changes)
            changes["visit_definition_ids"] = visit_changes
        phase.updated_at = datetime.now(UTC)

        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject_phase_definition",
            entity_id=phase.id,
            action="update",
            module=Module.DESIGNER,
            old_value=str(old_values),
            new_value=str(changes),
            actor_id=actor_id,
        )

        logger.info(
            "Subject phase definition updated: id=%s changes=%s",
            phase.id,
            list(changes),
        )
        return await self._get_live_phase(session, phase.id)

    @staticmethod
    def _validate_visit_membership(
        phase_type: SubjectPhaseType, visit_definition_ids: list[UUID]
    ) -> None:
        if phase_type not in _VISIT_PHASE_TYPES and visit_definition_ids:
            raise ValidationError(
                "Arm and complete subject phases cannot have associated visits",
                details={
                    "field": "visit_definition_ids",
                    "phase_type": phase_type.value,
                },
            )

    async def _replace_visits(
        self,
        session: AsyncSession,
        phase: SubjectPhaseDefinition,
        visit_definition_ids: list[UUID],
    ) -> None:
        """Replace a phase's ordered visit membership after scope validation."""
        ordered_ids = list(dict.fromkeys(visit_definition_ids))
        if len(ordered_ids) != len(visit_definition_ids):
            raise ValidationError(
                "A subject phase cannot contain the same visit more than once",
                details={"field": "visit_definition_ids"},
            )

        visits: list[VisitDefinition] = []
        if ordered_ids:
            result = await session.execute(
                select(VisitDefinition).where(VisitDefinition.id.in_(ordered_ids))
            )
            found = {visit.id: visit for visit in result.scalars().all()}
            invalid_ids = [
                visit_id
                for visit_id in ordered_ids
                if visit_id not in found
                or found[visit_id].study_version_id != phase.design_version_id
                or found[visit_id].definition_kind not in {"visit", "cycle_visit"}
            ]
            if invalid_ids:
                raise ValidationError(
                    "Subject phases may reference only visits or cycle visits from the same design version",
                    details={
                        "field": "visit_definition_ids",
                        "invalid_ids": [str(value) for value in invalid_ids],
                    },
                )
            visits = [found[visit_id] for visit_id in ordered_ids]

        await session.execute(
            delete(SubjectPhaseVisitDefinition).where(
                SubjectPhaseVisitDefinition.subject_phase_definition_id == phase.id
            )
        )
        for position, visit in enumerate(visits, start=1):
            session.add(
                SubjectPhaseVisitDefinition(
                    subject_phase_definition_id=phase.id,
                    visit_definition_id=visit.id,
                    display_order=position,
                )
            )
        await session.flush()
        session.expire(phase, ["visits"])

    async def delete_phase_definition(
        self,
        session: AsyncSession,
        phase_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        """Soft-delete a phase, cascading to its incident transition edges.

        Every live transition whose source or target is this phase is
        soft-deleted first (one ``delete`` audit event per cascaded edge noting
        the cascade), then the phase itself is soft-deleted — all in the
        caller's transaction so the data and audit commit atomically.
        """
        phase = await self._get_live_phase(session, phase_id)

        incident = await session.execute(
            select(SubjectPhaseTransition).where(
                or_(
                    SubjectPhaseTransition.from_phase_id == phase_id,
                    SubjectPhaseTransition.to_phase_id == phase_id,
                ),
                SubjectPhaseTransition.deleted_at.is_(None),
            )
        )
        now = datetime.now(UTC)
        for edge in incident.scalars().all():
            edge.deleted_at = now
            await session.flush()
            await audit_service.record(
                session,
                entity_type="subject_phase_transition",
                entity_id=edge.id,
                action="delete",
                module=Module.DESIGNER,
                old_value=(
                    f"cascade from phase {phase_id}; "
                    f"from_phase_id={edge.from_phase_id}; "
                    f"to_phase_id={edge.to_phase_id}"
                ),
                actor_id=actor_id,
            )

        phase.deleted_at = now
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject_phase_definition",
            entity_id=phase.id,
            action="delete",
            module=Module.DESIGNER,
            old_value=f"name={phase.name}; display_order={phase.display_order}",
            actor_id=actor_id,
        )

        logger.info("Subject phase definition soft-deleted: id=%s", phase.id)


# Module-level singleton for convenience
subject_phase_service = SubjectPhaseService()
