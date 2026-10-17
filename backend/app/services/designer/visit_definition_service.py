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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ValidationError
from app.models.designer.study_version import StudyVersion
from app.models.designer.visit import VisitDefinition
from app.models.designer.visit_dependency import VisitDefinitionDependency
from app.schemas.designer.visit import (
    VisitDefinitionCreate,
    VisitDefinitionKind,
    VisitDefinitionUpdate,
)
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
        is_cycle = data.definition_kind == VisitDefinitionKind.cycle or data.visit_type == "cycle"
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

    async def _next_container_number(self, session: AsyncSession, version_id: UUID) -> int:
        result = await session.execute(
            select(func.coalesce(func.max(VisitDefinition.visit_number), 0)).where(
                VisitDefinition.study_version_id == version_id
            )
        )
        return int(result.scalar_one()) + 1

    async def _validate_parent_folder(
        self,
        session: AsyncSession,
        *,
        version_id: UUID,
        parent_folder_id: UUID | None,
    ) -> None:
        if parent_folder_id is None:
            return
        parent = await session.get(VisitDefinition, parent_folder_id)
        if (
            parent is None
            or parent.study_version_id != version_id
            or parent.definition_kind != VisitDefinitionKind.folder
        ):
            raise ValidationError(
                "parent_folder_id must reference a folder in the same design version",
                details={"field": "parent_folder_id"},
            )

    async def define_visit(
        self,
        session: AsyncSession,
        version: StudyVersion,
        data: VisitDefinitionCreate,
        actor_id: UUID,
        *,
        owning_cycle: VisitDefinition | None = None,
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

        if data.definition_kind == VisitDefinitionKind.cycle_visit:
            if (
                owning_cycle is None
                or owning_cycle.study_version_id != version.id
                or owning_cycle.definition_kind != VisitDefinitionKind.cycle
            ):
                raise ValidationError(
                    "A cycle visit must be created inside its owning cycle",
                    details={"field": "definition_kind"},
                )
        elif owning_cycle is not None:
            raise ValidationError(
                "Only a cycle visit can be created inside a cycle",
                details={"field": "definition_kind"},
            )

        # Reject an inverted window before persisting anything (Req 4.3).
        self._validate_window(data)

        # Cycle-only metadata is accepted only for a cycle visit.
        self._validate_cycle_fields(data)

        await self._validate_parent_folder(
            session,
            version_id=version.id,
            parent_folder_id=data.parent_folder_id,
        )

        definition_kind = data.definition_kind
        if data.visit_type == "cycle":
            definition_kind = VisitDefinitionKind.cycle
        visit_number = data.visit_number
        if visit_number is None:
            visit_number = await self._next_container_number(session, version.id)

        definition = VisitDefinition(
            study_version_id=version.id,
            name=data.name,
            visit_number=visit_number,
            visit_type=str(data.visit_type),
            definition_kind=str(definition_kind),
            parent_folder_id=data.parent_folder_id,
            category=str(data.category) if data.category is not None else None,
            subtype=str(data.subtype) if data.subtype is not None else None,
            target_day=data.target_day,
            window_before=data.window_before,
            window_after=data.window_after,
            display_order=data.display_order,
            is_required=data.is_required,
            addable=data.addable,
            repeat_min=data.repeat_min,
            repeat_max=data.repeat_max,
            cycle_length=data.cycle_length,
        )
        session.add(definition)
        await session.flush()  # Assign the id

        if definition_kind == VisitDefinitionKind.cycle_visit:
            session.add(
                VisitDefinitionDependency(
                    visit_definition_id=definition.id,
                    depends_on_visit_definition_id=owning_cycle.id,
                    dependency_type="cycle_member",
                )
            )
            await session.flush()

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

    async def define_cycle_visit(
        self,
        session: AsyncSession,
        version: StudyVersion,
        cycle: VisitDefinition,
        data: VisitDefinitionCreate,
        actor_id: UUID,
    ) -> VisitDefinition:
        """Create a cycle-owned child visit and its membership edge atomically."""
        if (
            cycle.study_version_id != version.id
            or cycle.definition_kind != VisitDefinitionKind.cycle
        ):
            raise ValidationError(
                "Cycle visits can only be created inside a cycle from the same design version",
                details={"field": "cycle_id"},
            )
        owned_data = VisitDefinitionCreate.model_validate(
            data.model_dump()
            | {
                "definition_kind": VisitDefinitionKind.cycle_visit,
                "parent_folder_id": None,
                "member_visit_ids": [],
            }
        )
        return await self.define_visit(
            session,
            version,
            owned_data,
            actor_id,
            owning_cycle=cycle,
        )

    async def get_definition(self, session: AsyncSession, definition_id: UUID) -> VisitDefinition:
        definition = await session.get(VisitDefinition, definition_id)
        if definition is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(
                "Visit definition not found",
                details={"visit_definition_id": str(definition_id)},
            )
        return definition

    async def update_definition(
        self,
        session: AsyncSession,
        version: StudyVersion,
        definition: VisitDefinition,
        data: VisitDefinitionUpdate,
        actor_id: UUID,
    ) -> VisitDefinition:
        study_version_service.guard_mutable(version)
        changes = data.model_dump(exclude_unset=True)
        member_ids = changes.pop("member_visit_ids", None)
        if changes.get("addable") and definition.definition_kind not in {
            VisitDefinitionKind.visit,
            VisitDefinitionKind.cycle_visit,
        }:
            raise ValidationError(
                "Only a visit can be addable",
                details={"field": "addable"},
            )
        for enum_field in ("visit_type", "category", "subtype"):
            if changes.get(enum_field) is not None:
                changes[enum_field] = str(changes[enum_field])
        if "parent_folder_id" in changes:
            await self._validate_parent_folder(
                session,
                version_id=version.id,
                parent_folder_id=changes["parent_folder_id"],
            )
        before = {key: getattr(definition, key) for key in changes}
        for key, value in changes.items():
            setattr(definition, key, value)

        if (
            definition.window_before is not None
            and definition.window_after is not None
            and -definition.window_before > definition.window_after
        ):
            raise ValidationError("Visit definition window is invalid")
        if (
            definition.repeat_min is not None
            and definition.repeat_max is not None
            and definition.repeat_min > definition.repeat_max
        ):
            raise ValidationError("repeat_min must not exceed repeat_max")
        if member_ids is not None:
            raise ValidationError(
                "Cycle membership is read-only; create visits inside their owning cycle",
                details={"field": "member_visit_ids"},
            )
        await session.flush()
        await audit_service.record(
            session,
            entity_type="visit_definition",
            entity_id=definition.id,
            action="update",
            module=Module.DESIGNER,
            study_id=version.study_id,
            actor_id=actor_id,
            old_value=str(before),
            new_value=str(
                changes | ({"member_visit_ids": member_ids} if member_ids is not None else {})
            ),
        )
        return definition

    async def cycle_memberships(
        self, session: AsyncSession, version_id: UUID
    ) -> dict[UUID, list[UUID]]:
        result = await session.execute(
            select(
                VisitDefinitionDependency.depends_on_visit_definition_id,
                VisitDefinitionDependency.visit_definition_id,
            )
            .join(
                VisitDefinition,
                VisitDefinition.id == VisitDefinitionDependency.depends_on_visit_definition_id,
            )
            .where(
                VisitDefinition.study_version_id == version_id,
                VisitDefinitionDependency.dependency_type == "cycle_member",
            )
        )
        memberships: dict[UUID, list[UUID]] = {}
        for cycle_id, visit_id in result.all():
            memberships.setdefault(cycle_id, []).append(visit_id)
        return memberships

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
