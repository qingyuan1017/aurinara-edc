"""Scope-aware CTMS operational reports.

Report rows are built from CTMS operational tables and approved quality
projections only.  Clinical EDC tables are intentionally not queried.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import MonitoringActivity
from app.models.ctms.work import OperationalTask
from app.schemas.ctms.report import CTMSReportResponse
from app.services.ctms_dashboard_service import (
    _TERMINAL_MONITORING_STATUSES,
    _TERMINAL_TASK_STATUSES,
    CTMSDashboardService,
    _timestamp,
    _value,
    ctms_dashboard_service,
)


class CTMSReportService:
    """Build filtered monitoring, enrollment, and task reports."""

    def __init__(self, dashboard_service: CTMSDashboardService | None = None) -> None:
        self.dashboard_service = dashboard_service or ctms_dashboard_service

    @staticmethod
    def _date_category(value: datetime | None, now: datetime, *, terminal: bool = False) -> str:
        if value is None:
            return "no_due_date"
        value = _timestamp(value, now)
        if value < now and not terminal:
            return "overdue"
        if value.date() == now.date():
            return "today"
        return "upcoming"

    @classmethod
    def _matches_filters(
        cls,
        row: Any,
        *,
        status: str | None,
        owner_id: UUID | None,
        priority: str | None,
        due_date: str | None,
        trend: str | None,
        date_attr: str,
        terminal_statuses: set[str],
        now: datetime,
    ) -> bool:
        if status and str(_value(getattr(row, "status", ""))).lower() != status.lower():
            return False
        if owner_id is not None and getattr(row, "owner_id", getattr(row, "assigned_cra_id", None)) != owner_id:
            return False
        if priority and str(_value(getattr(row, "priority", ""))).lower() != priority.lower():
            return False
        value = getattr(row, date_attr, None)
        category = cls._date_category(value, now, terminal=str(_value(getattr(row, "status", ""))) in terminal_statuses)
        if due_date and due_date.lower() not in {category, category.replace("_", "-"), "all"}:
            return False
        if trend:
            wanted = trend.lower().replace("-", "_")
            if wanted in {"overdue", "late"} and category != "overdue":
                return False
            if wanted in {"upcoming", "planned"} and category != "upcoming":
                return False
            if wanted in {"today", "due_today"} and category != "today":
                return False
            if wanted in {"completed", "complete"} and str(_value(getattr(row, "status", ""))) not in {"Completed", "Met"}:
                return False
        return True

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return _value(value)

    @classmethod
    def _monitoring_item(cls, row: MonitoringActivity, now: datetime) -> dict[str, Any]:
        status = str(_value(row.status))
        return {
            "id": str(row.id),
            "study_id": str(row.study_id),
            "site_id": str(row.site_id) if row.site_id else None,
            "activity_type": row.activity_type,
            "planned_date": cls._serialize(row.planned_date),
            "assigned_cra_id": cls._serialize(row.assigned_cra_id),
            "owner_id": cls._serialize(row.assigned_cra_id),
            "status": status,
            "due_date_category": cls._date_category(row.planned_date, now, terminal=status in _TERMINAL_MONITORING_STATUSES),
            "edc_visit_instance_id": cls._serialize(row.edc_visit_instance_id),
            "operational_only": True,
        }

    @classmethod
    def _enrollment_item(
        cls, row: EnrollmentTarget, milestones: list[OperationalMilestone], now: datetime
    ) -> dict[str, Any]:
        actual = CTMSDashboardService._actual_for_target(row, milestones)
        status = str(_value(row.status))
        return {
            "id": str(row.id),
            "study_id": str(row.study_id),
            "site_id": str(row.site_id) if row.site_id else None,
            "target_type": str(_value(row.target_type)),
            "target": row.target_quantity,
            "actual": actual,
            "variance": row.target_quantity - actual,
            "status": status,
            "owner_id": cls._serialize(row.owner_id),
            "planning_period_start": cls._serialize(row.planning_period_start),
            "planning_period_end": cls._serialize(row.planning_period_end),
            "due_date_category": cls._date_category(row.planning_period_end, now, terminal=status in {"Met", "Cancelled"}),
            "operational_only": True,
        }

    @classmethod
    def _task_item(cls, row: OperationalTask, now: datetime) -> dict[str, Any]:
        status = str(_value(row.status))
        return {
            "id": str(row.id),
            "study_id": str(row.study_id),
            "site_id": str(row.site_id) if row.site_id else None,
            "title": row.title,
            "owner_id": cls._serialize(row.owner_id),
            "priority": str(_value(row.priority)),
            "status": status,
            "due_date": cls._serialize(row.due_date),
            "due_date_category": cls._date_category(row.due_date, now, terminal=status in _TERMINAL_TASK_STATUSES),
            "query_id": cls._serialize(row.query_id),
            "operational_only": True,
        }

    async def monitoring_report(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: Any | None = None,
        *,
        site_id: UUID | None = None,
        status: str | None = None,
        owner_id: UUID | None = None,
        due_date: str | None = None,
        trend: str | None = None,
        now: datetime | None = None,
    ) -> CTMSReportResponse:
        current = _timestamp(now, now) if now else datetime.now(UTC)
        scope = self.dashboard_service._scope(user)
        self.dashboard_service._ensure_study_scope(scope, study_id)
        rows = await self.dashboard_service._rows(session, MonitoringActivity, study_id=study_id, site_id=site_id, scope=scope)
        rows = [row for row in rows if self._matches_filters(row, status=status, owner_id=owner_id, priority=None, due_date=due_date, trend=trend, date_attr="planned_date", terminal_statuses=_TERMINAL_MONITORING_STATUSES, now=current)]
        items = [self._monitoring_item(row, current) for row in rows]
        statuses = Counter(item["status"] for item in items)
        return CTMSReportResponse(study_id=study_id, site_id=site_id, report_type="monitoring", items=items, totals={"count": len(items), "status": dict(statuses), "planned": sum(item["status"] in {"Planned", "Scheduled", "In Progress"} for item in items), "completed": statuses.get("Completed", 0), "overdue": sum(item["due_date_category"] == "overdue" for item in items), "rescheduled": statuses.get("Rescheduled", 0), "cancelled": statuses.get("Cancelled", 0)}, generated_at=current)

    async def enrollment_report(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: Any | None = None,
        *,
        site_id: UUID | None = None,
        status: str | None = None,
        owner_id: UUID | None = None,
        due_date: str | None = None,
        trend: str | None = None,
        now: datetime | None = None,
    ) -> CTMSReportResponse:
        current = _timestamp(now, now) if now else datetime.now(UTC)
        scope = self.dashboard_service._scope(user)
        self.dashboard_service._ensure_study_scope(scope, study_id)
        targets = await self.dashboard_service._rows(session, EnrollmentTarget, study_id=study_id, site_id=site_id, scope=scope)
        milestones = await self.dashboard_service._rows(session, OperationalMilestone, study_id=study_id, site_id=site_id, scope=scope)
        targets = [row for row in targets if self._matches_filters(row, status=status, owner_id=owner_id, priority=None, due_date=due_date, trend=trend, date_attr="planning_period_end", terminal_statuses={"Met", "Cancelled"}, now=current)]
        items = [self._enrollment_item(row, milestones, current) for row in targets]
        return CTMSReportResponse(study_id=study_id, site_id=site_id, report_type="enrollment", items=items, totals={"count": len(items), "target": sum(item["target"] for item in items), "actual": sum(item["actual"] for item in items), "variance": sum(item["variance"] for item in items), "status": dict(Counter(item["status"] for item in items)), "trend": self._trend(items)}, generated_at=current)

    async def task_report(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: Any | None = None,
        *,
        site_id: UUID | None = None,
        status: str | None = None,
        owner_id: UUID | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        trend: str | None = None,
        now: datetime | None = None,
    ) -> CTMSReportResponse:
        current = _timestamp(now, now) if now else datetime.now(UTC)
        scope = self.dashboard_service._scope(user)
        self.dashboard_service._ensure_study_scope(scope, study_id)
        rows = await self.dashboard_service._rows(session, OperationalTask, study_id=study_id, site_id=site_id, scope=scope)
        rows = [row for row in rows if self._matches_filters(row, status=status, owner_id=owner_id, priority=priority, due_date=due_date, trend=trend, date_attr="due_date", terminal_statuses=_TERMINAL_TASK_STATUSES, now=current)]
        items = [self._task_item(row, current) for row in rows]
        return CTMSReportResponse(study_id=study_id, site_id=site_id, report_type="tasks", items=items, totals={"count": len(items), "owner": dict(Counter(str(item["owner_id"]) for item in items)), "status": dict(Counter(item["status"] for item in items)), "priority": dict(Counter(item["priority"] for item in items)), "due_date": dict(Counter(item["due_date_category"] for item in items)), "overdue": sum(item["due_date_category"] == "overdue" for item in items)}, generated_at=current)

    @staticmethod
    def _trend(items: list[dict[str, Any]]) -> dict[str, int]:
        return dict(Counter(str(item.get("due_date_category", "unknown")) for item in items))

    async def report(self, session: AsyncSession, study_id: UUID, report_type: str, user: Any | None = None, **filters: Any) -> CTMSReportResponse:
        normalized = report_type.lower().replace("_", "-")
        if normalized == "monitoring":
            return await self.monitoring_report(session, study_id, user, **filters)
        if normalized == "enrollment":
            return await self.enrollment_report(session, study_id, user, **filters)
        if normalized in {"tasks", "task"}:
            return await self.task_report(session, study_id, user, **filters)
        from app.core.exceptions import ValidationError
        raise ValidationError("Unsupported CTMS report type", {"report_type": report_type})


ctms_report_service = CTMSReportService()

__all__ = ["CTMSReportService", "ctms_report_service"]
