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

import inspect
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.models.ctms.enrollment import OperationalMilestone
from app.models.ctms.financial import FinancialEvent
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.study_operation import StudyOperationRecord
from app.models.designer.subject_phase_definition import SubjectPhaseType
from app.models.edc.form_data import FieldValue, FormInstance
from app.models.edc.form_record import FormRecord
from app.models.edc.query import Query, QueryStatus
from app.models.edc.review import ReviewStatus
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import StudyVersion, StudyVersionStatus
from app.models.edc.subject import Subject, SubjectStatus
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.models.pv.safety_case import SafetyCase
from app.models.shared.audit import AuditEvent
from app.models.shared.file_attachment import FileAttachment
from app.schemas.edc.subject import SubjectCreate
from app.schemas.shared.base import PaginatedResponse
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)
from app.services.edc.lock_service import lock_service

logger = logging.getLogger(__name__)

# Legal subject status transitions: current_status -> set of allowed targets.
# Mirrors the subject state machine in the design document (Requirement 7.3).
_LEGAL_TRANSITIONS: dict[SubjectStatus, set[SubjectStatus]] = {
    SubjectStatus.screening: {
        SubjectStatus.screen_failed,
        SubjectStatus.enrolled,
        SubjectStatus.inactive,
        SubjectStatus.discontinued,
    },
    SubjectStatus.enrolled: {
        SubjectStatus.randomized,
        SubjectStatus.withdrawn,
        SubjectStatus.early_terminated,
        SubjectStatus.inactive,
        SubjectStatus.discontinued,
    },
    SubjectStatus.randomized: {
        SubjectStatus.on_treatment,
        SubjectStatus.inactive,
        SubjectStatus.discontinued,
    },
    SubjectStatus.on_treatment: {
        SubjectStatus.completed,
        SubjectStatus.early_terminated,
        SubjectStatus.lost_to_follow_up,
        SubjectStatus.withdrawn,
        SubjectStatus.inactive,
        SubjectStatus.discontinued,
    },
    # Terminal states
    SubjectStatus.screen_failed: set(),
    SubjectStatus.completed: set(),
    SubjectStatus.early_terminated: set(),
    SubjectStatus.lost_to_follow_up: set(),
    SubjectStatus.withdrawn: set(),
    SubjectStatus.inactive: {SubjectStatus.discontinued},
    SubjectStatus.discontinued: set(),
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
        if site.status != SiteStatus.active:
            raise BusinessRuleError(
                message="Subjects can only be enrolled at an active site",
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

        # Activate only the initial phase's visits. Designs without phase
        # configuration retain whole-version initialization for compatibility.
        # Imported here to avoid a circular import at module load time.
        from app.services.edc.visit_service import visit_service

        initial_visit_ids: set[UUID] | None = None
        if phase_definitions:
            initial_visit_ids = (
                set(initial_phase.visit_definition_ids) if initial_phase is not None else set()
            )
        await visit_service.initialize_instances(
            session,
            subject,
            actor_id,
            definition_ids=initial_visit_ids,
        )

        # Initialize Form_Instances from the bound Study_Version's form
        # definitions (Req 7.4). Must run after visit initialization so that
        # visit_instances exist to link against.
        from app.services.edc.form_instance_service import form_instance_service

        await form_instance_service.initialize_instances(
            session,
            subject,
            actor_id,
            definition_ids=initial_visit_ids,
        )

        logger.info(
            "Subject created: id=%s study_id=%s site_id=%s subject_number=%s actor=%s",
            subject.id,
            study_id,
            site_id,
            subject.subject_number,
            actor_id,
        )
        return subject

    async def enrollment_readiness(
        self,
        session: AsyncSession,
        study_id: UUID,
        *,
        authorized_site_ids: set[UUID] | None = None,
    ) -> dict:
        """Return server-derived prerequisites for subject enrollment."""
        version = await self._get_published_version(session, study_id)
        site_query = select(func.count(Site.id)).where(
            Site.study_id == study_id,
            Site.status == SiteStatus.active,
            Site.deleted_at.is_(None),
        )
        if authorized_site_ids is not None:
            site_query = site_query.where(Site.id.in_(authorized_site_ids))
        site_count = int((await session.execute(site_query)).scalar_one())

        blockers: list[dict[str, str]] = []
        if version is None:
            blockers.append(
                {
                    "code": "NO_PUBLISHED_DESIGN",
                    "message": "Publish a valid study design before enrolling subjects.",
                }
            )
        if site_count == 0:
            blockers.append(
                {
                    "code": "NO_AUTHORIZED_ACTIVE_SITE",
                    "message": "Configure or assign at least one active site for this study.",
                }
            )

        return {
            "study_id": study_id,
            "ready": not blockers,
            "published_version_id": version.id if version else None,
            "published_version_number": version.version_number if version else None,
            "authorized_active_site_count": site_count,
            "blockers": blockers,
        }

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
        previous_phase_id = await self._previous_phase_id(session, subject)
        return {
            "current_phase_definition_id": subject.current_phase_definition_id,
            "current_phase_name": current_phase.name if current_phase else None,
            "current_phase_type": current_phase.phase_type if current_phase else None,
            "arm_definition_id": subject.arm_definition_id,
            "arm_name": current_arm.name if current_arm else None,
            "phases": phase_options,
            "next_phases": [option for option in phase_options if option["id"] in next_phase_ids],
            "previous_phase": next(
                (option for option in phase_options if option["id"] == previous_phase_id),
                None,
            ),
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

        if phase.phase_type in {
            SubjectPhaseType.registered.value,
            SubjectPhaseType.screen_failure.value,
            SubjectPhaseType.common.value,
            SubjectPhaseType.complete.value,
        }:
            phase_visit_ids = set(phase.visit_definition_ids)
            if subject.arm_definition_id is not None:
                schedule = await self._design.get_schedule_of_assessment(
                    session,
                    subject.study_version_id,
                    subject.arm_definition_id,
                )
                arm_visit_ids = {
                    entry.visit_definition_id
                    for entry in schedule.entries
                    if entry.visit_definition_id is not None
                }
                phase_visit_ids.intersection_update(arm_visit_ids)
        else:
            phase_visit_ids = set()

        # Arm phases assign the schedule only. A later visit-bearing phase
        # activates the intersection of its visits and the selected arm SoA.
        if phase_visit_ids:
            from app.services.edc.form_instance_service import form_instance_service
            from app.services.edc.visit_service import visit_service

            await visit_service.initialize_instances(
                session,
                subject,
                actor_id,
                definition_ids=phase_visit_ids,
                skip_existing=True,
            )
            await form_instance_service.initialize_instances(
                session,
                subject,
                actor_id,
                skip_existing=True,
                arm_definition_id=subject.arm_definition_id,
                definition_ids=phase_visit_ids,
            )

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

    async def reverse_phase(
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        reason: str,
        actor_id: UUID,
    ) -> Subject:
        """Move to the immediately preceding audited phase without deleting data."""
        reason = self._normalize_lifecycle_reason(reason)
        locked_result = await session.execute(
            select(Subject).where(Subject.id == subject.id).with_for_update()
        )
        locked_subject = await self._first_scalar(locked_result)
        if isinstance(locked_subject, Subject):
            subject = locked_subject
        if await lock_service.is_modification_blocked(
            session,
            subject,
            object_type="subject",
            object_id=subject.id,
        ):
            raise BusinessRuleError(
                message="A frozen or locked subject phase cannot be reversed",
                details={"reason": "SUBJECT_PHASE_REVERSAL_LOCKED"},
            )
        previous_phase_id = await self._previous_phase_id(session, subject)
        if previous_phase_id is None:
            raise BusinessRuleError(
                message="The subject has no previous phase to restore",
                details={"reason": "SUBJECT_PHASE_HISTORY_EMPTY"},
            )

        phases = await self._design.list_subject_phase_definitions(
            session, subject.study_version_id
        )
        phase_by_id = {phase.id: phase for phase in phases}
        previous_phase = phase_by_id.get(previous_phase_id)
        if previous_phase is None:
            raise BusinessRuleError(
                message="The previous phase is no longer available in the bound design",
                details={"reason": "SUBJECT_PREVIOUS_PHASE_UNAVAILABLE"},
            )

        old_phase_id = subject.current_phase_definition_id
        old_status = SubjectStatus(subject.status)
        subject.current_phase_definition_id = previous_phase_id
        entered_path = await self._entered_phase_path(session, subject)
        previous_index = (
            entered_path.index(previous_phase_id) if previous_phase_id in entered_path else -1
        )
        retained_path = entered_path[: previous_index + 1]
        if not any(
            phase_by_id.get(phase_id)
            and phase_by_id[phase_id].phase_type == SubjectPhaseType.arm.value
            for phase_id in retained_path
        ):
            subject.arm_definition_id = None
        if old_status is SubjectStatus.completed:
            subject.status = SubjectStatus.on_treatment
        subject.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="phase_reversal",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            field_name="current_phase_definition_id",
            old_value=str(old_phase_id) if old_phase_id else None,
            new_value=str(previous_phase_id),
            reason=reason,
        )
        logger.info(
            "Subject phase reversed: id=%s actor=%s",
            subject.id,
            actor_id,
        )
        return subject

    async def list_visible_visits(
        self, session: AsyncSession, subject: Subject
    ) -> list[VisitInstance]:
        """List Study Data visits accumulated through the subject's phase path."""
        allowed_ids = await self.visible_visit_definition_ids(session, subject)

        result = await session.execute(
            select(VisitInstance)
            .where(VisitInstance.subject_id == subject.id)
            .order_by(VisitInstance.visit_date, VisitInstance.created_at)
        )
        instances = list(result.scalars().all())
        if allowed_ids is None:
            return instances
        return [
            visit
            for visit in instances
            if visit.status == VisitInstanceStatus.unscheduled
            or visit.visit_definition_id in allowed_ids
        ]

    async def visible_visit_definition_ids(
        self, session: AsyncSession, subject: Subject
    ) -> set[UUID] | None:
        """Return visit definitions accumulated along the subject's phase path.

        ``None`` means that the published design has no phase configuration, so
        all visits remain visible for backward compatibility. Once any phases
        are configured, the immutable phase lifecycle audit trail determines
        the currently active path, including reversals. This preserves visits
        from retained prior phases without exposing reversed, sibling, or
        future branches.
        """
        phases = await self._design.list_subject_phase_definitions(
            session, subject.study_version_id
        )
        if not phases:
            return None
        if subject.current_phase_definition_id is None:
            return set()

        entered_phase_path = await self._entered_phase_path(session, subject)
        phase_by_id = {phase.id: phase for phase in phases}
        entered_phases = [
            phase_by_id[phase_id] for phase_id in entered_phase_path if phase_id in phase_by_id
        ]
        if not entered_phases:
            return set()

        arm_visit_ids: set[UUID] | None = None
        if subject.arm_definition_id is not None and any(
            phase.phase_type == SubjectPhaseType.arm.value for phase in entered_phases
        ):
            arm_schedule = await self._design.get_schedule_of_assessment(
                session,
                subject.study_version_id,
                subject.arm_definition_id,
            )
            arm_visit_ids = {
                entry.visit_definition_id
                for entry in arm_schedule.entries
                if entry.visit_definition_id is not None
            }

        visible_ids: set[UUID] = set()
        arm_is_active = False
        for phase in entered_phases:
            if phase.phase_type == SubjectPhaseType.arm.value:
                arm_is_active = True
                continue
            if phase.phase_type not in {
                SubjectPhaseType.registered.value,
                SubjectPhaseType.screen_failure.value,
                SubjectPhaseType.common.value,
                SubjectPhaseType.complete.value,
            }:
                continue
            phase_visit_ids = set(phase.visit_definition_ids)
            if arm_is_active and arm_visit_ids is not None:
                phase_visit_ids.intersection_update(arm_visit_ids)
            visible_ids.update(phase_visit_ids)
        return visible_ids

    async def _entered_phase_path(self, session: AsyncSession, subject: Subject) -> list[UUID]:
        """Replay transitions and reversals into the subject's active phase path."""
        current_phase_id = subject.current_phase_definition_id
        if current_phase_id is None:
            return []

        result = await session.execute(
            select(AuditEvent.action, AuditEvent.old_value, AuditEvent.new_value)
            .where(
                AuditEvent.entity_type == "subject",
                AuditEvent.entity_id == subject.id,
                AuditEvent.action.in_(("phase_transition", "phase_reversal")),
                AuditEvent.field_name == "current_phase_definition_id",
            )
            .order_by(AuditEvent.timestamp, AuditEvent.id)
        )
        entered_path: list[UUID] = []
        for action, old_value, new_value in result.all():
            parsed_ids: list[UUID | None] = []
            for value in (old_value, new_value):
                if value is None:
                    parsed_ids.append(None)
                    continue
                try:
                    parsed_ids.append(UUID(value))
                except (TypeError, ValueError):
                    logger.warning(
                        "Ignoring malformed subject phase audit value: subject_id=%s",
                        subject.id,
                    )
                    parsed_ids.append(None)
            old_phase_id, new_phase_id = parsed_ids

            if action == "phase_reversal":
                if new_phase_id in entered_path:
                    entered_path = entered_path[: entered_path.index(new_phase_id) + 1]
                elif new_phase_id is not None:
                    entered_path.append(new_phase_id)
                continue

            if old_phase_id is not None:
                if old_phase_id in entered_path:
                    entered_path = entered_path[: entered_path.index(old_phase_id) + 1]
                else:
                    entered_path.append(old_phase_id)
            if new_phase_id is not None:
                if new_phase_id in entered_path:
                    entered_path = entered_path[: entered_path.index(new_phase_id) + 1]
                else:
                    entered_path.append(new_phase_id)

        if current_phase_id in entered_path:
            entered_path = entered_path[: entered_path.index(current_phase_id) + 1]
        else:
            entered_path.append(current_phase_id)
        return entered_path

    # ------------------------------------------------------------------
    # Status transition (Req 7.3, 7.6)
    # ------------------------------------------------------------------

    async def transition_status(
        self,
        session: AsyncSession,
        subject: Subject,
        target_status: SubjectStatus,
        actor_id: UUID,
        reason: str | None = None,
    ) -> Subject:
        """Transition a Subject's status along the allowed state machine.

        Legal transitions (Requirement 7.3):
            Active states → Inactive or Discontinued
            Inactive      → Discontinued
            Other transitions follow the configured clinical lifecycle.

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
        locked_result = await session.execute(
            select(Subject).where(Subject.id == subject.id).with_for_update()
        )
        locked_subject = await self._first_scalar(locked_result)
        if isinstance(locked_subject, Subject):
            subject = locked_subject
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
        if target_status in {SubjectStatus.inactive, SubjectStatus.discontinued}:
            reason = self._normalize_lifecycle_reason(reason or "")
            if await lock_service.is_modification_blocked(
                session,
                subject,
                object_type="subject",
                object_id=subject.id,
            ):
                raise BusinessRuleError(
                    message="A frozen or locked subject status cannot be changed",
                    details={"reason": "SUBJECT_LIFECYCLE_CHANGE_LOCKED"},
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
            reason=reason,
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

        schedules = [
            await self._design.get_schedule_of_assessment(
                session,
                subject.study_version_id,
                None,
            )
        ]
        if subject.arm_definition_id is not None:
            schedules.append(
                await self._design.get_schedule_of_assessment(
                    session,
                    subject.study_version_id,
                    subject.arm_definition_id,
                )
            )
        scheduled_pairs = {
            (entry.visit_definition_id, entry.form_definition_id)
            for schedule in schedules
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
        forms = list(form_result.scalars().all())
        from app.models.edc.form_record import FormRecord
        from app.services.edc.operational_service import edc_operational_service

        supports_operational_state = all(
            hasattr(form, "data_entry_status") and hasattr(form, "data_revision") for form in forms
        )
        if supports_operational_state:
            operational_statuses = await edc_operational_service.form_statuses(session, forms)
            record_counts = dict(
                (
                    await session.execute(
                        select(FormRecord.form_instance_id, func.count(FormRecord.id))
                        .where(
                            FormRecord.form_instance_id.in_(
                                [form.id for form in forms] or [UUID(int=0)]
                            ),
                            FormRecord.deleted_at.is_(None),
                        )
                        .group_by(FormRecord.form_instance_id)
                    )
                ).all()
            )
        else:
            operational_statuses = {}
            record_counts = {}
        forms_by_visit: dict[UUID | None, list[dict]] = {}
        added_in_error_visit_ids = {
            visit.id
            for visit in visit_instances
            if visit.status == VisitInstanceStatus.added_in_error
        }
        for form in forms:
            if form.visit_instance_id in added_in_error_visit_ids:
                continue
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
                "status": getattr(form, "data_entry_status", form.status),
                "operational_status": operational_statuses.get(form.id),
                "repeating_record_count": int(record_counts.get(form.id, 0)),
                "source_form_url": f"/subjects/{subject.id}/forms/{form.id}",
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
        *,
        subject_number_confirmation: str,
    ) -> Subject:
        """Remove a Screening subject that was entered in error.

        The row and all related clinical history are retained. A subject that
        has progressed, contains clinical data, is locked, or has downstream
        EDC/PV/CTMS records must use a lifecycle status instead.

        Args:
            session: Active async database session.
            subject: The Subject instance to soft-delete.
            reason: The reason for deletion (retained on the record).
            actor_id: UUID of the user performing the action.

        Returns:
            The updated Subject instance.

        Raises:
            ConflictError: If the subject is already soft-deleted.
            BusinessRuleError: If removal is not allowed for the record.
            ValidationError: If the reason or typed confirmation is invalid.
        """
        reason = self._normalize_lifecycle_reason(reason)
        if subject_number_confirmation.strip() != subject.subject_number:
            raise ValidationError(
                message="Subject number confirmation does not match",
                details={"reason": "SUBJECT_NUMBER_CONFIRMATION_MISMATCH"},
            )

        if subject.deleted_at is not None:
            raise ConflictError(
                message="Subject is already deleted",
                details={"subject_id": str(subject.id)},
            )

        locked_result = await session.execute(
            select(Subject).where(Subject.id == subject.id).with_for_update()
        )
        locked_subject = await self._first_scalar(locked_result)
        if isinstance(locked_subject, Subject):
            subject = locked_subject

        if subject.deleted_at is not None:
            raise ConflictError(
                message="Subject is already deleted",
                details={"subject_id": str(subject.id)},
            )

        if SubjectStatus(subject.status) is not SubjectStatus.screening:
            raise BusinessRuleError(
                message=(
                    "Only a Screening subject entered in error may be removed; "
                    "use the appropriate subject lifecycle status instead"
                ),
                details={
                    "reason": "SUBJECT_REMOVAL_STATUS_NOT_ELIGIBLE",
                    "subject_status": SubjectStatus(subject.status).value,
                },
            )

        if await lock_service.is_modification_blocked(
            session,
            subject,
            object_type="subject",
            object_id=subject.id,
        ):
            raise BusinessRuleError(
                message="A frozen or locked subject cannot be removed",
                details={"reason": "SUBJECT_REMOVAL_LOCKED"},
            )

        blockers = await self._subject_removal_blockers(session, subject)
        if blockers:
            raise BusinessRuleError(
                message=(
                    "Subject cannot be removed because clinical, safety, or operational "
                    "records already exist; use the appropriate lifecycle status instead"
                ),
                details={"reason": "SUBJECT_REMOVAL_HAS_RECORDS", "blockers": blockers},
            )

        now = datetime.now(UTC)
        subject.deleted_at = now
        subject.deleted_by = actor_id
        subject.deletion_reason = reason
        subject.updated_at = now
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
            "Subject soft-deleted: id=%s actor=%s",
            subject.id,
            actor_id,
        )
        return subject

    async def restore(
        self,
        session: AsyncSession,
        subject: Subject,
        reason: str,
        actor_id: UUID,
    ) -> Subject:
        """Restore a retained subject after an erroneous soft deletion."""
        reason = self._normalize_lifecycle_reason(reason)
        locked_result = await session.execute(
            select(Subject).where(Subject.id == subject.id).with_for_update()
        )
        locked_subject = await self._first_scalar(locked_result)
        if isinstance(locked_subject, Subject):
            subject = locked_subject
        if subject.deleted_at is None:
            raise ConflictError(
                message="Subject is not deleted",
                details={"subject_id": str(subject.id)},
            )

        deleted_at = subject.deleted_at
        deleted_by = subject.deleted_by
        deletion_reason = subject.deletion_reason
        subject.deleted_at = None
        subject.deleted_by = None
        subject.deletion_reason = None
        subject.updated_at = datetime.now(UTC)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="restore",
            study_id=subject.study_id,
            site_id=subject.site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            old_value=(
                f"deleted_at={deleted_at.isoformat()}, deleted_by={deleted_by}, "
                f"deletion_reason={deletion_reason}"
            ),
            new_value="deleted_at=None, deleted_by=None, deletion_reason=None",
            reason=reason,
        )
        logger.info("Subject restored: id=%s actor=%s", subject.id, actor_id)
        return subject

    async def switch_site(
        self,
        session: AsyncSession,
        subject: Subject,
        *,
        site_id: UUID,
        reason: str,
        actor_id: UUID,
    ) -> Subject:
        """Move an entered-in-error Screening subject to another active Site."""
        reason = self._normalize_lifecycle_reason(reason)
        locked_result = await session.execute(
            select(Subject).where(Subject.id == subject.id).with_for_update()
        )
        locked_subject = await self._first_scalar(locked_result)
        if isinstance(locked_subject, Subject):
            subject = locked_subject
        if subject.site_id == site_id:
            raise ConflictError(
                message="Subject is already assigned to this site",
                details={"site_id": str(site_id)},
            )
        if SubjectStatus(subject.status) is not SubjectStatus.screening:
            raise BusinessRuleError(
                message="Only a Screening subject without clinical activity may switch sites",
                details={"reason": "SUBJECT_SITE_TRANSFER_STATUS_NOT_ELIGIBLE"},
            )
        target_site = (
            (
                await session.execute(
                    select(Site).where(
                        Site.id == site_id,
                        Site.study_id == subject.study_id,
                        Site.status == SiteStatus.active,
                        Site.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if target_site is None:
            raise NotFoundError(
                message="Active destination site not found within this study",
                details={"site_id": str(site_id), "study_id": str(subject.study_id)},
            )
        if await lock_service.is_modification_blocked(
            session,
            subject,
            object_type="subject",
            object_id=subject.id,
        ):
            raise BusinessRuleError(
                message="A frozen or locked subject cannot switch sites",
                details={"reason": "SUBJECT_SITE_TRANSFER_LOCKED"},
            )
        blockers = await self._subject_removal_blockers(session, subject)
        if blockers:
            raise BusinessRuleError(
                message=(
                    "Subject cannot switch sites after clinical, safety, or operational "
                    "records exist"
                ),
                details={"reason": "SUBJECT_SITE_TRANSFER_HAS_RECORDS", "blockers": blockers},
            )

        old_site_id = subject.site_id
        subject.site_id = site_id
        subject.updated_at = datetime.now(UTC)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="subject",
            entity_id=subject.id,
            action="site_transfer",
            study_id=subject.study_id,
            site_id=site_id,
            subject_id=subject.id,
            actor_id=actor_id,
            field_name="site_id",
            old_value=str(old_site_id),
            new_value=str(site_id),
            reason=reason,
        )
        logger.info("Subject site switched: id=%s actor=%s", subject.id, actor_id)
        return subject

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_subject(
        self,
        session: AsyncSession,
        subject_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> Subject:
        """Retrieve a non-deleted Subject by its primary key.

        Args:
            session: Active async database session.
            subject_id: The UUID of the subject.

        Returns:
            The Subject instance.

        Raises:
            NotFoundError: If no subject exists with the given ID or it is soft-deleted.
        """
        query = select(Subject).where(Subject.id == subject_id)
        if not include_deleted:
            query = query.where(Subject.deleted_at.is_(None))
        result = await session.execute(query)
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
        search: str | None = None,
        phase_id: UUID | None = None,
        authorized_site_ids: set[UUID] | None = None,
        quality_state: str | None = None,
        sort: str = "created_desc",
        include_deleted: bool = False,
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
        query = select(Subject).where(Subject.study_id == study_id)
        if not include_deleted:
            query = query.where(Subject.deleted_at.is_(None))
        if site_id is not None:
            query = query.where(Subject.site_id == site_id)
        if authorized_site_ids is not None:
            query = query.where(Subject.site_id.in_(authorized_site_ids))
        if status is not None:
            query = query.where(Subject.status == status)
        if phase_id is not None:
            query = query.where(Subject.current_phase_definition_id == phase_id)
        if search and search.strip():
            query = query.where(Subject.subject_number.ilike(f"%{search.strip()}%"))
        active_query = exists(
            select(Query.id).where(
                Query.subject_id == Subject.id,
                Query.status.in_(
                    (
                        QueryStatus.open.value,
                        QueryStatus.answered.value,
                        QueryStatus.reopened.value,
                    )
                ),
            )
        )
        incomplete_form = exists(
            select(FormInstance.id).where(
                FormInstance.subject_id == Subject.id,
                FormInstance.data_entry_status != "Submitted",
            )
        )
        stale_review = exists(
            select(ReviewStatus.id)
            .join(
                FormInstance,
                FormInstance.id == ReviewStatus.form_instance_id,
            )
            .where(
                FormInstance.subject_id == Subject.id,
                ReviewStatus.is_reviewed.is_(True),
                ReviewStatus.reviewed_revision != FormInstance.data_revision,
            )
        )
        if quality_state == "queried":
            query = query.where(active_query)
        elif quality_state == "incomplete":
            query = query.where(incomplete_form)
        elif quality_state == "stale_review":
            query = query.where(stale_review)
        elif quality_state == "clean":
            query = query.where(~active_query, ~incomplete_form, ~stale_review)
        order_by = {
            "created_asc": Subject.created_at.asc(),
            "subject_asc": Subject.subject_number.asc(),
            "subject_desc": Subject.subject_number.desc(),
        }.get(sort, Subject.created_at.desc())
        query = query.order_by(order_by)

        return await paginate(session, query, pagination)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_lifecycle_reason(reason: str) -> str:
        normalized = reason.strip()
        if not normalized:
            raise ValidationError(
                message="A reason is required",
                details={"reason": "SUBJECT_LIFECYCLE_REASON_REQUIRED"},
            )
        if len(normalized) > 4000:
            raise ValidationError(
                message="Reason must be at most 4000 characters",
                details={"reason": "SUBJECT_LIFECYCLE_REASON_TOO_LONG"},
            )
        return normalized

    @staticmethod
    async def _previous_phase_id(
        session: AsyncSession,
        subject: Subject,
    ) -> UUID | None:
        current_phase_id = subject.current_phase_definition_id
        if current_phase_id is None:
            return None
        result = await session.execute(
            select(AuditEvent.old_value)
            .where(
                AuditEvent.entity_type == "subject",
                AuditEvent.entity_id == subject.id,
                AuditEvent.action == "phase_transition",
                AuditEvent.field_name == "current_phase_definition_id",
                AuditEvent.new_value == str(current_phase_id),
            )
            .order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        value = result.scalar_one_or_none()
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, str) or not value:
            return None
        try:
            return UUID(value)
        except ValueError:
            logger.warning(
                "Ignoring malformed previous subject phase audit value: subject_id=%s",
                subject.id,
            )
            return None

    @staticmethod
    async def _statement_has_row(session: AsyncSession, statement) -> bool:
        result = await session.execute(statement.limit(1))
        row = result.first()
        if inspect.isawaitable(row):
            row = await row
        if row is None:
            return False
        row_type = type(row)
        return isinstance(row, tuple) or row_type.__module__.startswith("sqlalchemy.")

    @staticmethod
    async def _first_scalar(result):
        scalars = result.scalars()
        if inspect.isawaitable(scalars):
            scalars = await scalars
        first = scalars.first()
        if inspect.isawaitable(first):
            first = await first
        return first

    async def _subject_removal_blockers(
        self,
        session: AsyncSession,
        subject: Subject,
    ) -> list[str]:
        """Return stable blocker codes without exposing regulated payloads."""
        blockers: list[str] = []
        if int(subject.data_revision or 0) > 0:
            blockers.append("CLINICAL_DATA")

        checks = (
            (
                "CLINICAL_DATA",
                select(FieldValue.id)
                .join(FormInstance, FormInstance.id == FieldValue.form_instance_id)
                .where(FormInstance.subject_id == subject.id),
            ),
            (
                "REPEATING_RECORDS",
                select(FormRecord.id)
                .join(FormInstance, FormInstance.id == FormRecord.form_instance_id)
                .where(FormInstance.subject_id == subject.id),
            ),
            ("QUERIES", select(Query.id).where(Query.subject_id == subject.id)),
            (
                "ATTACHMENTS",
                select(FileAttachment.id).where(
                    FileAttachment.subject_id == subject.id,
                    FileAttachment.deleted_at.is_(None),
                ),
            ),
            (
                "SAFETY_CASES",
                select(SafetyCase.id).where(
                    SafetyCase.subject_reference == subject.id,
                    SafetyCase.deleted_at.is_(None),
                ),
            ),
            (
                "CTMS_MILESTONES",
                select(OperationalMilestone.id).where(
                    OperationalMilestone.subject_id == subject.id,
                    OperationalMilestone.deleted_at.is_(None),
                ),
            ),
            (
                "CTMS_FINANCIAL_EVENTS",
                select(FinancialEvent.id).where(FinancialEvent.subject_id == subject.id),
            ),
            (
                "CTMS_OPERATIONAL_RECORDS",
                select(StudyOperationRecord.id).where(
                    StudyOperationRecord.subject_id == subject.id,
                    StudyOperationRecord.deleted_at.is_(None),
                ),
            ),
            (
                "CTMS_PROJECTIONS",
                select(CTMSOperationalProjection.id).where(
                    CTMSOperationalProjection.deleted_at.is_(None),
                    or_(
                        CTMSOperationalProjection.subject_id == subject.id,
                        CTMSOperationalProjection.source_record_id == subject.id,
                    ),
                ),
            ),
        )
        for code, statement in checks:
            if code in blockers:
                continue
            if await self._statement_has_row(session, statement):
                blockers.append(code)
        return blockers

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
