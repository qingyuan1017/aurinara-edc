"""Subject_Phase_Transition_Service — authoring of subject-phase transitions.

Owns creation of design-time ``Subject_Phase_Transition`` edges within a
``Draft_Design``. A transition expresses that a subject may move from one phase
to another. The service validates that both phases exist, are live, and share
the edge's ``Design_Version``, rejects a self-transition, and rejects a
duplicate edge. Mirrors ``visit_dependency_service.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.designer.subject_phase_transition import SubjectPhaseTransition

logger = logging.getLogger(__name__)


class SubjectPhaseTransitionService:
    """Creates and validates Subject_Phase_Transition edges for a Draft_Design."""

    async def create_transition(
        self,
        session: AsyncSession,
        *,
        design_version_id: UUID,
        from_phase_id: UUID,
        to_phase_id: UUID,
        label: str | None = None,
        condition_expression: str | None = None,
        actor_id: UUID | None = None,
    ) -> SubjectPhaseTransition:
        """Persist a subject-phase-to-phase transition edge.

        Args:
            session: The active async session (caller's transaction).
            design_version_id: The owning Design_Version.
            from_phase_id: The source phase.
            to_phase_id: The target phase.
            label: Optional presentation label.
            condition_expression: Optional condition driving the transition.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted SubjectPhaseTransition.

        Raises:
            ValidationError: On a self-transition or phases that do not belong to
                this design version.
            NotFoundError: If either phase does not exist (or is soft-deleted).
            ConflictError: If an identical edge already exists.
        """
        # (1) self-guard.
        if from_phase_id == to_phase_id:
            raise ValidationError(
                "A subject phase cannot transition to itself",
                details={"field": "to_phase_id"},
            )

        # (2) existence + same-version guard on live phases.
        result = await session.execute(
            select(
                SubjectPhaseDefinition.id,
                SubjectPhaseDefinition.design_version_id,
            ).where(
                SubjectPhaseDefinition.id.in_([from_phase_id, to_phase_id]),
                SubjectPhaseDefinition.deleted_at.is_(None),
            )
        )
        versions = {row[0]: row[1] for row in result.all()}
        missing = [str(pid) for pid in (from_phase_id, to_phase_id) if pid not in versions]
        if missing:
            raise NotFoundError(
                "One or more subject phase definitions were not found",
                details={"missing_subject_phase_ids": missing},
            )
        if (
            versions[from_phase_id] != versions[to_phase_id]
            or versions[from_phase_id] != design_version_id
        ):
            raise ValidationError(
                "A subject phase transition must link two phases in the "
                "transition's design version",
                details={"field": "to_phase_id"},
            )

        # (3) duplicate guard (ignoring soft-deleted edges).
        existing = await session.execute(
            select(SubjectPhaseTransition.id).where(
                SubjectPhaseTransition.design_version_id == design_version_id,
                SubjectPhaseTransition.from_phase_id == from_phase_id,
                SubjectPhaseTransition.to_phase_id == to_phase_id,
                SubjectPhaseTransition.deleted_at.is_(None),
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "This subject phase transition already exists",
                details={
                    "design_version_id": str(design_version_id),
                    "from_phase_id": str(from_phase_id),
                    "to_phase_id": str(to_phase_id),
                },
            )

        # (4) normalize optional text fields.
        normalized_label = label.strip() if label is not None else None
        if normalized_label == "":
            normalized_label = None
        normalized_condition = (
            condition_expression.strip() if condition_expression is not None else None
        )
        if normalized_condition == "":
            normalized_condition = None

        transition = SubjectPhaseTransition(
            design_version_id=design_version_id,
            from_phase_id=from_phase_id,
            to_phase_id=to_phase_id,
            label=normalized_label,
            condition_expression=normalized_condition,
        )
        session.add(transition)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject_phase_transition",
            entity_id=transition.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"from_phase_id={from_phase_id}; to_phase_id={to_phase_id}; "
                f"label={normalized_label}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Subject phase transition created: id=%s design_version_id=%s from=%s to=%s",
            transition.id,
            design_version_id,
            from_phase_id,
            to_phase_id,
        )
        return transition

    async def list_transitions(
        self,
        session: AsyncSession,
        design_version_id: UUID,
    ) -> list[SubjectPhaseTransition]:
        """List a version's live transition edges ordered by creation time.

        Excludes edges whose source or target phase has been soft-deleted
        (defense-in-depth; the phase-delete cascade already soft-deletes
        incident edges).
        """
        from_phase = SubjectPhaseDefinition.__table__.alias("from_phase")
        to_phase = SubjectPhaseDefinition.__table__.alias("to_phase")
        result = await session.execute(
            select(SubjectPhaseTransition)
            .join(from_phase, from_phase.c.id == SubjectPhaseTransition.from_phase_id)
            .join(to_phase, to_phase.c.id == SubjectPhaseTransition.to_phase_id)
            .where(
                SubjectPhaseTransition.design_version_id == design_version_id,
                SubjectPhaseTransition.deleted_at.is_(None),
                from_phase.c.deleted_at.is_(None),
                to_phase.c.deleted_at.is_(None),
            )
            .order_by(SubjectPhaseTransition.created_at, SubjectPhaseTransition.id)
        )
        return list(result.scalars().all())

    async def delete_transition(
        self,
        session: AsyncSession,
        transition_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> None:
        """Soft-delete a transition edge, raising ``NotFoundError`` if missing."""
        result = await session.execute(
            select(SubjectPhaseTransition).where(
                SubjectPhaseTransition.id == transition_id,
                SubjectPhaseTransition.deleted_at.is_(None),
            )
        )
        transition = result.scalars().first()
        if transition is None:
            raise NotFoundError(
                "Subject phase transition not found",
                details={"transition_id": str(transition_id)},
            )

        transition.deleted_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject_phase_transition",
            entity_id=transition.id,
            action="delete",
            module=Module.DESIGNER,
            old_value=(
                f"from_phase_id={transition.from_phase_id}; to_phase_id={transition.to_phase_id}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Subject phase transition soft-deleted: id=%s",
            transition.id,
        )


# Module-level singleton for convenience
subject_phase_transition_service = SubjectPhaseTransitionService()
