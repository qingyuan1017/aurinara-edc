"""Study_Service — study lifecycle management.

Satisfies Requirements:
  - 4.1: Persist study metadata (code, protocol number, title, sponsor, phase,
          therapeutic area, indication, status).
  - 4.2: Enforce globally unique study code.
  - 4.3: Enforce study status transitions (Draft → UAT → Active → Enrollment Closed
          → Locked → Archived).
  - 4.5: Write Audit_Event on study metadata changes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams
from app.api.pagination import paginate
from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.schemas.base import PaginatedResponse
from app.schemas.study import StudyCreate

logger = logging.getLogger(__name__)

# Legal status transitions: current_status -> set of allowed target statuses
_LEGAL_TRANSITIONS: dict[StudyStatus, set[StudyStatus]] = {
    StudyStatus.draft: {StudyStatus.uat},
    StudyStatus.uat: {StudyStatus.active},
    StudyStatus.active: {StudyStatus.enrollment_closed},
    StudyStatus.enrollment_closed: {StudyStatus.locked},
    StudyStatus.locked: {StudyStatus.archived},
    StudyStatus.archived: set(),  # terminal state
}


class StudyService:
    """Manages study creation, retrieval, listing, and status transitions."""

    # ------------------------------------------------------------------
    # Create (Req 4.1, 4.2, 4.5)
    # ------------------------------------------------------------------

    async def create_study(
        self,
        session: AsyncSession,
        data: StudyCreate,
        actor_id: UUID,
    ) -> Study:
        """Create a new Study with status Draft and an initial StudyVersion.

        Args:
            session: Active async database session (caller's transaction).
            data: Validated StudyCreate schema.
            actor_id: UUID of the user performing the action.

        Returns:
            The created Study instance.

        Raises:
            ConflictError: If the study_code already exists (Req 4.2).
        """
        # Check uniqueness of study_code (Req 4.2)
        existing = await session.execute(
            select(Study).where(Study.study_code == data.study_code)
        )
        if existing.scalars().first() is not None:
            raise ConflictError(
                message="Study code already exists",
                details={"study_code": data.study_code},
            )

        # Create the Study (Req 4.1)
        study = Study(
            study_code=data.study_code,
            protocol_number=data.protocol_number,
            title=data.title,
            sponsor=data.sponsor,
            phase=data.phase,
            therapeutic_area=data.therapeutic_area,
            indication=data.indication,
            status=StudyStatus.draft,
            created_by=actor_id,
        )
        session.add(study)
        await session.flush()  # Assign the id

        # Create initial StudyVersion (version 1.0, draft)
        version = StudyVersion(
            study_id=study.id,
            version_number="1.0",
            status=StudyVersionStatus.draft,
        )
        session.add(version)
        await session.flush()

        # Write Audit_Event (Req 4.5)
        await audit_service.record(
            session,
            entity_type="study",
            entity_id=study.id,
            action="create",
            study_id=study.id,
            actor_id=actor_id,
            new_value=f"study_code={study.study_code}, title={study.title}",
        )

        logger.info("Study created: id=%s code=%s actor=%s", study.id, study.study_code, actor_id)
        return study

    # ------------------------------------------------------------------
    # Status transition (Req 4.3, 4.5)
    # ------------------------------------------------------------------

    async def transition_status(
        self,
        session: AsyncSession,
        study: Study,
        target_status: StudyStatus,
        actor_id: UUID,
    ) -> Study:
        """Transition a Study's status along the allowed state machine.

        Legal transitions:
            Draft → UAT → Active → Enrollment Closed → Locked → Archived

        Args:
            session: Active async database session.
            study: The Study instance to transition.
            target_status: The desired target status.
            actor_id: UUID of the user performing the action.

        Returns:
            The updated Study instance.

        Raises:
            BusinessRuleError: If the transition is illegal (Req 4.3).
        """
        current_status = StudyStatus(study.status)
        allowed = _LEGAL_TRANSITIONS.get(current_status, set())

        if target_status not in allowed:
            raise BusinessRuleError(
                message=f"Illegal status transition from '{current_status.value}' to '{target_status.value}'",
                details={
                    "current_status": current_status.value,
                    "target_status": target_status.value,
                    "allowed_transitions": [s.value for s in allowed],
                },
            )

        old_status = current_status.value
        study.status = target_status
        study.updated_at = datetime.now(UTC)
        await session.flush()

        # Write Audit_Event (Req 4.5)
        await audit_service.record(
            session,
            entity_type="study",
            entity_id=study.id,
            action="status_transition",
            study_id=study.id,
            actor_id=actor_id,
            field_name="status",
            old_value=old_status,
            new_value=target_status.value,
        )

        logger.info(
            "Study status transitioned: id=%s %s→%s actor=%s",
            study.id, old_status, target_status.value, actor_id,
        )
        return study

    # ------------------------------------------------------------------
    # Get by ID
    # ------------------------------------------------------------------

    async def get_study(self, session: AsyncSession, study_id: UUID) -> Study:
        """Retrieve a Study by its primary key.

        Args:
            session: Active async database session.
            study_id: The UUID of the study.

        Returns:
            The Study instance.

        Raises:
            NotFoundError: If no study exists with the given ID.
        """
        result = await session.execute(
            select(Study).where(Study.id == study_id, Study.deleted_at.is_(None))
        )
        study = result.scalars().first()
        if study is None:
            raise NotFoundError(
                message="Study not found",
                details={"study_id": str(study_id)},
            )
        return study

    # ------------------------------------------------------------------
    # List (with pagination)
    # ------------------------------------------------------------------

    async def list_studies(
        self,
        session: AsyncSession,
        pagination: PaginationParams,
    ) -> PaginatedResponse:
        """List active (non-deleted) studies with pagination.

        Args:
            session: Active async database session.
            pagination: Page/page_size pagination parameters.

        Returns:
            PaginatedResponse containing Study instances.
        """
        query = (
            select(Study)
            .where(Study.deleted_at.is_(None))
            .order_by(Study.created_at.desc())
        )
        return await paginate(session, query, pagination)


# Module-level singleton for convenience
study_service = StudyService()
