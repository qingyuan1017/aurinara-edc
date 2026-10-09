"""Form_Dependency_Service — authoring of form-to-form dependencies.

Owns creation of design-time ``Form_Definition_Dependency`` edges within a
``Draft_Design``. A dependency expresses that one form depends on another (for
example a prerequisite). The service validates that both forms exist and share a
Design_Version, rejects a self-dependency, and rejects a duplicate edge.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.form_dependency import FormDefinitionDependency
from app.models.designer.form_metadata import FormDefinition

logger = logging.getLogger(__name__)

_DEPENDENCY_TYPE_MIN_LENGTH = 1
_DEPENDENCY_TYPE_MAX_LENGTH = 50


class FormDependencyService:
    """Creates and validates Form_Definition_Dependency edges for a Draft_Design."""

    async def create_dependency(
        self,
        session: AsyncSession,
        *,
        form_definition_id: UUID,
        depends_on_form_definition_id: UUID,
        dependency_type: str = "prerequisite",
        condition_expression: str | None = None,
        actor_id: UUID | None = None,
    ) -> FormDefinitionDependency:
        """Persist a form-to-form dependency edge.

        Args:
            session: The active async session (caller's transaction).
            form_definition_id: The dependent form.
            depends_on_form_definition_id: The form it depends on.
            dependency_type: Typed dependency; defaults to ``"prerequisite"``.
            condition_expression: Optional condition driving the dependency.
            actor_id: Optional actor UUID for the audit event.

        Returns:
            The persisted FormDefinitionDependency.

        Raises:
            ValidationError: On a self-dependency, an out-of-range dependency
                type, or forms belonging to different design versions.
            NotFoundError: If either form does not exist.
            ConflictError: If an identical edge already exists.
        """
        normalized_type = dependency_type.strip()
        if not (_DEPENDENCY_TYPE_MIN_LENGTH <= len(normalized_type) <= _DEPENDENCY_TYPE_MAX_LENGTH):
            raise ValidationError(
                "Dependency type must be 1 to 50 characters",
                details={"field": "dependency_type"},
            )

        if form_definition_id == depends_on_form_definition_id:
            raise ValidationError(
                "A form cannot depend on itself",
                details={"field": "depends_on_form_definition_id"},
            )

        result = await session.execute(
            select(FormDefinition.id, FormDefinition.study_version_id).where(
                FormDefinition.id.in_([form_definition_id, depends_on_form_definition_id])
            )
        )
        versions = {row[0]: row[1] for row in result.all()}
        missing = [
            str(fid)
            for fid in (form_definition_id, depends_on_form_definition_id)
            if fid not in versions
        ]
        if missing:
            raise NotFoundError(
                "One or more form definitions were not found",
                details={"missing_form_definition_ids": missing},
            )
        if versions[form_definition_id] != versions[depends_on_form_definition_id]:
            raise ValidationError(
                "A form dependency must link two forms in the same design version",
                details={"field": "depends_on_form_definition_id"},
            )

        existing = await session.execute(
            select(FormDefinitionDependency.id).where(
                FormDefinitionDependency.form_definition_id == form_definition_id,
                FormDefinitionDependency.depends_on_form_definition_id
                == depends_on_form_definition_id,
                FormDefinitionDependency.dependency_type == normalized_type,
            )
        )
        if existing.first() is not None:
            raise ConflictError(
                "This form dependency already exists",
                details={
                    "form_definition_id": str(form_definition_id),
                    "depends_on_form_definition_id": str(depends_on_form_definition_id),
                    "dependency_type": normalized_type,
                },
            )

        normalized_condition = (
            condition_expression.strip() if condition_expression is not None else None
        )
        if normalized_condition == "":
            normalized_condition = None

        dependency = FormDefinitionDependency(
            form_definition_id=form_definition_id,
            depends_on_form_definition_id=depends_on_form_definition_id,
            dependency_type=normalized_type,
            condition_expression=normalized_condition,
        )
        session.add(dependency)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="form_definition_dependency",
            entity_id=dependency.id,
            action="create",
            module=Module.DESIGNER,
            new_value=(
                f"form_definition_id={form_definition_id}; "
                f"depends_on_form_definition_id={depends_on_form_definition_id}; "
                f"dependency_type={normalized_type}"
            ),
            actor_id=actor_id,
        )

        logger.info(
            "Form dependency created: id=%s form=%s depends_on=%s type=%r",
            dependency.id,
            form_definition_id,
            depends_on_form_definition_id,
            normalized_type,
        )
        return dependency

    async def list_dependencies(
        self,
        session: AsyncSession,
        form_definition_id: UUID,
    ) -> list[FormDefinitionDependency]:
        """List a form's outgoing dependency edges ordered by creation time."""
        result = await session.execute(
            select(FormDefinitionDependency)
            .where(FormDefinitionDependency.form_definition_id == form_definition_id)
            .order_by(FormDefinitionDependency.created_at, FormDefinitionDependency.id)
        )
        return list(result.scalars().all())


# Module-level singleton for convenience
form_dependency_service = FormDependencyService()
