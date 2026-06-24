"""Study_Version_Service — version lifecycle management and immutability guard.

Satisfies Requirements:
  - 5.1: Publish a draft Study_Version (draft → published), recording actor and timestamp.
  - 5.2: Reject modifications to a published version and its child entities.
  - 5.3: Create a new draft Study_Version (amendment) with reason.
  - 5.4: Retain all prior published versions for traceability.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.study import StudyVersion, StudyVersionStatus

logger = logging.getLogger(__name__)


class StudyVersionService:
    """Manages Study_Version lifecycle: creation, retrieval, publish, and the mutable guard."""

    # ------------------------------------------------------------------
    # Publish (Requirement 5.1)
    # ------------------------------------------------------------------

    async def publish(
        self,
        session: AsyncSession,
        version: StudyVersion,
        actor_id: UUID,
    ) -> StudyVersion:
        """Transition a Study_Version from draft to published.

        Records publication actor and timestamp. Writes an Audit_Event.

        Args:
            session: The active async session (caller's transaction).
            version: The StudyVersion to publish.
            actor_id: The UUID of the actor performing the publish.

        Returns:
            The updated StudyVersion with status=published.

        Raises:
            BusinessRuleError: If the version is not in draft status.
        """
        if version.status != StudyVersionStatus.draft:
            raise BusinessRuleError(
                "Cannot publish a study version that is not in draft status",
                details={"current_status": version.status, "version_id": str(version.id)},
            )

        old_status = version.status
        version.status = StudyVersionStatus.published
        version.published_at = datetime.now(UTC)
        version.published_by = actor_id

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="publish",
            study_id=version.study_id,
            field_name="status",
            old_value=old_status,
            new_value=StudyVersionStatus.published,
            actor_id=actor_id,
        )

        await session.flush()

        logger.info(
            "Study version published: version_id=%s study_id=%s actor=%s",
            version.id,
            version.study_id,
            actor_id,
        )

        return version

    # ------------------------------------------------------------------
    # Immutability guard (Requirement 5.2)
    # ------------------------------------------------------------------

    def guard_mutable(self, version: StudyVersion) -> None:
        """Block writes to a published Study_Version and its children.

        This method is called by Form_Metadata_Service, Visit_Service, and
        Edit_Check_Engine before any metadata write to child entities.

        Args:
            version: The StudyVersion to check.

        Raises:
            BusinessRuleError: If the version is published.
        """
        if version.status == StudyVersionStatus.published:
            raise BusinessRuleError(
                "Cannot modify a published study version",
                details={"version_id": str(version.id), "status": version.status},
            )

    # ------------------------------------------------------------------
    # Create version (Requirement 5.3)
    # ------------------------------------------------------------------

    async def create_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        version_number: str,
        amendment_reason: str | None = None,
        actor_id: UUID | None = None,
    ) -> StudyVersion:
        """Create a new draft Study_Version for a study.

        Args:
            session: The active async session (caller's transaction).
            study_id: The UUID of the parent study.
            version_number: The version identifier (e.g. "1.0", "2.0").
            amendment_reason: Optional reason for the amendment.
            actor_id: Optional actor UUID; auto-resolved from context if not provided.

        Returns:
            The newly created StudyVersion in draft status.
        """
        version = StudyVersion(
            study_id=study_id,
            version_number=version_number,
            status=StudyVersionStatus.draft,
            amendment_reason=amendment_reason,
        )

        session.add(version)
        await session.flush()

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="create",
            study_id=study_id,
            new_value=version_number,
            actor_id=actor_id,
        )

        logger.info(
            "Study version created: version_id=%s study_id=%s version_number=%s",
            version.id,
            study_id,
            version_number,
        )

        return version

    # ------------------------------------------------------------------
    # Get version (Requirement 5.4 — retrieval)
    # ------------------------------------------------------------------

    async def get_version(
        self,
        session: AsyncSession,
        version_id: UUID,
    ) -> StudyVersion:
        """Retrieve a Study_Version by its ID.

        Args:
            session: The active async session.
            version_id: The UUID of the version to retrieve.

        Returns:
            The StudyVersion instance.

        Raises:
            NotFoundError: If no version with the given ID exists.
        """
        result = await session.execute(
            select(StudyVersion).where(StudyVersion.id == version_id)
        )
        version = result.scalars().first()

        if version is None:
            raise NotFoundError(
                "Study version not found",
                details={"version_id": str(version_id)},
            )

        return version


# Module-level singleton for convenience
study_version_service = StudyVersionService()
