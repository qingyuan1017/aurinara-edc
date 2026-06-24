"""Visit_Service — visit definitions, instances, and window-status computation.

Satisfies Requirements:
  - 8.1: Persist visit definitions (name, visit number, type, target day, window
          bounds, display order, required flag) while the owning version is draft.
  - 8.2: Create Visit_Instances from a bound Study_Version's visit definitions.
  - 8.3: Compute visit window status (before_window, in_window, after_window)
          from the visit date relative to the configured window bounds.
  - 8.4: Allow creation of an unscheduled Visit_Instance.
  - 8.5: Mark a Visit_Instance as missed.

All metadata and clinical mutations write an Audit_Event within the caller's
transaction (data + audit commit atomically).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import NotFoundError
from app.models.study import StudyVersion
from app.models.subject import Subject
from app.models.visit import VisitDefinition, VisitInstance, VisitInstanceStatus
from app.schemas.visit import (
    UnscheduledVisitCreate,
    VisitDefinitionCreate,
)
from app.services.study_version_service import study_version_service

logger = logging.getLogger(__name__)

# Window status string constants (mirror the visit_instances.window_status column).
WINDOW_BEFORE = "before_window"
WINDOW_IN = "in_window"
WINDOW_AFTER = "after_window"


def compute_window_status(
    target_day: int | None,
    window_before: int | None,
    window_after: int | None,
    day_offset: int | None,
) -> str | None:
    """Compute the visit window status from a day offset relative to target_day.

    The acceptable window is ``[target_day - window_before, target_day + window_after]``.

    Args:
        target_day: Target day relative to baseline; None disables computation.
        window_before: Days before target still considered in window (treated as 0 if None).
        window_after: Days after target still considered in window (treated as 0 if None).
        day_offset: Actual visit day offset relative to baseline; None disables computation.

    Returns:
        One of ``"before_window"``, ``"in_window"``, ``"after_window"``, or None
        when the status cannot be computed (missing target_day or day_offset).
    """
    if target_day is None or day_offset is None:
        return None

    before = window_before if window_before is not None else 0
    after = window_after if window_after is not None else 0

    lower_bound = target_day - before
    upper_bound = target_day + after

    if day_offset < lower_bound:
        return WINDOW_BEFORE
    if day_offset > upper_bound:
        return WINDOW_AFTER
    return WINDOW_IN


class VisitService:
    """Manages visit definitions, instance initialization, and window status."""

    # ------------------------------------------------------------------
    # Define visit (Req 8.1) — draft only
    # ------------------------------------------------------------------

    async def define_visit(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: VisitDefinitionCreate,
        actor_id: UUID,
    ) -> VisitDefinition:
        """Define a visit on a draft Study_Version (Requirement 8.1).

        Args:
            session: Active async database session (caller's transaction).
            version: The owning StudyVersion (must be draft).
            data: Validated VisitDefinitionCreate schema.
            actor_id: UUID of the user performing the action.

        Returns:
            The created VisitDefinition.

        Raises:
            BusinessRuleError: If the owning version is published (Req 5.2).
        """
        # Block metadata writes on a published version (Req 5.2)
        study_version_service.guard_mutable(version)

        definition = VisitDefinition(
            study_version_id=version.id,
            name=data.name,
            visit_number=data.visit_number,
            visit_type=data.visit_type,
            target_day=data.target_day,
            window_before=data.window_before,
            window_after=data.window_after,
            display_order=data.display_order,
            is_required=data.is_required,
        )
        session.add(definition)
        await session.flush()  # Assign the id

        await audit_service.record(
            session,
            entity_type="visit_definition",
            entity_id=definition.id,
            action="create",
            study_id=version.study_id,
            actor_id=actor_id,
            new_value=f"name={definition.name}, visit_number={definition.visit_number}",
        )

        logger.info(
            "Visit definition created: id=%s version_id=%s name=%s actor=%s",
            definition.id,
            version.id,
            definition.name,
            actor_id,
        )
        return definition

    # ------------------------------------------------------------------
    # Initialize instances (Req 8.2)
    # ------------------------------------------------------------------

    async def initialize_instances(
        self,
        session: AsyncSession,
        subject: Subject,
        actor_id: UUID | None = None,
    ) -> list[VisitInstance]:
        """Create Visit_Instances from the subject's bound Study_Version (Req 8.2).

        Args:
            session: Active async database session.
            subject: The Subject whose visit instances are being initialized.
            actor_id: Optional UUID of the user performing the action.

        Returns:
            The list of created VisitInstance objects (ordered by definition display order).
        """
        result = await session.execute(
            select(VisitDefinition)
            .where(VisitDefinition.study_version_id == subject.study_version_id)
            .order_by(VisitDefinition.display_order)
        )
        definitions = result.scalars().all()

        instances: list[VisitInstance] = []
        for definition in definitions:
            instance = VisitInstance(
                subject_id=subject.id,
                visit_definition_id=definition.id,
                name=definition.name,
                status=VisitInstanceStatus.scheduled,
            )
            session.add(instance)
            instances.append(instance)

        await session.flush()  # Assign ids

        for instance in instances:
            await audit_service.record(
                session,
                entity_type="visit_instance",
                entity_id=instance.id,
                action="create",
                study_id=subject.study_id,
                site_id=subject.site_id,
                subject_id=subject.id,
                actor_id=actor_id,
                new_value=f"name={instance.name}, status={instance.status}",
            )

        logger.info(
            "Visit instances initialized: subject_id=%s count=%d",
            subject.id,
            len(instances),
        )
        return instances

    # ------------------------------------------------------------------
    # Record visit date + window status (Req 8.3)
    # ------------------------------------------------------------------

    async def record_visit_date(
        self,
        session: AsyncSession,
        instance: VisitInstance,
        visit_date: date,
        actor_id: UUID,
        baseline_date: date | None = None,
    ) -> VisitInstance:
        """Record a visit date and compute the window status (Requirement 8.3).

        The window status is derived from the visit date relative to the owning
        definition's ``target_day ± window bounds``. The ``baseline_date`` (day 0)
        anchors the day offset; when it is omitted (or the definition has no
        ``target_day``) the window status is left unset.

        Args:
            session: Active async database session.
            instance: The VisitInstance to update.
            visit_date: The actual date the visit occurred.
            actor_id: UUID of the user performing the action.
            baseline_date: Optional baseline (day 0) anchor for window computation.

        Returns:
            The updated VisitInstance.
        """
        old_date = instance.visit_date
        old_window = instance.window_status

        instance.visit_date = visit_date

        # Compute window status when a definition with a target_day exists and a
        # baseline anchor is available (Req 8.3).
        definition = instance.visit_definition
        day_offset: int | None = None
        if baseline_date is not None:
            day_offset = (visit_date - baseline_date).days

        if definition is not None:
            window_status = compute_window_status(
                definition.target_day,
                definition.window_before,
                definition.window_after,
                day_offset,
            )
        else:
            window_status = None

        instance.window_status = window_status

        # A recorded visit within window moves it forward in its lifecycle.
        if window_status == WINDOW_IN:
            instance.status = VisitInstanceStatus.in_window

        instance.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="visit_instance",
            entity_id=instance.id,
            action="record_visit_date",
            subject_id=instance.subject_id,
            actor_id=actor_id,
            field_name="visit_date",
            old_value=old_date.isoformat() if old_date is not None else None,
            new_value=visit_date.isoformat(),
        )

        logger.info(
            "Visit date recorded: instance_id=%s date=%s window=%s (was window=%s) actor=%s",
            instance.id,
            visit_date.isoformat(),
            window_status,
            old_window,
            actor_id,
        )
        return instance

    # ------------------------------------------------------------------
    # Create unscheduled visit (Req 8.4)
    # ------------------------------------------------------------------

    async def create_unscheduled(
        self,
        session: AsyncSession,
        subject: Subject,
        data: UnscheduledVisitCreate,
        actor_id: UUID,
    ) -> VisitInstance:
        """Create an unscheduled Visit_Instance for a subject (Requirement 8.4).

        Unscheduled visits have no source visit definition.

        Args:
            session: Active async database session.
            subject: The Subject the visit belongs to.
            data: Validated UnscheduledVisitCreate schema.
            actor_id: UUID of the user performing the action.

        Returns:
            The created VisitInstance with status ``unscheduled``.
        """
        instance = VisitInstance(
            subject_id=subject.id,
            visit_definition_id=None,
            name=data.name,
            visit_date=data.visit_date,
            status=VisitInstanceStatus.unscheduled,
        )
        session.add(instance)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="visit_instance",
            entity_id=instance.id,
            action="create_unscheduled",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            new_value=f"name={instance.name}, status={instance.status}",
        )

        logger.info(
            "Unscheduled visit created: instance_id=%s subject_id=%s name=%s actor=%s",
            instance.id,
            subject.id,
            instance.name,
            actor_id,
        )
        return instance

    # ------------------------------------------------------------------
    # Mark missed (Req 8.5)
    # ------------------------------------------------------------------

    async def mark_missed(
        self,
        session: AsyncSession,
        instance: VisitInstance,
        actor_id: UUID,
    ) -> VisitInstance:
        """Mark a Visit_Instance as missed (Requirement 8.5).

        Args:
            session: Active async database session.
            instance: The VisitInstance to mark missed.
            actor_id: UUID of the user performing the action.

        Returns:
            The updated VisitInstance with status ``missed``.
        """
        old_status = (
            instance.status
            if isinstance(instance.status, str)
            else instance.status.value
        )
        instance.status = VisitInstanceStatus.missed
        instance.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="visit_instance",
            entity_id=instance.id,
            action="mark_missed",
            subject_id=instance.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=old_status,
            new_value=VisitInstanceStatus.missed.value,
        )

        logger.info(
            "Visit marked missed: instance_id=%s actor=%s",
            instance.id,
            actor_id,
        )
        return instance

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_instance(
        self, session: AsyncSession, instance_id: UUID
    ) -> VisitInstance:
        """Retrieve a VisitInstance by its primary key.

        Args:
            session: Active async database session.
            instance_id: The UUID of the visit instance.

        Returns:
            The VisitInstance.

        Raises:
            NotFoundError: If no visit instance exists with the given ID.
        """
        result = await session.execute(
            select(VisitInstance).where(VisitInstance.id == instance_id)
        )
        instance = result.scalars().first()
        if instance is None:
            raise NotFoundError(
                message="Visit instance not found",
                details={"visit_instance_id": str(instance_id)},
            )
        return instance


# Module-level singleton for convenience
visit_service = VisitService()
