"""Scope-aware CTMS operational dashboards.

This service intentionally queries only CTMS-owned records and the typed,
approved projection table.  It never joins or reads EDC clinical content.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import MonitoringActivity
from app.models.ctms.operational_site import ActivationAction, OperationalSite
from app.models.ctms.operational_study import (
    OperationalStudy,
    ReadinessCriterion,
    StudyOperationalMilestone,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.work import OperationalContact, OperationalTask
from app.models.identity import User
from app.schemas.ctms.dashboard import CTMSDashboardResponse
from app.schemas.permission import AuthorizationScope
from app.services.permission_service import PermissionService

READ_PERMISSION = "ctms.operational_data_read"
_TERMINAL_TASK_STATUSES = {"Completed", "Cancelled", "Archived"}
_TERMINAL_MONITORING_STATUSES = {"Completed", "Cancelled"}
_ENROLLMENT_ACTUAL_STATUSES = {
    "Enrolled", "Randomized", "On Treatment", "Completed", "Early Terminated",
    "Lost to Follow-up", "Withdrawn",
}
_SCREENING_STATUSES = {"Screening", "Screen Failed"}


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _active(row: Any) -> bool:
    return getattr(row, "deleted_at", None) is None and getattr(row, "retention_state", "active") not in {"soft_deleted"}


def _timestamp(value: datetime | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CTMSDashboardService:
    """Aggregate CTMS dashboards after applying shared authorization scope."""

    def __init__(self, permission_service: PermissionService | None = None) -> None:
        self.permission_service = permission_service or PermissionService()

    def _scope(self, user: User | None) -> AuthorizationScope | None:
        if user is None:
            return None
        explicit = getattr(user, "authorization_scope", None)
        if isinstance(explicit, AuthorizationScope):
            return explicit
        if hasattr(user, "user_roles"):
            return self.permission_service.resolve_scope(user)
        return AuthorizationScope(grants=[])

    def _allows(self, scope: AuthorizationScope | None, study_id: UUID, site_id: UUID | None) -> bool:
        if scope is None:
            return True
        return scope.has_permission(READ_PERMISSION, study_id=study_id, site_id=site_id)

    def _ensure_study_scope(self, scope: AuthorizationScope | None, study_id: UUID) -> None:
        if scope is None or scope.has_permission(READ_PERMISSION, study_id=study_id):
            return
        # A site-scoped grant still permits a study dashboard, but aggregation
        # is restricted to those explicitly granted sites.
        if any(grant.study_id == study_id and grant.site_id is not None for grant in scope.grants):
            return
        raise AuthorizationError("Insufficient permissions", {"study_id": str(study_id)})

    def _ensure_site_scope(self, scope: AuthorizationScope | None, study_id: UUID | None, site_id: UUID) -> None:
        if scope is None or (study_id is not None and scope.has_permission(READ_PERMISSION, study_id, site_id)):
            return
        if any(grant.site_id == site_id for grant in scope.grants):
            return
        raise AuthorizationError("Insufficient permissions", {"site_id": str(site_id)})

    async def _rows(
        self,
        session: AsyncSession,
        model: type,
        *,
        study_id: UUID,
        site_id: UUID | None = None,
        scope: AuthorizationScope | None = None,
    ) -> list[Any]:
        result = await session.execute(select(model).where(model.study_id == study_id))
        rows = [row for row in result.scalars().all() if _active(row)]
        if site_id is not None:
            rows = [row for row in rows if getattr(row, "site_id", None) == site_id]
        return [row for row in rows if self._allows(scope, study_id, getattr(row, "site_id", None))]

    async def _projections(
        self, session: AsyncSession, *, study_id: UUID, site_id: UUID | None, scope: AuthorizationScope | None
    ) -> list[CTMSOperationalProjection]:
        rows = await self._rows(session, CTMSOperationalProjection, study_id=study_id, site_id=site_id, scope=scope)
        return [row for row in rows if str(_value(getattr(row, "status", "Current"))).lower() == "current" and getattr(row, "projection_type", None) == "data_quality_signal"]

    @staticmethod
    def _quality_signal(row: CTMSOperationalProjection, now: datetime) -> dict[str, Any]:
        payload = dict(getattr(row, "payload_json", None) or {})
        source_timestamp = _timestamp(getattr(row, "source_timestamp", None), now)
        freshness_seconds = None if source_timestamp is None else max(0, int((now - source_timestamp).total_seconds()))
        return {
            "projection_id": str(row.id),
            "signal_type": payload.get("signal_type"),
            "value": payload.get("value"),
            "numerator": payload.get("numerator"),
            "denominator": payload.get("denominator"),
            "read_only": True,
            "ownership": "projected",
            "source_module": row.source_module,
            "source_timestamp": source_timestamp,
            "freshness_seconds": freshness_seconds,
            "freshness": "fresh" if freshness_seconds is None or freshness_seconds <= 86400 else "stale",
            "rule_version": row.rule_version,
        }

    @staticmethod
    def _actual_for_target(target: EnrollmentTarget, milestones: list[OperationalMilestone]) -> int:
        target_type = str(_value(target.target_type)).lower()
        matching = []
        for milestone in milestones:
            kind = str(getattr(milestone, "milestone_type", "")).lower()
            status = str(_value(getattr(milestone, "status", "")))
            if target.site_id is not None and milestone.site_id != target.site_id:
                continue
            if target_type in kind or (
                target_type == "enrollment" and status in _ENROLLMENT_ACTUAL_STATUSES
            ) or (
                target_type in {"screening", "recruitment"} and status in _SCREENING_STATUSES
            ):
                matching.append(milestone)
        return len(matching)

    async def study_dashboard(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: User | None = None,
        *,
        now: datetime | None = None,
    ) -> CTMSDashboardResponse:
        """Return an operational study dashboard restricted to the user's scope."""
        scope = self._scope(user)
        self._ensure_study_scope(scope, study_id)
        current = _timestamp(now, now) if now else datetime.now(UTC)
        targets = await self._rows(session, EnrollmentTarget, study_id=study_id, scope=scope)
        milestones = await self._rows(session, OperationalMilestone, study_id=study_id, scope=scope)
        activities = await self._rows(session, MonitoringActivity, study_id=study_id, scope=scope)
        tasks = await self._rows(session, OperationalTask, study_id=study_id, scope=scope)
        contacts = await self._rows(session, OperationalContact, study_id=study_id, scope=scope)
        sites = await self._rows(session, OperationalSite, study_id=study_id, scope=scope)
        activation = await self._rows(session, ActivationAction, study_id=study_id, scope=scope)
        readiness = await self._rows(session, ReadinessCriterion, study_id=study_id, scope=scope)
        study_milestones = await self._rows(session, StudyOperationalMilestone, study_id=study_id, scope=scope)
        profiles = await self._rows(session, OperationalStudy, study_id=study_id, scope=scope)
        projections = await self._projections(session, study_id=study_id, site_id=None, scope=scope)

        target_rows = [target for target in targets if str(_value(target.status)) != "Cancelled"]
        target_totals: dict[str, int] = {}
        for target in target_rows:
            target_type = str(_value(target.target_type))
            target_totals[target_type] = target_totals.get(target_type, 0) + int(target.target_quantity)
        actual_totals: dict[str, int] = {}
        for target_type in target_totals:
            actual_totals[target_type] = sum(
                self._actual_for_target(target, milestones)
                for target in target_rows
                if str(_value(target.target_type)) == target_type
            )
        target_progress = {
            target_type: {
                "target": int(target_totals[target_type]),
                "actual": int(actual_totals[target_type]),
                "variance": int(target_totals[target_type] - actual_totals[target_type]),
            }
            for target_type in target_totals
        }
        readiness_counts = Counter(str(_value(getattr(row, "status", "Open"))) for row in readiness)
        activation_counts = Counter(str(_value(getattr(row, "status", "Open"))) for row in activation)
        site_status_counts = Counter(str(_value(getattr(row, "status", "Not Started"))) for row in sites)
        monitoring_counts = Counter(str(_value(getattr(row, "status", "Planned"))) for row in activities)
        task_counts = Counter(str(_value(getattr(row, "status", "Open"))) for row in tasks)
        milestone_counts = Counter(str(_value(getattr(row, "status", "Planned"))) for row in [*milestones, *study_milestones])
        overdue_tasks = sum(
            1 for task in tasks
            if getattr(task, "due_date", None) is not None
            and _timestamp(task.due_date, current) < current
            and str(_value(task.status)) not in _TERMINAL_TASK_STATUSES
        )
        upcoming_monitoring = sum(
            1 for activity in activities
            if getattr(activity, "planned_date", None) is not None
            and _timestamp(activity.planned_date, current) >= current
            and str(_value(activity.status)) not in _TERMINAL_MONITORING_STATUSES
        )
        required_readiness = [row for row in readiness if getattr(row, "required", True)]
        met_readiness = sum(str(_value(getattr(row, "status", "Open"))) in {"Met", "Waived"} for row in required_readiness)
        profile = profiles[0] if profiles else None
        return CTMSDashboardResponse(
            study_id=study_id,
            operational={
                "enrollment": {"targets": target_progress, "target_count": len(target_rows), "actual": len(milestones), "variance": sum(target.target_quantity for target in target_rows) - len(milestones)},
                "readiness": {"study_status": getattr(profile, "status", None), "criteria": dict(readiness_counts), "required_total": len(required_readiness), "required_met": met_readiness, "completion_percentage": round(met_readiness / len(required_readiness) * 100, 2) if required_readiness else 0.0},
                "activation": {"site_status": dict(site_status_counts), "actions": dict(activation_counts), "active_sites": site_status_counts.get("Active", 0)},
                "monitoring": {"status": dict(monitoring_counts), "upcoming": upcoming_monitoring, "total": len(activities)},
                "tasks": {"status": dict(task_counts), "overdue": overdue_tasks, "total": len(tasks)},
                "milestones": {"status": dict(milestone_counts), "total": len(milestones) + len(study_milestones)},
                "contacts": {"total": len(contacts), "active": sum(str(_value(row.status)) == "Active" for row in contacts)},
            },
            projected_clinical=[self._quality_signal(row, current) for row in projections],
            generated_at=current,
        )

    async def site_dashboard(
        self,
        session: AsyncSession,
        site_id: UUID,
        user: User | None = None,
        *,
        study_id: UUID | None = None,
        now: datetime | None = None,
    ) -> CTMSDashboardResponse:
        """Return an operational site dashboard with no clinical aggregation."""
        scope = self._scope(user)
        if study_id is None:
            for model in (EnrollmentTarget, MonitoringActivity, OperationalTask, OperationalContact, OperationalSite):
                result = await session.execute(select(model).where(model.site_id == site_id).limit(1))
                first = result.scalars().first()
                if first is not None:
                    study_id = first.study_id
                    break
        if study_id is None:
            raise AuthorizationError("Site is outside the requested CTMS scope", {"site_id": str(site_id)})
        self._ensure_site_scope(scope, study_id, site_id)
        current = _timestamp(now, now) if now else datetime.now(UTC)
        targets = await self._rows(session, EnrollmentTarget, study_id=study_id, site_id=site_id, scope=scope)
        milestones = await self._rows(session, OperationalMilestone, study_id=study_id, site_id=site_id, scope=scope)
        activities = await self._rows(session, MonitoringActivity, study_id=study_id, site_id=site_id, scope=scope)
        tasks = await self._rows(session, OperationalTask, study_id=study_id, site_id=site_id, scope=scope)
        contacts = await self._rows(session, OperationalContact, study_id=study_id, site_id=site_id, scope=scope)
        profiles = await self._rows(session, OperationalSite, study_id=study_id, site_id=site_id, scope=scope)
        activation = await self._rows(session, ActivationAction, study_id=study_id, site_id=site_id, scope=scope)
        projections = await self._projections(session, study_id=study_id, site_id=site_id, scope=scope)
        target_rows = [row for row in targets if str(_value(row.status)) != "Cancelled"]
        target = sum(row.target_quantity for row in target_rows)
        actual = len(milestones)
        task_status = Counter(str(_value(row.status)) for row in tasks)
        activity_status = Counter(str(_value(row.status)) for row in activities)
        overdue = sum(1 for row in tasks if row.due_date and _timestamp(row.due_date, current) < current and str(_value(row.status)) not in _TERMINAL_TASK_STATUSES)
        return CTMSDashboardResponse(
            study_id=study_id,
            site_id=site_id,
            operational={
                "enrollment": {"target": target, "actual": actual, "variance": target - actual, "targets": len(target_rows)},
                "activation": {"status": getattr(profiles[0], "status", None) if profiles else None, "monitoring_readiness": getattr(profiles[0], "monitoring_readiness", None) if profiles else None, "actions": dict(Counter(str(_value(row.status)) for row in activation))},
                "monitoring": {"status": dict(activity_status), "total": len(activities)},
                "tasks": {"status": dict(task_status), "assigned": sum(row.owner_id is not None for row in tasks), "overdue": overdue},
                "contacts": {"total": len(contacts), "active": sum(str(_value(row.status)) == "Active" for row in contacts)},
                "milestones": {"total": len(milestones), "status": dict(Counter(str(_value(row.status)) for row in milestones))},
            },
            projected_clinical=[self._quality_signal(row, current) for row in projections],
            generated_at=current,
        )


ctms_dashboard_service = CTMSDashboardService()

__all__ = ["CTMSDashboardService", "ctms_dashboard_service"]
