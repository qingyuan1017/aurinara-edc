"""Visit_Service — operational visit instances and window-status computation.

As part of the Designer / EDC refactor the **definition-authoring** part of
visits was reassigned to the Designer module and now lives in
``app.services.designer.visit_definition_service`` (``VisitDefinitionService`` /
``visit_definition_service``). This EDC service keeps the **operational** part:
initializing Visit_Instances from a bound Design_Version, recording visit dates
and computing window status, creating unscheduled visits, and marking visits
missed.

For backward compatibility ``VisitService.define_visit`` is retained here as a
thin wrapper that delegates to the Designer service; existing callers and import
paths (``from app.services.edc.visit_service import visit_service``) keep working
unchanged (R11.1).

All metadata and clinical mutations write an Audit_Event within the caller's
transaction (data + audit commit atomically).

Satisfies Requirements:
  - 4.2 / 4.3: Visit definition authoring (now Designer-owned; delegated).
  - 8.2: Create Visit_Instances from a bound Study_Version's visit definitions.
  - 8.3: Compute visit window status (before_window, in_window, after_window)
          from the visit date relative to the configured window bounds.
  - 8.4: Allow creation of an unscheduled Visit_Instance.
  - 8.5: Mark a Visit_Instance as missed.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.designer.study_version import StudyVersion
from app.models.designer.visit import VisitDefinition
from app.models.edc.form_data import FormInstance, FormInstanceStatus
from app.models.edc.form_record import FormRecord
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.schemas.edc.visit import (
    AddableVisitCreate,
    UnscheduledVisitCreate,
    VisitDefinitionCreate,
)
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.designer.visit_definition_service import visit_definition_service
from app.services.edc.form_instance_service import form_instance_service
from app.services.edc.revision_service import clinical_revision_service

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
    """Manages visit instance initialization and window status (operational EDC)."""

    def __init__(self, design_service: DesignConsumptionService | None = None) -> None:
        self._design = design_service or design_consumption_service

    # ------------------------------------------------------------------
    # Define visit (Req 4.2 / 4.3) — Designer-owned; delegated for compatibility
    # ------------------------------------------------------------------

    async def define_visit(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: VisitDefinitionCreate,
        actor_id: UUID,
    ) -> VisitDefinition:
        """Define a visit on a draft Design_Version (Requirements 4.2, 4.3).

        Backward-compatible delegate: visit definition authoring is owned by the
        Designer module's ``visit_definition_service``. This method forwards to
        it so existing callers that reach the EDC ``visit_service`` keep working.

        Args:
            session: Active async database session (caller's transaction).
            version: The owning StudyVersion (must be draft).
            data: Validated VisitDefinitionCreate schema.
            actor_id: UUID of the user performing the action.

        Returns:
            The created VisitDefinition.

        Raises:
            BusinessRuleError: If the owning version is published (Req 2.4).
            ValidationError: If the window bounds are inverted (Req 4.3).
        """
        return await visit_definition_service.define_visit(session, version, data, actor_id)

    # ------------------------------------------------------------------
    # Initialize instances (Req 8.2)
    # ------------------------------------------------------------------

    async def initialize_instances(
        self,
        session: AsyncSession,
        subject: Subject,
        actor_id: UUID | None = None,
        *,
        definition_ids: set[UUID] | None = None,
        skip_existing: bool = False,
    ) -> list[VisitInstance]:
        """Create Visit_Instances from the subject's bound Study_Version (Req 8.2).

        ``definition_ids`` limits activation to the visits belonging to a
        subject phase (or selected arm SoA). ``None`` retains the legacy
        all-protocol-visits behavior for designs without subject phases.
        ``skip_existing`` makes phase transitions safe to retry.

        Args:
            session: Active async database session.
            subject: The Subject whose visit instances are being initialized.
            actor_id: Optional UUID of the user performing the action.

        Returns:
            The list of created VisitInstance objects (ordered by definition display order).
        """
        if definition_ids == set():
            return []

        definition_query = (
            select(VisitDefinition)
            .where(
                VisitDefinition.study_version_id == subject.study_version_id,
                VisitDefinition.definition_kind.in_({"visit", "cycle_visit"}),
                VisitDefinition.addable.is_(False),
            )
            .order_by(VisitDefinition.display_order)
        )
        if definition_ids is not None:
            definition_query = definition_query.where(VisitDefinition.id.in_(definition_ids))
        result = await session.execute(definition_query)
        definitions = result.scalars().all()

        existing_definition_ids: set[UUID] = set()
        if skip_existing and definitions:
            existing_result = await session.execute(
                select(VisitInstance.visit_definition_id).where(
                    VisitInstance.subject_id == subject.id,
                    VisitInstance.visit_definition_id.in_(
                        [definition.id for definition in definitions]
                    ),
                )
            )
            existing_definition_ids = {
                definition_id
                for definition_id in existing_result.scalars().all()
                if definition_id is not None
            }

        instances: list[VisitInstance] = []
        for definition in definitions:
            if definition.id in existing_definition_ids:
                continue
            instance = VisitInstance(
                subject_id=subject.id,
                visit_definition_id=definition.id,
                name=definition.name,
                status=VisitInstanceStatus.scheduled,
                is_user_added=False,
                design_version_id=subject.study_version_id,
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

    async def list_addable_definitions(
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        allowed_definition_ids: set[UUID] | None = None,
    ) -> list[VisitDefinition]:
        """List addable real visit leaves from the subject's bound design."""
        statement = (
            select(VisitDefinition)
            .where(
                VisitDefinition.study_version_id == subject.study_version_id,
                VisitDefinition.definition_kind.in_({"visit", "cycle_visit"}),
                VisitDefinition.addable.is_(True),
            )
            .order_by(VisitDefinition.display_order, VisitDefinition.id)
        )
        if allowed_definition_ids is not None:
            # Unscheduled visits are a design-level capability rather than a
            # scheduled phase occurrence. Keep them available throughout the
            # subject lifecycle while phase-scoping other addable visits.
            statement = statement.where(
                or_(
                    VisitDefinition.id.in_(allowed_definition_ids),
                    VisitDefinition.visit_type == "unscheduled",
                )
            )
        result = await session.execute(statement)
        return list(result.scalars().all())

    async def create_addable(
        self,
        session: AsyncSession,
        subject: Subject,
        data: AddableVisitCreate,
        actor_id: UUID,
        *,
        allowed_definition_ids: set[UUID] | None = None,
    ) -> VisitInstance:
        """Create another visit occurrence only when the published design permits it."""
        definitions = await self.list_addable_definitions(
            session,
            subject,
            allowed_definition_ids=allowed_definition_ids,
        )
        definition = next(
            (item for item in definitions if item.id == data.visit_definition_id),
            None,
        )
        if definition is None:
            raise ValidationError(
                "Visit definition is not addable for this subject",
                details={"field": "visit_definition_id"},
            )

        status = (
            VisitInstanceStatus.unscheduled
            if definition.visit_type == "unscheduled"
            else VisitInstanceStatus.scheduled
        )
        instance = VisitInstance(
            subject_id=subject.id,
            visit_definition_id=definition.id,
            name=definition.name,
            visit_date=data.visit_date,
            status=status,
            is_user_added=True,
            design_version_id=subject.study_version_id,
        )
        session.add(instance)
        await session.flush()
        await form_instance_service.initialize_for_visit(session, subject, instance, actor_id)
        await audit_service.record(
            session,
            entity_type="visit_instance",
            entity_id=instance.id,
            action="create_addable",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            new_value=(
                f"visit_definition_id={definition.id}, name={instance.name}, "
                f"status={instance.status}"
            ),
        )
        return instance

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
        self._guard_not_added_in_error(instance)
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
        clinical_revision_service.bump_visit(instance)
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
        permits_unscheduled = await self._design.permits_unscheduled_visits(
            session, subject.study_version_id
        )
        if not permits_unscheduled:
            raise BusinessRuleError(
                message="The bound published design does not permit unscheduled visits",
                details={
                    "design_version_id": str(subject.study_version_id),
                    "subject_id": str(subject.id),
                },
            )

        instance = VisitInstance(
            subject_id=subject.id,
            visit_definition_id=None,
            name=data.name,
            visit_date=data.visit_date,
            status=VisitInstanceStatus.unscheduled,
            is_user_added=True,
            design_version_id=subject.study_version_id,
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
        self._guard_not_added_in_error(instance)
        old_status = instance.status if isinstance(instance.status, str) else instance.status.value
        instance.status = VisitInstanceStatus.missed
        instance.updated_at = datetime.now(UTC)
        clinical_revision_service.bump_visit(instance)
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

    async def mark_added_in_error(
        self,
        session: AsyncSession,
        instance: VisitInstance,
        actor_id: UUID,
        reason: str,
    ) -> VisitInstance:
        """Void a user-added visit while retaining its immutable history."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError(
                "Reason is required when marking a visit as added in error",
                details={"field": "reason"},
            )
        if not instance.is_user_added:
            raise BusinessRuleError(
                message="Only a user-added visit can be marked as added in error",
                details={"visit_instance_id": str(instance.id)},
            )
        self._guard_not_added_in_error(instance)
        if await self._has_clinical_data(session, instance.id):
            raise BusinessRuleError(
                message=(
                    "Visit cannot be marked as added in error after clinical data entry; "
                    "use the controlled data-correction workflow"
                ),
                details={"visit_instance_id": str(instance.id)},
            )

        old_status = instance.status if isinstance(instance.status, str) else instance.status.value
        instance.status = VisitInstanceStatus.added_in_error
        instance.updated_at = datetime.now(UTC)
        clinical_revision_service.bump_visit(instance)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="visit_instance",
            entity_id=instance.id,
            action="mark_added_in_error",
            subject_id=instance.subject_id,
            actor_id=actor_id,
            field_name="status",
            old_value=old_status,
            new_value=VisitInstanceStatus.added_in_error.value,
            reason=normalized_reason,
        )
        logger.info("Visit marked added in error: instance_id=%s actor=%s", instance.id, actor_id)
        return instance

    @staticmethod
    def _guard_not_added_in_error(instance: VisitInstance) -> None:
        if instance.status == VisitInstanceStatus.added_in_error:
            raise BusinessRuleError(
                message="A visit marked as added in error cannot be modified",
                details={"visit_instance_id": str(instance.id)},
            )

    @staticmethod
    async def _has_clinical_data(session: AsyncSession, instance_id: UUID) -> bool:
        result = await session.execute(
            select(FormInstance).where(FormInstance.visit_instance_id == instance_id)
        )
        forms = list(result.scalars().all())
        if any(
            form.data_jsonb is not None
            or form.submitted_at is not None
            or form.status != FormInstanceStatus.not_started
            or form.data_entry_status != FormInstanceStatus.not_started.value
            or bool(form.field_values)
            for form in forms
        ):
            return True
        if not forms:
            return False
        record_result = await session.execute(
            select(FormRecord.id)
            .where(FormRecord.form_instance_id.in_([form.id for form in forms]))
            .limit(1)
        )
        return record_result.scalar_one_or_none() is not None

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_instance(self, session: AsyncSession, instance_id: UUID) -> VisitInstance:
        """Retrieve a VisitInstance by its primary key.

        Args:
            session: Active async database session.
            instance_id: The UUID of the visit instance.

        Returns:
            The VisitInstance.

        Raises:
            NotFoundError: If no visit instance exists with the given ID.
        """
        result = await session.execute(select(VisitInstance).where(VisitInstance.id == instance_id))
        instance = result.scalars().first()
        if instance is None:
            raise NotFoundError(
                message="Visit instance not found",
                details={"visit_instance_id": str(instance_id)},
            )
        return instance


# Module-level singleton for convenience
visit_service = VisitService()
