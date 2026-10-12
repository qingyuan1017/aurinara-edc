"""Subject_Service — subject lifecycle, state machine, casebook, soft-delete.

Satisfies Requirements:
  - 7.1: Persist subject metadata and bind the Subject to the applicable
          published Study_Version.
  - 7.2: Generate the subject identifier by the configured rule and enforce
          subject number uniqueness within the study.
  - 7.3: Enforce subject status transitions through the subject state machine.
  - 7.5: Return the subject casebook (visit/form structure with clinical status).
  - 7.6: Record an Audit_Event when a subject status changes.
  - 22.2: Soft-delete retains the subject record (deleted_at/by/reason).

Note: Visit_Instance initialization (Req 7.4 / 8.2) is wired into
``create_subject`` via the Visit_Service. Form_Instance initialization
(Req 7.4) is wired in via the Form_Instance_Service.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.models.designer.subject_phase_definition import SubjectPhaseType
from app.models.edc.form_data import FormInstance
from app.models.edc.site import Site
from app.models.edc.study import StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance
from app.schemas.edc.subject import SubjectCreate
from app.schemas.shared.base import PaginatedResponse
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)

logger = logging.getLogger(__name__)

# Legal subject status transitions: current_status -> set of allowed targets.
# Mirrors the subject state machine in the design document (Requirement 7.3).
_LEGAL_TRANSITIONS: dict[SubjectStatus, set[SubjectStatus]] = {
    SubjectStatus.screening: {
        SubjectStatus.screen_failed,
        SubjectStatus.enrolled,
    },
    SubjectStatus.enrolled: {
        SubjectStatus.randomized,
        SubjectStatus.withdrawn,
        SubjectStatus.early_terminated,
    },
    SubjectStatus.randomized: {
        SubjectStatus.on_treatment,
    },
    SubjectStatus.on_treatment: {
        SubjectStatus.completed,
        SubjectStatus.early_terminated,
        SubjectStatus.lost_to_follow_up,
        SubjectStatus.withdrawn,
    },
    # Terminal states
    SubjectStatus.screen_failed: set(),
    SubjectStatus.completed: set(),
    SubjectStatus.early_terminated: set(),
    SubjectStatus.lost_to_follow_up: set(),
    SubjectStatus.withdrawn: set(),
}


class SubjectService:
    """Manages subject creation, status transitions, casebook, and soft-delete."""

    def __init__(
        self,
        *,
        design_service: DesignConsumptionService | None = None,
    ) -> None:
        self._design = design_service or design_consumption_service

    # ------------------------------------------------------------------
    # Create (Req 7.1, 7.2)
    # ------------------------------------------------------------------

    async def create_subject(
        self,
        session: AsyncSession,
        study_id: UUID,
        data: SubjectCreate,
        actor_id: UUID,
    ) -> Subject:
        """Create a new Subject bound to the applicable published Study_Version.

        Args:
            session: Active async database session (caller's transaction).
            study_id: UUID of the parent study.
            data: Validated SubjectCreate schema (site_id + optional subject_number).
            actor_id: UUID of the user performing the action.

        Returns:
            The created Subject instance with status Screening.

        Raises:
            NotFoundError: If the target site does not exist within the study.
            BusinessRuleError: If the study has no published Study_Version (Req 7.1).
            ConflictError: If the subject_number is not unique within the study (Req 7.2).
        """
        site_id = data.site_id

        # Validate the site belongs to the study and exists
        site_result = await session.execute(
            select(Site).where(
                Site.id == site_id,
                Site.study_id == study_id,
                Site.deleted_at.is_(None),
            )
        )
        site = site_result.scalars().first()
        if site is None:
            raise NotFoundError(
                message="Site not found within this study",
                details={"site_id": str(site_id), "study_id": str(study_id)},
            )

        # Find the applicable published Study_Version (latest published) — Req 7.1
        version = await self._get_published_version(session, study_id)
        if version is None:
            raise BusinessRuleError(
                message="Study has no published version; cannot enroll subjects",
                details={"study_id": str(study_id)},
            )

        # Generate the subject identifier by the configured rule (Req 7.2)
        subject_number = data.subject_number
        if subject_number is None:
            subject_number = await self._generate_subject_number(session, study_id, site)

        # Enforce subject_number uniqueness within the study (Req 7.2)
        existing = await session.execute(
            select(Subject).where(
                Subject.study_id == study_id,
                Subject.subject_number == subject_number,
            )
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                message="Subject number already exists within this study",
                details={"subject_number": subject_number, "study_id": str(study_id)},
            )

        # Create the Subject bound to the published version (Req 7.1)
        phase_definitions = await self._design.list_subject_phase_definitions(session, version.id)
        initial_phase = next(
            (
                phase
                for phase in phase_definitions
                if phase.phase_type == SubjectPhaseType.registered.value
            ),
            None,
        )
        subject = Subject(
            study_id=study_id,
            site_id=site_id,
            study_version_id=version.id,
            current_phase_definition_id=(initial_phase.id if initial_phase else None),
            subject_number=subject_number,
            status=SubjectStatus.screening,
            created_by=actor_id,
        )
        session.add(subject)
        await session.flush()  # Assign the id

        # Write Audit_Event (same transaction)
        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="create",
            study_id=study_id,
            site_id=site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            new_value=f"subject_number={subject.subject_number}, status={subject.status}",
        )

        # Initialize Visit_Instances from the bound Study_Version's visit
        # definitions (Req 7.4, 8.2). Imported here to avoid a circular import
        # at module load time.
        from app.services.edc.visit_service import visit_service

        await visit_service.initialize_instances(session, subject, actor_id)

        # Initialize Form_Instances from the bound Study_Version's form
        # definitions (Req 7.4). Must run after visit initialization so that
        # visit_instances exist to link against.
        from app.services.edc.form_instance_service import form_instance_service

        await form_instance_service.initialize_instances(session, subject, actor_id)

        logger.info(
            "Subject created: id=%s study_id=%s site_id=%s subject_number=%s actor=%s",
            subject.id,
            study_id,
            site_id,
            subject.subject_number,
            actor_id,
        )
        return subject

    # ------------------------------------------------------------------
    # Study-data phase and arm state
    # ------------------------------------------------------------------

    async def get_phase_state(self, session: AsyncSession, subject: Subject) -> dict:
        """Return current state and flow-valid next phases for Study Data."""
        phases = await self._design.list_subject_phase_definitions(
            session, subject.study_version_id
        )
        transitions = await self._design.list_subject_phase_transitions(
            session, subject.study_version_id
        )
        arms = await self._design.list_arm_definitions(session, subject.study_version_id)
        current_phase = next(
            (phase for phase in phases if phase.id == subject.current_phase_definition_id),
            None,
        )
        current_arm = next(
            (arm for arm in arms if arm.id == subject.arm_definition_id),
            None,
        )
        next_phases = self._available_next_phases(
            phases, transitions, subject.current_phase_definition_id
        )
        phase_options = [
            {
                "id": phase.id,
                "name": phase.name,
                "phase_type": phase.phase_type,
                "display_order": phase.display_order,
                "visit_definition_ids": list(phase.visit_definition_ids),
            }
            for phase in phases
        ]
        next_phase_ids = {phase.id for phase in next_phases}
        return {
            "current_phase_definition_id": subject.current_phase_definition_id,
            "current_phase_name": current_phase.name if current_phase else None,
            "current_phase_type": current_phase.phase_type if current_phase else None,
            "arm_definition_id": subject.arm_definition_id,
            "arm_name": current_arm.name if current_arm else None,
            "phases": phase_options,
            "next_phases": [option for option in phase_options if option["id"] in next_phase_ids],
            "arms": [
                {
                    "id": arm.id,
                    "name": arm.name,
                    "display_order": arm.display_order,
                    "description": arm.description,
                }
                for arm in arms
            ],
        }

    async def update_phase(
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        phase_definition_id: UUID,
        arm_definition_id: UUID | None,
        actor_id: UUID,
    ) -> Subject:
        """Move a subject to a phase and require an arm for arm phases."""
        phases = await self._design.list_subject_phase_definitions(
            session, subject.study_version_id
        )
        phase = next((item for item in phases if item.id == phase_definition_id), None)
        if phase is None:
            raise ValidationError(
                "Subject phase does not belong to the subject's published design",
                details={"phase_definition_id": str(phase_definition_id)},
            )

        transitions = await self._design.list_subject_phase_transitions(
            session, subject.study_version_id
        )
        available_phases = self._available_next_phases(
            phases, transitions, subject.current_phase_definition_id
        )
        if phase.id not in {item.id for item in available_phases}:
            raise ValidationError(
                "Subject phase is not a valid next step in the configured phase flow",
                details={
                    "current_phase_definition_id": (
                        str(subject.current_phase_definition_id)
                        if subject.current_phase_definition_id
                        else None
                    ),
                    "phase_definition_id": str(phase_definition_id),
                },
            )

        selected_arm = None
        if phase.phase_type == SubjectPhaseType.arm.value:
            if arm_definition_id is None:
                raise ValidationError(
                    "An arm must be selected when entering an arm phase",
                    details={"field": "arm_definition_id"},
                )
            arms = await self._design.list_arm_definitions(session, subject.study_version_id)
            selected_arm = next((item for item in arms if item.id == arm_definition_id), None)
            if selected_arm is None:
                raise ValidationError(
                    "Arm does not belong to the subject's published design",
                    details={"arm_definition_id": str(arm_definition_id)},
                )
        elif arm_definition_id is not None:
            raise ValidationError(
                "An arm can only be selected when entering an arm phase",
                details={"field": "arm_definition_id"},
            )

        old_phase_id = subject.current_phase_definition_id
        old_arm_id = subject.arm_definition_id
        subject.current_phase_definition_id = phase.id
        if selected_arm is not None:
            subject.arm_definition_id = selected_arm.id
        if phase.phase_type == SubjectPhaseType.complete.value:
            subject.status = SubjectStatus.completed
        subject.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="phase_transition",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            field_name="current_phase_definition_id",
            old_value=(str(old_phase_id) if old_phase_id else None),
            new_value=str(phase.id),
            reason=(
                f"phase_type={phase.phase_type}; old_arm_id={old_arm_id}; "
                f"arm_definition_id={subject.arm_definition_id}"
            ),
        )
        return subject

    async def list_visible_visits(
        self, session: AsyncSession, subject: Subject
    ) -> list[VisitInstance]:
        """List Study Data visits allowed by the subject's current phase/arm."""
        allowed_ids: set[UUID] | None = None
        if subject.current_phase_definition_id is not None:
            phases = await self._design.list_subject_phase_definitions(
                session, subject.study_version_id
            )
            phase = next(
                (item for item in phases if item.id == subject.current_phase_definition_id),
                None,
            )
            if phase is None:
                allowed_ids = set()
            elif phase.phase_type == SubjectPhaseType.arm.value:
                arms = await self._design.list_arm_definitions(session, subject.study_version_id)
                arm = next(
                    (item for item in arms if item.id == subject.arm_definition_id),
                    None,
                )
                allowed_ids = set(arm.visit_definition_ids) if arm else set()
            elif phase.phase_type in {
                SubjectPhaseType.registered.value,
                SubjectPhaseType.screen_failure.value,
                SubjectPhaseType.common.value,
            }:
                allowed_ids = set(phase.visit_definition_ids)
            else:
                allowed_ids = set()

        result = await session.execute(
            select(VisitInstance)
            .where(VisitInstance.subject_id == subject.id)
            .order_by(VisitInstance.visit_date, VisitInstance.created_at)
        )
        instances = list(result.scalars().all())
        if allowed_ids is None:
            return instances
        return [visit for visit in instances if visit.visit_definition_id in allowed_ids]

    # ------------------------------------------------------------------
    # Status transition (Req 7.3, 7.6)
    # ------------------------------------------------------------------

    async def transition_status(
        self,
        session: AsyncSession,
        subject: Subject,
        target_status: SubjectStatus,
        actor_id: UUID,
    ) -> Subject:
        """Transition a Subject's status along the allowed state machine.

        Legal transitions (Requirement 7.3):
            Screening    → {Screen Failed, Enrolled}
            Enrolled     → {Randomized, Withdrawn, Early Terminated}
            Randomized   → On Treatment
            On Treatment → {Completed, Early Terminated, Lost to Follow-up, Withdrawn}

        Args:
            session: Active async database session.
            subject: The Subject instance to transition.
            target_status: The desired target status.
            actor_id: UUID of the user performing the action.

        Returns:
            The updated Subject instance.

        Raises:
            BusinessRuleError: If the transition is illegal (Req 7.3).
        """
        current_status = SubjectStatus(subject.status)
        allowed = _LEGAL_TRANSITIONS.get(current_status, set())

        if target_status not in allowed:
            raise BusinessRuleError(
                message=(
                    f"Illegal subject status transition from "
                    f"'{current_status.value}' to '{target_status.value}'"
                ),
                details={
                    "current_status": current_status.value,
                    "target_status": target_status.value,
                    "allowed_transitions": [s.value for s in allowed],
                },
            )

        old_status = current_status.value
        subject.status = target_status
        subject.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 7.6)
        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="status_transition",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            field_name="status",
            old_value=old_status,
            new_value=target_status.value,
        )

        logger.info(
            "Subject status transitioned: id=%s %s→%s actor=%s",
            subject.id,
            old_status,
            target_status.value,
            actor_id,
        )
        return subject

    # ------------------------------------------------------------------
    # Casebook (Req 7.5)
    # ------------------------------------------------------------------

    async def get_casebook(self, session: AsyncSession, subject_id: UUID) -> dict:
        """Return the subject's visit/form structure with clinical status.

        Visit_Instances and Form_Instances are wired in by later tasks; until
        then this returns the subject envelope with an empty visit list. The
        shape matches ``CasebookResponse``.

        Args:
            session: Active async database session.
            subject_id: UUID of the subject.

        Returns:
            A dict describing the subject casebook.

        Raises:
            NotFoundError: If the subject does not exist or is soft-deleted.
        """
        subject = await self.get_subject(session, subject_id)

        # Load the subject's visit instances (scheduled + unscheduled) ordered
        # by visit date then creation, with their source definition eagerly
        # available (VisitInstance.visit_definition is a selectin relationship).
        visit_instances = await self.list_visible_visits(session, subject)
        visit_definition_by_instance = {
            visit.id: visit.visit_definition_id for visit in visit_instances
        }

        schedule = await self._design.get_schedule_of_assessment(session, subject.study_version_id)
        scheduled_pairs = {
            (entry.visit_definition_id, entry.form_definition_id)
            for entry in schedule.entries
            if entry.visit_definition_id is not None and entry.form_definition_id is not None
        }

        # Load the subject's form instances; group them under their owning visit
        # instance. form_definition is eagerly loaded (selectin) for the name.
        form_result = await session.execute(
            select(FormInstance)
            .where(FormInstance.subject_id == subject.id)
            .order_by(FormInstance.created_at)
        )
        forms_by_visit: dict[UUID | None, list[dict]] = {}
        for form in form_result.scalars().all():
            visit_definition_id = visit_definition_by_instance.get(form.visit_instance_id)
            is_scheduled = (
                visit_definition_id,
                form.form_definition_id,
            ) in scheduled_pairs
            if not is_scheduled:
                continue
            definition = form.form_definition
            entry = {
                "form_instance_id": form.id,
                "form_definition_id": form.form_definition_id,
                "name": getattr(definition, "name", None),
                "status": str(form.status),
            }
            forms_by_visit.setdefault(form.visit_instance_id, []).append(entry)

        visits: list[dict] = []
        for visit in visit_instances:
            visits.append(
                {
                    "visit_instance_id": visit.id,
                    "visit_definition_id": visit.visit_definition_id,
                    "name": visit.name,
                    "status": str(visit.status),
                    "forms": forms_by_visit.pop(visit.id, []),
                }
            )

        # Surface any form instances not tied to a visit instance as a trailing
        # visit-less group so they are not silently dropped from the casebook.
        orphan_forms = forms_by_visit.pop(None, [])
        if orphan_forms:
            visits.append(
                {
                    "visit_instance_id": None,
                    "visit_definition_id": None,
                    "name": "Unscheduled forms",
                    "status": "",
                    "forms": orphan_forms,
                }
            )

        phase_state = (
            await self.get_phase_state(session, subject)
            if subject.current_phase_definition_id is not None
            else {
                "current_phase_definition_id": None,
                "current_phase_name": None,
                "current_phase_type": None,
                "arm_definition_id": subject.arm_definition_id,
                "arm_name": None,
            }
        )
        return {
            "subject_id": subject.id,
            "subject_number": subject.subject_number,
            "status": subject.status,
            "study_version_id": subject.study_version_id,
            "current_phase_definition_id": phase_state["current_phase_definition_id"],
            "current_phase_name": phase_state["current_phase_name"],
            "current_phase_type": phase_state["current_phase_type"],
            "arm_definition_id": phase_state["arm_definition_id"],
            "arm_name": phase_state["arm_name"],
            "visits": visits,
        }

    # ------------------------------------------------------------------
    # Soft-delete (Req 22.2)
    # ------------------------------------------------------------------

    async def soft_delete(
        self,
        session: AsyncSession,
        subject: Subject,
        reason: str,
        actor_id: UUID,
    ) -> Subject:
        """Soft-delete a Subject, retaining the record (Requirement 22.2).

        Args:
            session: Active async database session.
            subject: The Subject instance to soft-delete.
            reason: The reason for deletion (retained on the record).
            actor_id: UUID of the user performing the action.

        Returns:
            The updated Subject instance.

        Raises:
            ConflictError: If the subject is already soft-deleted.
        """
        if subject.deleted_at is not None:
            raise ConflictError(
                message="Subject is already deleted",
                details={"subject_id": str(subject.id)},
            )

        subject.deleted_at = datetime.now(UTC)
        subject.deleted_by = actor_id
        subject.deletion_reason = reason
        await session.flush()

        # Write Audit_Event (same transaction)
        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="delete",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            reason=reason,
        )

        logger.info(
            "Subject soft-deleted: id=%s actor=%s reason=%s",
            subject.id,
            actor_id,
            reason,
        )
        return subject

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_subject(self, session: AsyncSession, subject_id: UUID) -> Subject:
        """Retrieve a non-deleted Subject by its primary key.

        Args:
            session: Active async database session.
            subject_id: The UUID of the subject.

        Returns:
            The Subject instance.

        Raises:
            NotFoundError: If no subject exists with the given ID or it is soft-deleted.
        """
        result = await session.execute(
            select(Subject).where(Subject.id == subject_id, Subject.deleted_at.is_(None))
        )
        subject = result.scalars().first()
        if subject is None:
            raise NotFoundError(
                message="Subject not found",
                details={"subject_id": str(subject_id)},
            )
        return subject

    # ------------------------------------------------------------------
    # List (with pagination)
    # ------------------------------------------------------------------

    async def list_subjects(
        self,
        session: AsyncSession,
        study_id: UUID,
        pagination: PaginationParams,
        site_id: UUID | None = None,
        status: SubjectStatus | None = None,
    ) -> PaginatedResponse:
        """List non-deleted subjects for a study with optional filters.

        Args:
            session: Active async database session.
            study_id: UUID of the parent study.
            pagination: Page/page_size pagination parameters.
            site_id: Optional site filter.
            status: Optional status filter.

        Returns:
            PaginatedResponse containing Subject instances.
        """
        query = select(Subject).where(Subject.study_id == study_id, Subject.deleted_at.is_(None))
        if site_id is not None:
            query = query.where(Subject.site_id == site_id)
        if status is not None:
            query = query.where(Subject.status == status)
        query = query.order_by(Subject.created_at.desc())

        return await paginate(session, query, pagination)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _available_next_phases(phases, transitions, current_phase_id: UUID | None):
        """Resolve ordered phase choices from the published transition graph."""
        if current_phase_id is not None:
            target_ids = {
                transition.to_phase_id
                for transition in transitions
                if transition.from_phase_id == current_phase_id
            }
        else:
            # Legacy subjects without a phase can enter only a graph root.
            target_ids = {phase.id for phase in phases} - {
                transition.to_phase_id for transition in transitions
            }
        return [phase for phase in phases if phase.id in target_ids]

    async def _get_published_version(
        self, session: AsyncSession, study_id: UUID
    ) -> StudyVersion | None:
        """Return the latest published Study_Version for a study, or None."""
        result = await session.execute(
            select(StudyVersion)
            .where(
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.published,
            )
            .order_by(StudyVersion.published_at.desc())
        )
        return result.scalars().first()

    async def _generate_subject_number(
        self, session: AsyncSession, study_id: UUID, site: Site
    ) -> str:
        """Generate a subject identifier by the configured rule.

        Default rule: ``{site_number}-{sequence}`` where the sequence is the
        next zero-padded number scoped to the site within the study.
        """
        count_result = await session.execute(
            select(func.count())
            .select_from(Subject)
            .where(Subject.study_id == study_id, Subject.site_id == site.id)
        )
        sequence = (count_result.scalar_one() or 0) + 1
        return f"{site.site_number}-{sequence:04d}"


# Module-level singleton for convenience
subject_service = SubjectService()
