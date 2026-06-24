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
(Req 11.6) is wired in by a later task.
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
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.site import Site
from app.models.study import StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.schemas.base import PaginatedResponse
from app.schemas.subject import SubjectCreate

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
            subject_number = await self._generate_subject_number(
                session, study_id, site
            )

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
        subject = Subject(
            study_id=study_id,
            site_id=site_id,
            study_version_id=version.id,
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
        # at module load time. Form_Instance initialization is wired in by a
        # later task (11.6).
        from app.services.visit_service import visit_service

        await visit_service.initialize_instances(session, subject, actor_id)

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

        # Visit/form instances are populated by later tasks (10.3, 11.6).
        return {
            "subject_id": subject.id,
            "subject_number": subject.subject_number,
            "status": subject.status,
            "study_version_id": subject.study_version_id,
            "visits": [],
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
            select(Subject).where(
                Subject.id == subject_id, Subject.deleted_at.is_(None)
            )
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
        query = select(Subject).where(
            Subject.study_id == study_id, Subject.deleted_at.is_(None)
        )
        if site_id is not None:
            query = query.where(Subject.site_id == site_id)
        if status is not None:
            query = query.where(Subject.status == status)
        query = query.order_by(Subject.created_at.desc())

        return await paginate(session, query, pagination)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
