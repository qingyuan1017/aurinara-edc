"""Study_Version_Service — Design_Version lifecycle and immutability guard.

Owned by the Designer module (the Design_Version lifecycle). This service was
moved from ``app.services.edc.study_version_service`` as part of the Designer /
EDC refactor; a backward-compatible shim remains at the old path (R2, R11.1).

Satisfies Requirements:
  - 2.1: Publish a draft Design_Version (draft → published).
  - 2.2: Publication records the actor and the timestamp.
  - 2.3: Reject an invalid publish, leaving the Design_Version a draft.
  - 2.4: Reject modifications to a published version and its child entities.
  - 2.9: Amend a published version with a reason of 1-4,000 characters, creating
         exactly one new draft.
  - 2.10: Reject an amendment whose reason is empty or exceeds 4,000 characters,
          creating no new draft.
  - 2.11: Retain all prior published versions for traceability.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.designer.study_version import (
    StudyVersion,
    StudyVersionStatus,
)
from app.models.edc.study import Study
from app.models.edc.subject import Subject
from app.repositories.designer.study_version_repository import StudyVersionRepository
from app.services.designer.design_clone_service import (
    DesignCloneService,
    design_clone_service,
)
from app.services.designer.design_validation_service import (
    DesignValidationService,
    design_validation_service,
)
from app.services.designer.subject_phase_service import (
    SubjectPhaseService,
    subject_phase_service,
)

logger = logging.getLogger(__name__)

# Amendment reason bounds (Requirements 2.9, 2.10): 1-4,000 characters inclusive.
AMENDMENT_REASON_MAX_LENGTH = 4000


class StudyVersionService:
    """Manages the Design_Version lifecycle and immutable version history."""

    def __init__(
        self,
        repository: StudyVersionRepository | None = None,
        *,
        validation_service: DesignValidationService | None = None,
        clone_service: DesignCloneService | None = None,
        phase_service: SubjectPhaseService | None = None,
    ) -> None:
        self.repository = repository or StudyVersionRepository()
        self.validation_service = validation_service or design_validation_service
        self.clone_service = clone_service or design_clone_service
        self.phase_service = phase_service or subject_phase_service

    # ------------------------------------------------------------------
    # Amendment creation (Requirements 2.9, 2.10, 2.11)
    # ------------------------------------------------------------------

    async def create_amendment(
        self,
        session: AsyncSession,
        study: Study,
        reason: str,
        actor_id: UUID,
    ) -> StudyVersion:
        """Create a draft amendment without changing published history.

        Amendments are based on the latest published version. The source
        version is retained through ``amended_from_version_id`` and published
        versions are never updated or replaced (R2.11). Only one draft may be
        open for a study at a time so an amendment has a deterministic successor.

        The amendment reason must be 1 to 4,000 characters inclusive. An empty
        or over-length reason is rejected before any lookup and no draft is
        created (R2.10).
        """
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError(
                "Amendment reason is required",
                details={"field": "reason"},
            )
        if len(normalized_reason) > AMENDMENT_REASON_MAX_LENGTH:
            raise ValidationError(
                f"Amendment reason must not exceed {AMENDMENT_REASON_MAX_LENGTH} characters",
                details={
                    "field": "reason",
                    "max_length": AMENDMENT_REASON_MAX_LENGTH,
                    "length": len(normalized_reason),
                },
            )

        source = await self.repository.latest_published(session, study.id)
        if source is None:
            raise BusinessRuleError(
                "An amendment can only be created from a published study version",
                details={"study_id": str(study.id)},
            )

        existing_draft = await self.repository.draft_for_study(session, study.id)
        if existing_draft is not None:
            raise ConflictError(
                "A draft study version already exists for this study",
                details={
                    "study_id": str(study.id),
                    "version_id": str(existing_draft.id),
                },
            )

        # Version numbers are retained across the complete history, including
        # abandoned drafts. Deriving only from the latest published version can
        # therefore collide with a retained abandoned successor (for example,
        # published 3.0 plus abandoned 4.0). Always advance beyond every
        # recognizable version number already owned by the study.
        version_history = await self.repository.list_for_study(session, study.id)

        version = StudyVersion(
            study_id=study.id,
            version_number=self._next_available_version_number(
                source.version_number,
                [item.version_number for item in version_history],
            ),
            status=StudyVersionStatus.draft,
            odm_study_oid=source.odm_study_oid,
            amendment_reason=normalized_reason,
            amended_from_version_id=source.id,
        )
        await self.repository.add(session, version)

        # An amendment is an editable successor of the published design, not an
        # empty shell. Clone the complete live definition graph after the target
        # version has an id. Any failure rolls the version and all children back
        # with the caller's transaction.
        clone_counts = await self.clone_service.clone_version(
            session,
            source_version_id=source.id,
            target_version_id=version.id,
        )

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="amend",
            module=Module.DESIGNER,
            study_id=study.id,
            actor_id=actor_id,
            old_value=str(source.id),
            new_value=(
                f"version={version.version_number}; reason={normalized_reason}; "
                f"amended_from={source.id}; "
                f"cloned_definitions={sum(clone_counts.values())}"
            ),
            reason=normalized_reason,
        )

        logger.info(
            "Study amendment created: version_id=%s source_version_id=%s study_id=%s actor=%s",
            version.id,
            source.id,
            study.id,
            actor_id,
        )
        return version

    @staticmethod
    def _next_version_number(source_version_number: str) -> str:
        """Return the next major version for native and imported draft labels."""
        return StudyVersionService._next_available_version_number(
            source_version_number,
            (),
        )

    @staticmethod
    def _next_available_version_number(
        source_version_number: str,
        existing_version_numbers: list[str] | tuple[str, ...],
    ) -> str:
        """Return a major version above the source and all retained history."""

        major_versions: list[int] = []
        for version_number in (source_version_number, *existing_version_numbers):
            match = re.match(
                r"^\s*(?:draft\s+)?v?(\d+)(?:\.\d+)?",
                version_number,
                flags=re.IGNORECASE,
            )
            if match is not None:
                major_versions.append(int(match.group(1)))

        if not major_versions:
            raise ValidationError(
                "Published version number must include a recognizable major version",
                details={"version_number": source_version_number},
            )

        return f"{max(major_versions) + 1}.0"

    async def abandon_draft(
        self,
        session: AsyncSession,
        version: StudyVersion,
        reason: str,
        actor_id: UUID,
    ) -> StudyVersion:
        """Retain a draft as immutable abandoned history.

        Published versions and drafts already referenced by operational subject
        records cannot be abandoned. The required reason and lifecycle change
        are retained both on the version and in the immutable audit trail.
        """
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError(
                "Abandonment reason is required",
                details={"field": "reason"},
            )
        if len(normalized_reason) > AMENDMENT_REASON_MAX_LENGTH:
            raise ValidationError(
                f"Abandonment reason must not exceed {AMENDMENT_REASON_MAX_LENGTH} characters",
                details={
                    "field": "reason",
                    "max_length": AMENDMENT_REASON_MAX_LENGTH,
                    "length": len(normalized_reason),
                },
            )
        if version.status != StudyVersionStatus.draft:
            raise BusinessRuleError(
                "Only a draft study version can be abandoned",
                details={"version_id": str(version.id), "current_status": version.status},
            )

        referenced_subject_id = await session.scalar(
            select(Subject.id).where(Subject.study_version_id == version.id).limit(1)
        )
        if referenced_subject_id is not None:
            raise ConflictError(
                "A study version referenced by operational subjects cannot be abandoned",
                details={
                    "version_id": str(version.id),
                    "subject_id": str(referenced_subject_id),
                },
            )

        abandoned_at = datetime.now(UTC)
        old_status = version.status
        version.status = StudyVersionStatus.abandoned
        version.abandoned_at = abandoned_at
        version.abandoned_by = actor_id
        version.abandonment_reason = normalized_reason

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="abandon",
            module=Module.DESIGNER,
            study_id=version.study_id,
            field_name="status",
            old_value=old_status,
            new_value=StudyVersionStatus.abandoned,
            actor_id=actor_id,
            reason=normalized_reason,
        )
        await session.flush()

        logger.info(
            "Study version abandoned: version_id=%s study_id=%s actor=%s",
            version.id,
            version.study_id,
            actor_id,
        )
        return version

    # ------------------------------------------------------------------
    # Publish (Requirements 2.1, 2.2, 2.3)
    # ------------------------------------------------------------------

    async def publish(
        self,
        session: AsyncSession,
        version: StudyVersion,
        actor_id: UUID,
    ) -> StudyVersion:
        """Transition a Design_Version from draft to published.

        Validates the complete design graph before changing state, records the
        publication actor and timestamp (R2.2), and writes an Audit_Event. An
        invalid publish is rejected and the version is left unchanged (R2.3).

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

        await self.validation_service.require_publishable(session, version)

        old_status = version.status
        version.status = StudyVersionStatus.published
        version.published_at = datetime.now(UTC)
        version.published_by = actor_id

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="publish",
            module=Module.DESIGNER,
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
    # Immutability guard (Requirement 2.4)
    # ------------------------------------------------------------------

    def guard_mutable(self, version: StudyVersion) -> None:
        """Allow writes only to an active draft and block retained history.

        This method is called by Form_Metadata_Service, Visit_Service, and
        Edit_Check_Engine before any metadata write to child entities.

        Args:
            version: The StudyVersion to check.

        Raises:
            BusinessRuleError: If the version is published or abandoned.
        """
        if version.status == StudyVersionStatus.published:
            raise BusinessRuleError(
                "Cannot modify a published study version",
                details={"version_id": str(version.id), "status": version.status},
            )
        if version.status != StudyVersionStatus.draft:
            raise BusinessRuleError(
                "Cannot modify an abandoned study version",
                details={"version_id": str(version.id), "status": version.status},
            )

    # ------------------------------------------------------------------
    # Create version (Requirement 2.1 — draft creation)
    # ------------------------------------------------------------------

    async def create_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        version_number: str,
        amendment_reason: str | None = None,
        actor_id: UUID | None = None,
    ) -> StudyVersion:
        """Create a new draft Design_Version for a study.

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

        await self.phase_service.seed_default_phase_flow(
            session,
            design_version_id=version.id,
            study_id=study_id,
            actor_id=actor_id,
        )

        await audit_service.record(
            session,
            entity_type="study_version",
            entity_id=version.id,
            action="create",
            module=Module.DESIGNER,
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
    # Get version (Requirement 2.11 — retrieval of retained versions)
    # ------------------------------------------------------------------

    async def get_version(
        self,
        session: AsyncSession,
        version_id: UUID,
    ) -> StudyVersion:
        """Retrieve a Design_Version by its ID.

        Args:
            session: The active async session.
            version_id: The UUID of the version to retrieve.

        Returns:
            The StudyVersion instance.

        Raises:
            NotFoundError: If no version with the given ID exists.
        """
        result = await session.execute(select(StudyVersion).where(StudyVersion.id == version_id))
        version = result.scalars().first()

        if version is None:
            raise NotFoundError(
                "Study version not found",
                details={"version_id": str(version_id)},
            )

        return version


# Module-level singleton for convenience
study_version_service = StudyVersionService()
