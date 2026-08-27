"""Dashboard_Service — read-only aggregation metrics for studies, sites, and queries.

All metrics are computed via SQL aggregation queries. The Authorization_Scope
filtering is done at the route level — the caller passes study_id/site_id that
have already been authorized.

Satisfies Requirements:
  - 4.4: Study dashboard accessible from study management.
  - 6.3: Site dashboard accessible from site management.
  - 20.1: Study dashboard: subject counts by status, form completion, open queries.
  - 20.2: Site dashboard: site-level progress.
  - 20.3: Query metrics: open/answered/overdue counts and aging.
  - 20.4: All metrics computed strictly within the caller's Authorization_Scope.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.query import Query, QueryStatus
from app.models.subject import Subject
from app.schemas.dashboard import QueryMetrics, SiteDashboard, StudyDashboard

logger = logging.getLogger(__name__)

# Queries open longer than this are considered overdue (Requirement 20.3)
OVERDUE_THRESHOLD_DAYS = 14


class DashboardService:
    """Read-only dashboard aggregation service.

    Methods accept study_id or site_id that have already been validated
    against the caller's Authorization_Scope at the route level.
    """

    # ------------------------------------------------------------------
    # Study Dashboard (Req 20.1, 4.4)
    # ------------------------------------------------------------------

    async def study_dashboard(
        self,
        session: AsyncSession,
        study_id: UUID,
    ) -> StudyDashboard:
        """Compute study-level dashboard metrics.

        Args:
            session: Active async database session.
            study_id: UUID of the study (already authorized).

        Returns:
            StudyDashboard with subject counts by status, form completion,
            and open query count.
        """
        # --- Subject counts by status ---
        subject_counts = await self._subject_counts_by_status(
            session, study_id=study_id
        )

        # --- Form completion ---
        total_forms, submitted_forms = await self._form_completion(
            session, study_id=study_id
        )

        # --- Open query count ---
        open_queries = await self._open_query_count(session, study_id=study_id)

        dashboard = StudyDashboard(
            subject_counts_by_status=subject_counts,
            total_form_instances=total_forms,
            submitted_form_instances=submitted_forms,
            open_query_count=open_queries,
        )

        logger.debug("Study dashboard computed: study_id=%s", study_id)
        return dashboard

    # ------------------------------------------------------------------
    # Site Dashboard (Req 20.2, 6.3)
    # ------------------------------------------------------------------

    async def site_dashboard(
        self,
        session: AsyncSession,
        site_id: UUID,
    ) -> SiteDashboard:
        """Compute site-level dashboard metrics.

        Args:
            session: Active async database session.
            site_id: UUID of the site (already authorized).

        Returns:
            SiteDashboard with subject counts by status, form completion,
            and open query count for the site.
        """
        # --- Subject counts by status ---
        subject_counts = await self._subject_counts_by_status(
            session, site_id=site_id
        )

        # --- Form completion ---
        total_forms, submitted_forms = await self._form_completion(
            session, site_id=site_id
        )

        # --- Open query count ---
        open_queries = await self._open_query_count(session, site_id=site_id)

        dashboard = SiteDashboard(
            subject_counts_by_status=subject_counts,
            total_form_instances=total_forms,
            submitted_form_instances=submitted_forms,
            open_query_count=open_queries,
        )

        logger.debug("Site dashboard computed: site_id=%s", site_id)
        return dashboard

    # ------------------------------------------------------------------
    # Query Metrics (Req 20.3)
    # ------------------------------------------------------------------

    async def query_metrics(
        self,
        session: AsyncSession,
        study_id: UUID,
    ) -> QueryMetrics:
        """Compute query metrics for a study.

        Args:
            session: Active async database session.
            study_id: UUID of the study (already authorized).

        Returns:
            QueryMetrics with open/answered/closed/cancelled counts,
            overdue count, and average days open for open queries.
        """
        now = datetime.now(UTC)

        # Count queries by status
        status_counts_stmt = (
            select(
                Query.status,
                func.count().label("cnt"),
            )
            .where(Query.study_id == study_id)
            .group_by(Query.status)
        )

        result = await session.execute(status_counts_stmt)
        rows = result.all()

        counts: dict[str, int] = {}
        for row in rows:
            counts[row.status] = row.cnt

        open_count = counts.get(QueryStatus.open, 0) + counts.get(
            QueryStatus.reopened, 0
        )
        answered_count = counts.get(QueryStatus.answered, 0)
        closed_count = counts.get(QueryStatus.closed, 0)
        cancelled_count = counts.get(QueryStatus.cancelled, 0)

        # Fetch creation dates for open queries to compute overdue and aging.
        # Computing in Python avoids database-specific interval syntax issues.
        open_queries_stmt = (
            select(Query.created_at)
            .where(
                Query.study_id == study_id,
                Query.status.in_([QueryStatus.open, QueryStatus.reopened]),
            )
        )
        open_result = await session.execute(open_queries_stmt)
        open_dates = open_result.scalars().all()

        overdue_count = 0
        total_days_open = 0.0
        for created_at in open_dates:
            # Ensure timezone-aware comparison
            if created_at.tzinfo is None:
                days_open = (now.replace(tzinfo=None) - created_at).total_seconds() / 86400.0
            else:
                days_open = (now - created_at).total_seconds() / 86400.0
            total_days_open += days_open
            if days_open > OVERDUE_THRESHOLD_DAYS:
                overdue_count += 1

        average_days_open = (
            round(total_days_open / len(open_dates), 2)
            if open_dates
            else 0.0
        )

        metrics = QueryMetrics(
            open_count=open_count,
            answered_count=answered_count,
            closed_count=closed_count,
            cancelled_count=cancelled_count,
            overdue_count=overdue_count,
            average_days_open=average_days_open,
        )

        logger.debug("Query metrics computed: study_id=%s", study_id)
        return metrics

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _subject_counts_by_status(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> dict[str, int]:
        """Count non-deleted subjects grouped by status.

        Filters by study_id or site_id (or both).
        """
        stmt = (
            select(Subject.status, func.count().label("cnt"))
            .where(Subject.deleted_at.is_(None))
            .group_by(Subject.status)
        )

        if study_id is not None:
            stmt = stmt.where(Subject.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(Subject.site_id == site_id)

        result = await session.execute(stmt)
        rows = result.all()

        return {row.status: row.cnt for row in rows}

    async def _form_completion(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> tuple[int, int]:
        """Count total form instances and submitted (or beyond) instances.

        Joins through Subject to filter by study or site.

        Returns:
            (total_count, submitted_count)
        """
        # Statuses that count as "submitted or beyond"
        submitted_statuses = [
            FormInstanceStatus.submitted,
            FormInstanceStatus.reviewed,
            FormInstanceStatus.frozen,
            FormInstanceStatus.locked,
            FormInstanceStatus.signed,
        ]

        base_stmt = select(
            func.count().label("total"),
            func.count(
                case(
                    (FormInstance.status.in_(submitted_statuses), FormInstance.id),
                    else_=None,
                )
            ).label("submitted"),
        ).select_from(FormInstance)

        # Join to Subject for study/site filtering
        if study_id is not None or site_id is not None:
            base_stmt = base_stmt.join(
                Subject, FormInstance.subject_id == Subject.id
            )
            if study_id is not None:
                base_stmt = base_stmt.where(Subject.study_id == study_id)
            if site_id is not None:
                base_stmt = base_stmt.where(Subject.site_id == site_id)

        result = await session.execute(base_stmt)
        row = result.one()

        return row.total, row.submitted

    async def _open_query_count(
        self,
        session: AsyncSession,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
    ) -> int:
        """Count queries in Open or Reopened status."""
        stmt = (
            select(func.count())
            .select_from(Query)
            .where(Query.status.in_([QueryStatus.open, QueryStatus.reopened]))
        )

        if study_id is not None:
            stmt = stmt.where(Query.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(Query.site_id == site_id)

        result = await session.execute(stmt)
        return result.scalar_one()


# Module-level singleton for convenience
dashboard_service = DashboardService()
