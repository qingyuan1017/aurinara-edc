"""Scope-aware PV safety dashboards and reports (Requirement 13).

PV owns safety dashboard/report content. This service reuses the shared
authorization primitive (``PermissionService.resolve_scope`` and
``AuthorizationScope.has_permission``) and the shared aggregation approach used
by the platform dashboards, rather than forking either. It queries only
PV-owned safety records (``pv_safety_cases``, ``pv_adverse_event_records``,
``pv_seriousness_assessments``, ``pv_regulatory_reports``/``pv_regulatory_clocks``)
and the approved read-only ``pv_edc_ae_projections`` read model.

Every metric is computed from PV records within the requesting user's
Authorization_Scope as of the request timestamp (Requirements 13.1, 13.4).
Reporting-compliance buckets are mutually exclusive and derived from report
status and the Regulatory_Clock due date versus the current UTC date, reusing
the pure ``is_overdue`` predicate owned by the ``Regulatory_Reporting_Service``
(Requirement 13.2). Site dashboards return only in-scope PV site metrics with
zero-valued metrics when no records qualify (Requirement 13.3). Any approved
EDC/CTMS projection is displayed only as read-only, source-labeled fields and is
never folded into a PV safety metric or mutated through PV (Requirement 13.5).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.pv import ReportStatus
from app.models.identity import User
from app.models.pv.assessment import SeriousnessAssessment
from app.models.pv.coordination import EdcAeProjection
from app.models.pv.regulatory import RegulatoryReport
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase
from app.schemas.permission import AuthorizationScope
from app.schemas.pv.dashboard import (
    ProjectedField,
    ReportingComplianceMetrics,
    SafetySiteDashboard,
    SafetyStudyDashboard,
)
from app.services.permission_service import PermissionService
from app.services.regulatory_reporting_service import regulatory_reporting_service

# PV read permission required to view safety dashboards/reports.
READ_PERMISSION = "safety_case.read"

# Seriousness buckets for adverse-event counts. An adverse event is classified
# from its most recent live Seriousness_Assessment; without one it is Unassessed.
SERIOUSNESS_SERIOUS = "Serious"
SERIOUSNESS_NON_SERIOUS = "Non-serious"
SERIOUSNESS_UNASSESSED = "Unassessed"

# Only the approved minimized projection fields may be surfaced (read-only).
_PROJECTION_DISPLAY_FIELDS: tuple[str, ...] = (
    "subject_reference",
    "verbatim_term",
    "onset_date",
    "seriousness",
)


def _active(row: Any) -> bool:
    """Return whether a PV record is live (not soft-deleted or archived)."""

    if getattr(row, "deleted_at", None) is not None:
        return False
    return getattr(row, "retention_state", "active") != "soft_deleted"


def _today_utc(now: datetime | None) -> date:
    """Return the current UTC date for compliance-bucket classification."""

    if now is None:
        return datetime.now(UTC).date()
    if now.tzinfo is None or now.utcoffset() is None:
        return now.replace(tzinfo=UTC).astimezone(UTC).date()
    return now.astimezone(UTC).date()


class PVDashboardService:
    """Aggregate PV safety dashboards after applying shared authorization scope."""

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self.permission_service = permission_service or PermissionService()

    # ------------------------------------------------------------------
    # Authorization scope (shared primitive, not forked)
    # ------------------------------------------------------------------

    def _scope(self, user: User | None) -> AuthorizationScope | None:
        if user is None:
            return None
        explicit = getattr(user, "authorization_scope", None)
        if isinstance(explicit, AuthorizationScope):
            return explicit
        if hasattr(user, "user_roles"):
            return self.permission_service.resolve_scope(user)
        return AuthorizationScope(grants=[])

    def _ensure_study_scope(
        self, scope: AuthorizationScope | None, study_id: UUID
    ) -> None:
        if scope is None or scope.has_permission(READ_PERMISSION, study_id=study_id):
            return
        # A site-scoped grant within the study still permits a study dashboard;
        # aggregation is then restricted to the granted sites.
        if any(
            grant.study_id == study_id and grant.site_id is not None
            for grant in scope.grants
        ):
            return
        raise AuthorizationError(
            "Insufficient permissions", {"study_id": str(study_id)}
        )

    def _ensure_site_scope(
        self, scope: AuthorizationScope | None, study_id: UUID, site_id: UUID
    ) -> None:
        if scope is None or scope.has_permission(
            READ_PERMISSION, study_id=study_id, site_id=site_id
        ):
            return
        if any(grant.site_id == site_id for grant in scope.grants):
            return
        raise AuthorizationError(
            "Insufficient permissions", {"site_id": str(site_id)}
        )

    def _allows(
        self,
        scope: AuthorizationScope | None,
        study_id: UUID,
        site_id: UUID | None,
    ) -> bool:
        if scope is None:
            return True
        return scope.has_permission(READ_PERMISSION, study_id=study_id, site_id=site_id)

    # ------------------------------------------------------------------
    # Study dashboard (Requirements 13.1, 13.2, 13.4, 13.5)
    # ------------------------------------------------------------------

    async def study_dashboard(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: User | None = None,
        *,
        now: datetime | None = None,
    ) -> SafetyStudyDashboard:
        """Return a PV safety study dashboard restricted to the user's scope."""

        scope = self._scope(user)
        self._ensure_study_scope(scope, study_id)
        current = datetime.now(UTC) if now is None else now

        cases = await self._scoped_cases(session, study_id=study_id, scope=scope)
        case_ids = [case.id for case in cases]

        case_counts = self._case_counts(cases)
        seriousness_counts = await self._seriousness_counts(session, case_ids)
        reports = await self._scoped_reports(session, case_ids)
        report_counts, compliance = self._report_metrics(reports, current)
        projected = await self._projected_fields(
            session, study_id=study_id, site_id=None, scope=scope
        )

        return SafetyStudyDashboard(
            study_id=study_id,
            case_counts_by_status=case_counts,
            adverse_event_counts_by_seriousness=seriousness_counts,
            report_counts_by_status=report_counts,
            reporting_compliance=compliance,
            projected_fields=projected,
            generated_at=current,
        )

    # ------------------------------------------------------------------
    # Site dashboard (Requirements 13.3, 13.4, 13.5)
    # ------------------------------------------------------------------

    async def site_dashboard(
        self,
        session: AsyncSession,
        site_id: UUID,
        user: User | None = None,
        *,
        study_id: UUID | None = None,
        now: datetime | None = None,
    ) -> SafetySiteDashboard:
        """Return a PV safety site dashboard with only in-scope site metrics.

        Zero-valued metrics are returned when no qualifying safety records exist
        (Requirement 13.3).
        """

        scope = self._scope(user)
        if study_id is None:
            study_id = await self._resolve_site_study(session, site_id)
        if study_id is None:
            raise AuthorizationError(
                "Site is outside the requested PV scope", {"site_id": str(site_id)}
            )
        self._ensure_site_scope(scope, study_id, site_id)
        current = datetime.now(UTC) if now is None else now

        cases = await self._scoped_cases(
            session, study_id=study_id, site_id=site_id, scope=scope
        )
        case_ids = [case.id for case in cases]

        case_counts = self._case_counts(cases)
        seriousness_counts = await self._seriousness_counts(session, case_ids)
        reports = await self._scoped_reports(session, case_ids)
        report_counts, compliance = self._report_metrics(reports, current)
        projected = await self._projected_fields(
            session, study_id=study_id, site_id=site_id, scope=scope
        )

        return SafetySiteDashboard(
            study_id=study_id,
            site_id=site_id,
            case_counts_by_status=case_counts,
            adverse_event_counts_by_seriousness=seriousness_counts,
            report_counts_by_status=report_counts,
            reporting_compliance=compliance,
            projected_fields=projected,
            generated_at=current,
        )

    # ------------------------------------------------------------------
    # Record loading (scoped, PV-only)
    # ------------------------------------------------------------------

    async def _scoped_cases(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None = None,
        scope: AuthorizationScope | None,
    ) -> list[SafetyCase]:
        stmt = select(SafetyCase).where(SafetyCase.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(SafetyCase.site_id == site_id)
        result = await session.execute(stmt)
        cases = [case for case in result.scalars().all() if _active(case)]
        return [
            case
            for case in cases
            if self._allows(scope, case.study_id, case.site_id)
        ]

    async def _seriousness_counts(
        self, session: AsyncSession, case_ids: list[UUID]
    ) -> dict[str, int]:
        """Count adverse events by seriousness classification (Requirement 13.1).

        Each live Adverse_Event_Record under an in-scope case is classified from
        its most recent live Seriousness_Assessment. Adverse events with no live
        assessment are counted as Unassessed.
        """

        counts: Counter[str] = Counter()
        if not case_ids:
            return dict(counts)

        ae_result = await session.execute(
            select(AdverseEventRecord).where(
                AdverseEventRecord.case_id.in_(case_ids)
            )
        )
        adverse_events = [ae for ae in ae_result.scalars().all() if _active(ae)]
        if not adverse_events:
            return dict(counts)

        ae_ids = [ae.id for ae in adverse_events]
        assessment_result = await session.execute(
            select(SeriousnessAssessment).where(
                SeriousnessAssessment.ae_id.in_(ae_ids)
            )
        )
        assessments = [
            row for row in assessment_result.scalars().all() if _active(row)
        ]

        # Most recent live assessment per adverse event by created_at.
        latest: dict[UUID, SeriousnessAssessment] = {}
        for assessment in assessments:
            current = latest.get(assessment.ae_id)
            if current is None or _created_at(assessment) >= _created_at(current):
                latest[assessment.ae_id] = assessment

        for ae in adverse_events:
            assessment = latest.get(ae.id)
            if assessment is None:
                counts[SERIOUSNESS_UNASSESSED] += 1
            elif assessment.serious:
                counts[SERIOUSNESS_SERIOUS] += 1
            else:
                counts[SERIOUSNESS_NON_SERIOUS] += 1

        return dict(counts)

    async def _scoped_reports(
        self, session: AsyncSession, case_ids: list[UUID]
    ) -> list[RegulatoryReport]:
        if not case_ids:
            return []
        result = await session.execute(
            select(RegulatoryReport).where(RegulatoryReport.case_id.in_(case_ids))
        )
        return [report for report in result.scalars().all() if _active(report)]

    async def _resolve_site_study(
        self, session: AsyncSession, site_id: UUID
    ) -> UUID | None:
        result = await session.execute(
            select(SafetyCase.study_id)
            .where(SafetyCase.site_id == site_id)
            .limit(1)
        )
        return result.scalars().first()

    # ------------------------------------------------------------------
    # Metric computation (PV-only)
    # ------------------------------------------------------------------

    @staticmethod
    def _case_counts(cases: list[SafetyCase]) -> dict[str, int]:
        return dict(Counter(case.lifecycle_state for case in cases))

    def _report_metrics(
        self, reports: list[RegulatoryReport], now: datetime
    ) -> tuple[dict[str, int], ReportingComplianceMetrics]:
        """Compute report counts by status and mutually exclusive compliance buckets.

        Buckets are derived from report status and the Regulatory_Clock due date
        versus the current UTC date using the shared pure ``is_overdue``
        predicate (Requirement 13.2).
        """

        status_counts: Counter[str] = Counter()
        today = _today_utc(now)
        submitted = overdue = on_time = 0

        for report in reports:
            status_value = report.status
            status_counts[status_value] += 1
            status = _to_report_status(status_value)

            if status is ReportStatus.SUBMITTED:
                submitted += 1
                continue

            due_date = self._due_date(report)
            if due_date is None:
                # No clock: cannot be overdue; classify as on time (not late).
                on_time += 1
                continue

            if regulatory_reporting_service.is_overdue(due_date, status, today):
                overdue += 1
            else:
                on_time += 1

        compliance = ReportingComplianceMetrics(
            submitted=submitted, overdue=overdue, on_time=on_time
        )
        # Surface the current overdue count on the PV metrics endpoint as a
        # gauge; only the integer count is recorded, never report content.
        from app.services.pv_observability_service import pv_observability_service

        pv_observability_service.set_overdue_reports(overdue)
        return dict(status_counts), compliance

    @staticmethod
    def _due_date(report: RegulatoryReport) -> date | None:
        clock = getattr(report, "clock", None)
        if clock is None:
            return None
        return getattr(clock, "due_date", None)

    # ------------------------------------------------------------------
    # Read-only projections (Requirement 13.5)
    # ------------------------------------------------------------------

    async def _projected_fields(
        self,
        session: AsyncSession,
        *,
        study_id: UUID,
        site_id: UUID | None,
        scope: AuthorizationScope | None,
    ) -> list[ProjectedField]:
        """Surface approved EDC projections as read-only, source-labeled fields.

        Only ``Current`` projections within the requested scope are displayed,
        and only their approved minimized fields. Projected values never enter a
        PV safety metric calculation and are never mutated through PV.
        """

        stmt = select(EdcAeProjection).where(EdcAeProjection.study_id == study_id)
        if site_id is not None:
            stmt = stmt.where(EdcAeProjection.site_id == site_id)
        result = await session.execute(stmt)

        projected: list[ProjectedField] = []
        for row in result.scalars().all():
            if not _active(row):
                continue
            if str(getattr(row, "projection_status", "")).lower() != "current":
                continue
            if not self._allows(scope, study_id, getattr(row, "site_id", None)):
                continue
            for field_name in _PROJECTION_DISPLAY_FIELDS:
                projected.append(
                    ProjectedField(
                        projection_id=row.id,
                        source_module=row.source_module,
                        field_name=field_name,
                        value=_display_value(getattr(row, field_name, None)),
                        read_only=True,
                        ownership="projected",
                    )
                )
        return projected


def _created_at(row: Any) -> datetime:
    """Return a comparable creation timestamp (UTC-aware) for ordering."""

    value = getattr(row, "created_at", None)
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_report_status(value: Any) -> ReportStatus:
    if isinstance(value, ReportStatus):
        return value
    return ReportStatus(value)


def _display_value(value: Any) -> Any:
    """Render a projected scalar as a display-safe value."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


pv_dashboard_service = PVDashboardService()

__all__ = [
    "READ_PERMISSION",
    "SERIOUSNESS_NON_SERIOUS",
    "SERIOUSNESS_SERIOUS",
    "SERIOUSNESS_UNASSESSED",
    "PVDashboardService",
    "pv_dashboard_service",
]
