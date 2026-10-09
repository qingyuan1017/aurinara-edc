"""Visit_Dependency_Service — authoring of visit-to-visit dependencies.

Owns creation of design-time ``Visit_Definition_Dependency`` edges within a
``Draft_Design``. A dependency expresses that one visit depends on another;
because a cycle is now a visit, this also covers cycle dependencies. The service
validates that both visits exist and share a Design_Version, rejects a
self-dependency, and rejects a duplicate edge.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.visit import VisitDefinition
from app.models.designer.visit_dependency import VisitDefinitionDependency

logger = logging.getLogger(__name__)

_DEPENDENCY_TYPE_MIN_LENGTH = 1
_DEPENDENCY_TYPE_MAX_LENGTH = 50


class VisitDependencyService:
    """Creates and validates Visit_Definition_Dependency edges for a Draft_Design."""

    async def create_dependency(
        self,
        session: AsyncSession,
        *,
        visit_definition_id: UUID,
        depends_on_visit_definition_id: UUID,
        dependency_type: str = "prerequisite",
        condition_expression: str | None = None,
        actor_id: UUID | None = None,
    ) -> VisitDefinitionDependency:
        """Persist a visit-to-visit dependency edge.

        Args:
            session: The active async session (caller's transaction).
            visit_definition_id: The dependent visit.
            depends_on_visit_definition_id: The visit it depends on.
            dependency_type: Typed dependency; defaults to ``"prerequisite"``.
            condition_expression: Optional condition driving the dependency.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted VisitDefinitionDependency.

        Raises:
            ValidationError: On a self-dependency, an out-of-range dependency
                type, or visits belonging to different design versions.
            NotFoundError: If either visit does not exist.
            ConflictError: If an identical edge already exists.
        """
        normalized_type = dependency_type.strip()
        if not (_DEPENDENCY_TYPE_MIN_LENGTH <= len(normalized_type) <= _DEPENDENCY_TYPE_MAX_LENGTH):
            raise ValidationError(
                "Dependency type must be 1 to 50 characters",
                details={"field": "dependency_type"},
            )

        if visit_definition_id == depends_on_visit_definition_id:
            raise ValidationError(
                "A visit cannot depend on itself",
                details={"field": "depends_on_visit_definition_id"},
            )

        result = await session.execute(
            select(VisitDefinition.id, VisitDefinition.study_version_id).where(
                VisitDefinition.id.in_([visit_definition_id, depends_on_visit_definition_id])
            )
        )
        versions = {row[0]: row[1] for row in result.all()}
        missing = [
            str(vid)
            for vid in (visit_definition_id, depends_on_visit_definition_id)
            if vid not in versions
        ]
        if missing:
            raise NotFoundError(
                "One or more visit definitions were not found",
                details={"missing_visit_definition_ids": missing},
            )
        if versions[visit_definition_id] != versions[depends_on_visit_definition_id]:
            raise ValidationError(
                "A visit dependency must link two visits in the same design version",
                details={"field": "depends_on_visit_definition_id"},
            )

        existing = await session.execute(
            select(VisitDefinitionDependency.id).where(
                VisitDefinitionDependency.visit_definition_id == visit_definition_id,
                VisitDefinitionDependency.depends_on_visit_definition_id
                == depends_on_visit_definition_id,
                VisitDefinitionDependency.dependency_type == normalized_type,
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "This visit dependency already exists",
                details={
                    "visit_definition_id": str(visit_definition_id),
                    "depends_on_visit_definition_id": str(depends_on_visit_definition_id),
                    "dependency_type": normalized_type,
                },
            )

        normalized_condition = (
            condition_expression.strip() if condition_expression is not None else None
        )
        if normalized_condition == "":
            normalized_condition = None

        dependency = VisitDefinitionDependency(
            visit_definition_id=visit_definition_id,
            depends_on_visit_definition_id=depends_on_visit_definition_id,
            dependency_type=normalized_type,
            condition_expression=normalized_condition,
        )
        session.add(dependency)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="visit_definition_dependency",
            entity_id=dependency.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"visit_definition_id={visit_definition_id}; "
                f"depends_on_visit_definition_id={depends_on_visit_definition_id}; "
                f"dependency_type={normalized_type}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Visit dependency created: id=%s visit=%s depends_on=%s type=%r",
            dependency.id,
            visit_definition_id,
            depends_on_visit_definition_id,
            normalized_type,
        )
        return dependency

    async def list_dependencies(
        self,
        session: AsyncSession,
        visit_definition_id: UUID,
    ) -> list[VisitDefinitionDependency]:
        """List a visit's outgoing dependency edges ordered by creation time."""
        result = await session.execute(
            select(VisitDefinitionDependency)
            .where(VisitDefinitionDependency.visit_definition_id == visit_definition_id)
            .order_by(VisitDefinitionDependency.created_at, VisitDefinitionDependency.id)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience
visit_dependency_service = VisitDependencyService()
