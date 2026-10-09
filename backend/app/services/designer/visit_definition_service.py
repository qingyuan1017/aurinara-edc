"""Visit_Definition_Service — Designer-owned visit definition authoring.

Reassigned from the EDC module's ``visit_service`` to the Designer module as
part of the Designer / EDC refactor. This service owns the **definition-authoring
part** of visits: creating Visit_Definitions within a draft ``Design_Version``
(``study_versions``). The operational part (visit instances, window-status
computation, unscheduled visits, mark-missed) stays in
``app.services.edc.visit_service``.

Authoring is allowed **only while the owning Design_Version is in draft**
(enforced via ``study_version_service.guard_mutable``), and every mutation
writes an Audit_Event within the caller's transaction (data + audit commit
atomically).

Satisfies Requirements:
  - 2.4: Reject modifications to a published version's child visit definitions
          (via guard_mutable).
  - 4.2: Persist a Visit_Definition with name (1-100), visit number (1-9999),
          integer target day (0-99999), and integer lower/upper window bounds
          (0-99999) where the lower bound is no greater than the upper bound.
  - 4.3: Reject a Visit_Definition whose lower window bound exceeds its upper
          window bound, persisting nothing and returning an error that
          identifies the invalid window.
  - 11.1: Ownership reassignment with no stored-value changes.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.study_version import StudyVersion
from app.models.designer.visit import VisitDefinition
from app.schemas.designer.visit import VisitDefinitionCreate
from app.services.edc.study_version_service import study_version_service

logger = logging.getLogger(__name__)


class VisitDefinitionService:
    """Authors Visit_Definitions within a draft Design_Version (Requirement 4.2)."""

    @staticmethod
    def _validate_window(data: VisitDefinitionCreate) -> None:
        """Reject a definition whose lower window bound exceeds its upper bound.

        The acceptable window is ``[target_day - window_before, target_day +
        window_after]``. ``window_before`` is the lower bound and ``window_after``
        the upper bound (both measured as non-negative offsets from the target
        day). When both offsets are provided they must leave the lower edge no
        later than the upper edge — i.e. ``-window_before <= window_after``.
        Because both are constrained to be ``>= 0`` by the schema, the only way
        the lower edge can exceed the upper edge is a negative offset, which the
        schema already forbids; this guard additionally rejects any explicitly
        inverted window and identifies it in the error (Requirement 4.3).

        Args:
            data: The validated create payload.

        Raises:
            ValidationError: If the window bounds are inverted (lower > upper),
                with details identifying the invalid window.
        """
        lower = data.window_before
        upper = data.window_after

        # Only compare when both bounds are present; a missing bound leaves the
        # window open on that side and cannot be inverted.
        if lower is None or upper is None:
            return

        lower_edge = -lower
        upper_edge = upper
        if lower_edge > upper_edge:
            raise ValidationError(
                message=(
                    "Visit definition window is invalid: the lower window bound "
                    "exceeds the upper window bound"
                ),
                details={
                    "visit_name": data.name,
                    "visit_number": data.visit_number,
                    "window_before": lower,
                    "window_after": upper,
                },
            )

    @staticmethod
    def _validate_cycle_fields(data: VisitDefinitionCreate) -> None:
        """Enforce the cycle-only metadata invariant.

        ``repeat_min`` / ``repeat_max`` / ``cycle_length`` are meaningful only
        for a cycle visit (``visit_type == 'cycle'``). A plain visit that carries
        any of them is rejected. When both repeat bounds are present they must
        satisfy ``repeat_min <= repeat_max``.

        Raises:
            ValidationError: If a non-cycle visit sets cycle metadata, or if the
                repeat bounds are inverted; the error identifies the field.
        """
        is_cycle = data.visit_type == "cycle"
        if not is_cycle and (
            data.repeat_min is not None
            or data.repeat_max is not None
            or data.cycle_length is not None
        ):
            raise ValidationError(
                "repeat_min/repeat_max/cycle_length are only valid when visit_type == 'cycle'",
                details={"field": "visit_type"},
            )
        if (
            data.repeat_min is not None
            and data.repeat_max is not None
            and data.repeat_min > data.repeat_max
        ):
            raise ValidationError(
                "repeat_min must not exceed repeat_max",
                details={
                    "field": "repeat_min",
                    "repeat_min": data.repeat_min,
                    "repeat_max": data.repeat_max,
                },
            )

    async def define_visit(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: VisitDefinitionCreate,
        actor_id: UUID,
    ) -> VisitDefinition:
        """Define a visit on a draft Design_Version (Requirements 4.2, 4.3, 2.4).

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
        # Block metadata writes on a published version (Req 2.4).
        study_version_service.guard_mutable(version)

        # Reject an inverted window before persisting anything (Req 4.3).
        self._validate_window(data)

        # Cycle-only metadata is accepted only for a cycle visit.
        self._validate_cycle_fields(data)

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
            repeat_min=data.repeat_min,
            repeat_max=data.repeat_max,
            cycle_length=data.cycle_length,
        )
        session.add(definition)
        await session.flush()  # Assign the id

        await audit_service.record(
            session,
            entity_type="visit_definition",
            entity_id=definition.id,
            action="create",
            module=Module.DESIGNER,
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

    async def list_definitions(
        self,
        session: AsyncSession,
        version_id: UUID,
    ) -> list[VisitDefinition]:
        """List a version's Visit_Definitions ordered by display order.

        Reads are not audited (matching the other Designer list reads).

        Args:
            session: Active async database session.
            version_id: The owning Design_Version id.

        Returns:
            The version's VisitDefinitions ordered by ``display_order``.
        """
        result = await session.execute(
            select(VisitDefinition)
            .where(VisitDefinition.study_version_id == version_id)
            .order_by(VisitDefinition.display_order)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience
visit_definition_service = VisitDefinitionService()
