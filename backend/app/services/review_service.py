"""Review_Service — clinical review state and progress tracking.

Satisfies Requirements:
  - 15.1: Mark Form_Instances as reviewed with actor and timestamp.
  - 15.2: Clear review status and return a form to not reviewed.
  - 15.3: Report reviewed and not-reviewed counts for a requested scope.
  - 15.4: Write an Audit_Event for every review status mutation.

Review state is kept in the dedicated ``review_status`` table rather than in
``form_instances.status``. All writes use the caller's session so the review
row and its Audit_Event participate in the same transaction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.models.form_data import FormInstance
from app.models.review import ReviewStatus
from app.models.subject import Subject

logger = logging.getLogger(__name__)


class ReviewService:
    """Manage form-instance review toggles and scoped review progress."""

    async def mark_reviewed(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        actor_id: Any = None,
    ) -> ReviewStatus:
        """Mark a form instance reviewed and record the reviewer and time.

        Args:
            session: Active async database session (caller's transaction).
            form_instance: Form instance whose review status is being changed.
            actor_id: UUID of the user performing the review.

        Returns:
            The persisted ``ReviewStatus`` row.
        """
        actor_uuid, actor_email = self._normalize_actor(actor_id)
        review_status = await self._get_or_create_status(session, form_instance.id)
        old_reviewed = review_status.is_reviewed
        reviewed_at = datetime.now(UTC)

        review_status.is_reviewed = True
        review_status.reviewed_by = actor_uuid
        review_status.reviewed_at = reviewed_at
        review_status.updated_at = reviewed_at
        await session.flush()

        await self._record_audit(
            session,
            form_instance=form_instance,
            review_status=review_status,
            action="mark_reviewed",
            actor_id=actor_uuid,
            actor_email=actor_email,
            old_value=str(old_reviewed),
            new_value="True",
        )

        logger.info(
            "Form instance marked reviewed: form_instance_id=%s actor=%s",
            form_instance.id,
            actor_id,
        )
        return review_status

    async def clear_review(
        self,
        session: AsyncSession,
        form_instance: FormInstance,
        actor_id: Any = None,
    ) -> ReviewStatus:
        """Clear review state for a form instance.

        ``reviewed_by`` and ``reviewed_at`` are cleared because they describe
        the current reviewed state. The clearing actor remains attributable in
        the Audit_Event. ``actor_id`` is optional so request-context actor
        resolution can be used by callers that do not pass it explicitly.

        Args:
            session: Active async database session (caller's transaction).
            form_instance: Form instance whose review status is being cleared.
            actor_id: UUID of the user clearing review, when not supplied by
                the request context.

        Returns:
            The persisted ``ReviewStatus`` row.
        """
        actor_uuid, actor_email = self._normalize_actor(actor_id)
        review_status = await self._get_or_create_status(session, form_instance.id)
        old_reviewed = review_status.is_reviewed
        cleared_at = datetime.now(UTC)

        review_status.is_reviewed = False
        review_status.reviewed_by = None
        review_status.reviewed_at = None
        review_status.updated_at = cleared_at
        await session.flush()

        await self._record_audit(
            session,
            form_instance=form_instance,
            review_status=review_status,
            action="clear_review",
            actor_id=actor_uuid,
            actor_email=actor_email,
            old_value=str(old_reviewed),
            new_value="False",
        )

        logger.info(
            "Form instance review cleared: form_instance_id=%s actor=%s",
            form_instance.id,
            actor_id,
        )
        return review_status

    async def progress(
        self,
        session: AsyncSession,
        scope: Any = None,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        subject_id: UUID | None = None,
    ) -> dict[str, int]:
        """Return reviewed/not-reviewed form counts for a clinical scope.

        ``scope`` is treated as a study ID for the design's primary
        ``progress(scope)`` interface. Explicit ``study_id``, ``site_id``, or
        ``subject_id`` keyword arguments allow callers to request narrower
        scopes without changing the service contract. Form instances without a
        ``ReviewStatus`` row count as not reviewed.

        Returns:
            A dictionary with ``reviewed`` and ``not_reviewed`` integer counts.
        """
        if scope is not None and all(
            value is None for value in (study_id, site_id, subject_id)
        ):
            if isinstance(scope, UUID):
                study_id = scope
            elif isinstance(scope, str):
                try:
                    study_id = UUID(scope)
                except ValueError:
                    study_id = scope
            else:
                study_id = getattr(scope, "study_id", None)
                site_id = getattr(scope, "site_id", None)
                subject_id = getattr(scope, "subject_id", None)
                if isinstance(scope, Subject):
                    subject_id = scope.id

        stmt = select(
            func.count(FormInstance.id).label("total"),
            func.count(
                case(
                    (ReviewStatus.is_reviewed.is_(True), FormInstance.id),
                    else_=None,
                )
            ).label("reviewed"),
        ).select_from(FormInstance)
        stmt = stmt.join(Subject, FormInstance.subject_id == Subject.id)
        stmt = stmt.outerjoin(
            ReviewStatus,
            ReviewStatus.form_instance_id == FormInstance.id,
        )

        if study_id is not None:
            stmt = stmt.where(Subject.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(Subject.site_id == site_id)
        if subject_id is not None:
            stmt = stmt.where(Subject.id == subject_id)

        result = await session.execute(stmt)
        row = result.one()
        total = int(row.total or 0)
        reviewed = int(row.reviewed or 0)

        counts = {
            "reviewed": reviewed,
            "not_reviewed": total - reviewed,
        }
        logger.debug(
            "Review progress computed: study_id=%s site_id=%s subject_id=%s counts=%s",
            study_id,
            site_id,
            subject_id,
            counts,
        )
        return counts

    async def _get_or_create_status(
        self,
        session: AsyncSession,
        form_instance_id: UUID,
    ) -> ReviewStatus:
        """Fetch the unique status row or create its not-reviewed baseline."""
        result = await session.execute(
            select(ReviewStatus).where(
                ReviewStatus.form_instance_id == form_instance_id
            )
        )
        review_status = result.scalars().first()
        if review_status is None:
            review_status = ReviewStatus(
                form_instance_id=form_instance_id,
                is_reviewed=False,
            )
            session.add(review_status)
            await session.flush()
        return review_status

    async def _record_audit(
        self,
        session: AsyncSession,
        *,
        form_instance: FormInstance,
        review_status: ReviewStatus,
        action: str,
        actor_id: UUID | None,
        actor_email: str | None,
        old_value: str,
        new_value: str,
    ) -> None:
        """Write a review audit event with any loaded hierarchy context."""
        # Avoid triggering an async lazy load while retaining context when the
        # caller loaded the subject relationship with the form instance.
        subject: Any = form_instance.__dict__.get("subject")
        study_id = getattr(subject, "study_id", None)
        site_id = getattr(subject, "site_id", None)

        await audit_service.record(
            session,
            entity_type="review_status",
            entity_id=review_status.id,
            action=action,
            study_id=study_id,
            site_id=site_id,
            subject_id=form_instance.subject_id,
            actor_id=actor_id,
            actor_email=actor_email,
            field_name="is_reviewed",
            old_value=old_value,
            new_value=new_value,
        )

    @staticmethod
    def _normalize_actor(actor: Any) -> tuple[UUID | None, str | None]:
        """Normalize a UUID or authenticated User-like object for persistence."""
        if actor is None:
            return None, None
        actor_id = actor if isinstance(actor, UUID) else getattr(actor, "id", actor)
        normalized_id = UUID(str(actor_id))
        return normalized_id, getattr(actor, "email", None)


# Module-level singleton for route/service consumers.
review_service = ReviewService()
