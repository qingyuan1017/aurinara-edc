"""Report_Service — read-only, server-side scope-filtered EDC reporting.

Groups the EDC_Module Report_Area report families behind a single service:

  - Data Summary (R9.1)
  - CRF Status (R9.2)
  - Query Report (R9.3)
  - Enrollment Status (R9.4) — data-backed by the Subject operational model
  - eCOA / eDiary Report (R9.5)
  - On-Demand / KRI-Central Monitoring / SDV-SDR Workload / Data Analysis /
    Comment / Source Document Tracker (R9.6)
  - End of Study (R9.7)

Every report is **scope-filtered server-side** through the shared
``permission_service`` and is independent of any frontend check:

  - only records within the requesting user's Authorization_Scope are returned
    (R9.8);
  - an empty result set is returned when nothing is in scope, which is a normal
    (non-error) response (R9.9);
  - a request the user is not authorized for is rejected with a not-authorized
    error (R9.10) — enforced by ``require_permission`` at the route boundary and
    re-checked here before any read.

Where a report family has no dedicated backing data model yet, the service
returns a structured, scope-filtered envelope (empty ``rows`` scoped to the
authorized studies). The scope-filtering and authorization behavior is real and
testable in every case; only the row payload is a boundary placeholder for the
not-yet-modeled sections, mirroring the CTMS/PV operational scaffolding.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edc.study import Study
from app.models.edc.subject import Subject
from app.models.shared.identity import User
from app.schemas.edc.report import (
    EnrollmentStatusReport,
    EnrollmentStatusRow,
    ReportMeta,
    ReportResponse,
)
from app.services.shared.permission_service import PermissionService

logger = logging.getLogger(__name__)


class ReportService:
    """Read-only reporting service with server-side scope filtering.

    The service never mutates state. Authorization is enforced twice: the route
    guard rejects users lacking the required permission (R9.10), and every read
    path here restricts rows to the studies returned by
    ``permission_service.filter_studies`` so a payload can only ever contain
    in-scope records (R9.8) and is empty when nothing is in scope (R9.9).
    """

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self._permissions = permission_service or PermissionService()

    # ------------------------------------------------------------------
    # Scope resolution (shared by every report family)
    # ------------------------------------------------------------------

    async def _studies_in_scope(
        self,
        session: AsyncSession,
        user: User,
        *,
        study_id: UUID | None = None,
    ) -> list[UUID]:
        """Return the studies the user may see, honoring an optional filter.

        Resolves the universe of non-deleted study IDs (optionally narrowed to a
        single requested ``study_id``) and filters it through
        ``permission_service.filter_studies``. The result is the authoritative,
        server-side list of in-scope studies for a report request.

        An out-of-scope ``study_id`` collapses the universe to an empty list,
        yielding an empty report rather than leaking that the study exists
        (R9.8/R9.9).
        """
        stmt = select(Study.id).where(Study.deleted_at.is_(None))
        if study_id is not None:
            stmt = stmt.where(Study.id == study_id)
        result = await session.execute(stmt)
        universe = list(result.scalars().all())
        return self._permissions.filter_studies(user, universe)

    def _empty_meta(self, report_key: str, report_group: str, study_ids: list[UUID]) -> ReportMeta:
        return ReportMeta(
            report_key=report_key,
            report_group=report_group,
            study_ids_in_scope=study_ids,
            total=0,
        )

    async def _structured_report(
        self,
        session: AsyncSession,
        user: User,
        *,
        report_key: str,
        report_group: str,
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """Build a scope-filtered structured report envelope.

        Used by report families without a dedicated backing data model yet. The
        envelope carries the real in-scope study list so the scope-filtering and
        empty-when-none behavior (R9.8/R9.9) is observable even though ``rows``
        is an operational boundary placeholder.
        """
        study_ids = await self._studies_in_scope(session, user, study_id=study_id)
        return ReportResponse(
            meta=self._empty_meta(report_key, report_group, study_ids),
            rows=[],
        )

    # ------------------------------------------------------------------
    # Enrollment Status (R9.4) — data-backed by Subject
    # ------------------------------------------------------------------

    async def enrollment_status(
        self,
        session: AsyncSession,
        user: User,
        *,
        study_id: UUID | None = None,
    ) -> EnrollmentStatusReport:
        """Subject counts by status, scoped to the user's authorized studies.

        Only subjects belonging to in-scope studies are counted (R9.8). When no
        study is in scope the report is empty (R9.9). Access is rejected upstream
        for users lacking ``study.read`` (R9.10).
        """
        study_ids = await self._studies_in_scope(session, user, study_id=study_id)

        if not study_ids:
            # Nothing in scope — return an empty report, not an error (R9.9).
            return EnrollmentStatusReport(
                meta=self._empty_meta("enrollment.status", "Enrollment Status", []),
                rows=[],
            )

        stmt = (
            select(
                Subject.study_id,
                Subject.status,
                func.count().label("subject_count"),
            )
            .where(
                Subject.deleted_at.is_(None),
                Subject.study_id.in_(study_ids),
            )
            .group_by(Subject.study_id, Subject.status)
        )
        result = await session.execute(stmt)
        rows = [
            EnrollmentStatusRow(
                study_id=row.study_id,
                status=str(row.status),
                subject_count=row.subject_count,
            )
            for row in result.all()
        ]

        meta = ReportMeta(
            report_key="enrollment.status",
            report_group="Enrollment Status",
            study_ids_in_scope=study_ids,
            total=len(rows),
        )
        logger.debug(
            "Enrollment status report: studies_in_scope=%d rows=%d",
            len(study_ids),
            len(rows),
        )
        return EnrollmentStatusReport(meta=meta, rows=rows)

    # ------------------------------------------------------------------
    # Data Summary (R9.1)
    # ------------------------------------------------------------------

    async def data_summary(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "summary",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """Data Summary reports (Raw/CRF/Item/Visit/Audit/Log, etc.)."""
        return await self._structured_report(
            session,
            user,
            report_key=f"data_summary.{section}",
            report_group="Data Summary",
            study_id=study_id,
        )

    # ------------------------------------------------------------------
    # CRF Status (R9.2)
    # ------------------------------------------------------------------

    async def crf_status(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "status_summary",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """CRF Status reports (Status Summary, Form/Visit/Record details, etc.)."""
        return await self._structured_report(
            session,
            user,
            report_key=f"crf_status.{section}",
            report_group="CRF Status",
            study_id=study_id,
        )

    # ------------------------------------------------------------------
    # Query Report (R9.3)
    # ------------------------------------------------------------------

    async def query_report(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "all",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """Query Report (Aging, Manual/System/All/Lab/Exception details)."""
        return await self._structured_report(
            session,
            user,
            report_key=f"query_report.{section}",
            report_group="Query Report",
            study_id=study_id,
        )

    # ------------------------------------------------------------------
    # eCOA / eDiary Report (R9.5)
    # ------------------------------------------------------------------

    async def ecoa_ediary_report(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "completion_rate",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """eCOA and eDiary Report (Completion/Quality/Compliance, etc.)."""
        return await self._structured_report(
            session,
            user,
            report_key=f"ecoa_ediary.{section}",
            report_group="eCOA/eDiary Report",
            study_id=study_id,
        )

    # ------------------------------------------------------------------
    # On-Demand / KRI / SDV-SDR Workload / Data Analysis / Comment /
    # Source Document Tracker (R9.6)
    # ------------------------------------------------------------------

    async def operational_report(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "on_demand",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """On-Demand/KRI/SDV-SDR Workload/Data Analysis/Comment/Source Doc Tracker."""
        return await self._structured_report(
            session,
            user,
            report_key=f"operational.{section}",
            report_group="On-Demand/KRI/Workload/Analysis/Comment/SourceDocTracker",
            study_id=study_id,
        )

    # ------------------------------------------------------------------
    # End of Study (R9.7)
    # ------------------------------------------------------------------

    async def end_of_study(
        self,
        session: AsyncSession,
        user: User,
        *,
        section: str = "overview",
        study_id: UUID | None = None,
    ) -> ReportResponse:
        """End of Study reports (End of Study Overview, System Document)."""
        return await self._structured_report(
            session,
            user,
            report_key=f"end_of_study.{section}",
            report_group="End of Study",
            study_id=study_id,
        )


# Module-level singleton for convenience
report_service = ReportService()
