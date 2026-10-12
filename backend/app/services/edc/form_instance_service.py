"""Form_Instance_Service — form instance initialization from the published SoA.

Satisfies Requirements:
  - 7.4: When a Subject is created, initialize Form_Instances for the forms
          scheduled at each visit by the bound published Study_Version.

All mutations write an Audit_Event within the caller's transaction (data + audit
commit atomically).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.models.edc.form_data import FormInstance, FormInstanceStatus
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)

logger = logging.getLogger(__name__)


class FormInstanceService:
    """Initializes operational forms from a published schedule of assessment."""

    def __init__(
        self,
        *,
        design_service: DesignConsumptionService | None = None,
    ) -> None:
        self._design = design_service or design_consumption_service

    async def initialize_instances(
        self,
        session: AsyncSession,
        subject: Subject,
        actor_id: UUID | None = None,
    ) -> list[FormInstance]:
        """Create scheduled Form_Instances from the subject's bound design.

        The published schedule of assessment is authoritative for which form is
        collected at which visit.  Procedure-only SoA entries do not create
        Form_Instances.  Repeating forms receive one empty FormInstance for the
        scheduled visit; records are added later by Repeating_Record_Service.

        Args:
            session: Active async database session.
            subject: The Subject whose form instances are being initialized.
            actor_id: Optional UUID of the user performing the action.

        Returns:
            The list of created FormInstance objects.
        """
        schedule = await self._design.get_schedule_of_assessment(
            session, subject.study_version_id
        )
        scheduled_pairs = list(
            dict.fromkeys(
                (entry.visit_definition_id, entry.form_definition_id)
                for entry in schedule.entries
                if entry.visit_definition_id is not None
                and entry.form_definition_id is not None
            )
        )

        if not scheduled_pairs:
            logger.info(
                "No scheduled forms for study_version_id=%s; "
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
        visits_by_definition = {
            visit.visit_definition_id: visit
            for visit in visit_instances
            if visit.visit_definition_id is not None
        }

        instances: list[FormInstance] = []

        for visit_definition_id, form_definition_id in scheduled_pairs:
            visit_instance = visits_by_definition.get(visit_definition_id)
            if visit_instance is None:
                logger.warning(
                    "Skipping scheduled form without a subject visit instance: "
                    "subject_id=%s visit_definition_id=%s form_definition_id=%s",
                    subject.id,
                    visit_definition_id,
                    form_definition_id,
                )
                continue
            form_instance = FormInstance(
                subject_id=subject.id,
                visit_instance_id=visit_instance.id,
                form_definition_id=form_definition_id,
                status=FormInstanceStatus.not_started,
                design_version_id=subject.study_version_id,
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
