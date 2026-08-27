"""Form_Instance_Service — form instance initialization from definitions.

Satisfies Requirements:
  - 7.4: When a Subject is created, initialize Form_Instances for each form
          definition in the bound Study_Version, linked to their respective
          Visit_Instances.

All mutations write an Audit_Event within the caller's transaction (data + audit
commit atomically).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.subject import Subject
from app.models.visit import VisitInstance

logger = logging.getLogger(__name__)


class FormInstanceService:
    """Manages form instance initialization from study version form definitions."""

    async def initialize_instances(
        self,
        session: AsyncSession,
        subject: Subject,
        actor_id: UUID | None = None,
    ) -> list[FormInstance]:
        """Create Form_Instances from the subject's bound Study_Version (Req 7.4).

        For each visit_instance belonging to the subject, a FormInstance is
        created for every form_definition in the bound study version. For
        non-repeating forms this creates one FormInstance per visit per form.
        For repeating forms, one empty FormInstance is created per visit per
        form (records are added later via the Repeating_Record_Service).

        Args:
            session: Active async database session.
            subject: The Subject whose form instances are being initialized.
            actor_id: Optional UUID of the user performing the action.

        Returns:
            The list of created FormInstance objects.
        """
        # Fetch all form definitions for the subject's bound study version
        form_defs_result = await session.execute(
            select(FormDefinition)
            .where(FormDefinition.study_version_id == subject.study_version_id)
            .order_by(FormDefinition.display_order)
        )
        form_definitions = list(form_defs_result.scalars().all())

        if not form_definitions:
            logger.info(
                "No form definitions for study_version_id=%s; "
                "skipping form instance initialization for subject_id=%s",
                subject.study_version_id,
                subject.id,
            )
            return []

        # Fetch all visit instances for this subject
        visit_result = await session.execute(
            select(VisitInstance).where(VisitInstance.subject_id == subject.id)
        )
        visit_instances = list(visit_result.scalars().all())

        instances: list[FormInstance] = []

        # Create a FormInstance for each (visit_instance, form_definition) pair
        for visit_instance in visit_instances:
            for form_def in form_definitions:
                form_instance = FormInstance(
                    subject_id=subject.id,
                    visit_instance_id=visit_instance.id,
                    form_definition_id=form_def.id,
                    status=FormInstanceStatus.not_started,
                )
                session.add(form_instance)
                instances.append(form_instance)

        await session.flush()  # Assign ids

        # Write audit events for each created form instance
        for form_instance in instances:
            await audit_service.record(
                session,
                entity_type="form_instance",
                entity_id=form_instance.id,
                action="create",
                study_id=subject.study_id,
                site_id=subject.site_id,
                subject_id=subject.id,
                actor_id=actor_id,
                new_value=(
                    f"form_definition_id={form_instance.form_definition_id}, "
                    f"visit_instance_id={form_instance.visit_instance_id}, "
                    f"status={form_instance.status}"
                ),
            )

        logger.info(
            "Form instances initialized: subject_id=%s count=%d",
            subject.id,
            len(instances),
        )
        return instances


# Module-level singleton for convenience
form_instance_service = FormInstanceService()
