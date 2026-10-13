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

from app.core.exceptions import ValidationError
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import MonitoringActivity
from app.models.ctms.operational_study import StudyOperationalMilestone
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.work import OperationalTask
from app.schemas.ctms.report import CTMSReportResponse
from app.services.ctms.ctms_dashboard_service import (
    _TERMINAL_MONITORING_STATUSES,
    _TERMINAL_TASK_STATUSES,
    CTMSDashboardService,
    _timestamp,
    _value,
    ctms_dashboard_service,
)
from app.services.ctms.report_catalog import REPORT_CATALOG_BY_KEY


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
        if (
            owner_id is not None
            and getattr(row, "owner_id", getattr(row, "assigned_cra_id", None)) != owner_id
        ):
            return False
        if priority and str(_value(getattr(row, "priority", ""))).lower() != priority.lower():
            return False
        value = getattr(row, date_attr, None)
        category = cls._date_category(
            value, now, terminal=str(_value(getattr(row, "status", ""))) in terminal_statuses
        )
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
            if wanted in {"completed", "complete"} and str(
                _value(getattr(row, "status", ""))
            ) not in {"Completed", "Met"}:
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
            "due_date_category": cls._date_category(
                row.planned_date, now, terminal=status in _TERMINAL_MONITORING_STATUSES
            ),
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
            "due_date_category": cls._date_category(
                row.planning_period_end, now, terminal=status in {"Met", "Cancelled"}
            ),
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
            "due_date_category": cls._date_category(
                row.due_date, now, terminal=status in _TERMINAL_TASK_STATUSES
            ),
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
        rows = await self.dashboard_service._rows(
            session, MonitoringActivity, study_id=study_id, site_id=site_id, scope=scope
        )
        rows = [
            row
            for row in rows
            if self._matches_filters(
                row,
                status=status,
                owner_id=owner_id,
                priority=None,
                due_date=due_date,
                trend=trend,
                date_attr="planned_date",
                terminal_statuses=_TERMINAL_MONITORING_STATUSES,
                now=current,
            )
        ]
        items = [self._monitoring_item(row, current) for row in rows]
        statuses = Counter(item["status"] for item in items)
        return CTMSReportResponse(
            study_id=study_id,
            site_id=site_id,
            report_type="monitoring",
            items=items,
            totals={
                "count": len(items),
                "status": dict(statuses),
                "planned": sum(
                    item["status"] in {"Planned", "Scheduled", "In Progress"} for item in items
                ),
                "completed": statuses.get("Completed", 0),
                "overdue": sum(item["due_date_category"] == "overdue" for item in items),
                "rescheduled": statuses.get("Rescheduled", 0),
                "cancelled": statuses.get("Cancelled", 0),
            },
            generated_at=current,
        )

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
        targets = await self.dashboard_service._rows(
            session, EnrollmentTarget, study_id=study_id, site_id=site_id, scope=scope
        )
        milestones = await self.dashboard_service._rows(
            session, OperationalMilestone, study_id=study_id, site_id=site_id, scope=scope
        )
        targets = [
            row
            for row in targets
            if self._matches_filters(
                row,
                status=status,
                owner_id=owner_id,
                priority=None,
                due_date=due_date,
                trend=trend,
                date_attr="planning_period_end",
                terminal_statuses={"Met", "Cancelled"},
                now=current,
            )
        ]
        items = [self._enrollment_item(row, milestones, current) for row in targets]
        return CTMSReportResponse(
            study_id=study_id,
            site_id=site_id,
            report_type="enrollment",
            items=items,
            totals={
                "count": len(items),
                "target": sum(item["target"] for item in items),
                "actual": sum(item["actual"] for item in items),
                "variance": sum(item["variance"] for item in items),
                "status": dict(Counter(item["status"] for item in items)),
                "trend": self._trend(items),
            },
            generated_at=current,
        )

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
        rows = await self.dashboard_service._rows(
            session, OperationalTask, study_id=study_id, site_id=site_id, scope=scope
        )
        rows = [
            row
            for row in rows
            if self._matches_filters(
                row,
                status=status,
                owner_id=owner_id,
                priority=priority,
                due_date=due_date,
                trend=trend,
                date_attr="due_date",
                terminal_statuses=_TERMINAL_TASK_STATUSES,
                now=current,
            )
        ]
        items = [self._task_item(row, current) for row in rows]
        return CTMSReportResponse(
            study_id=study_id,
            site_id=site_id,
            report_type="tasks",
            items=items,
            totals={
                "count": len(items),
                "owner": dict(Counter(str(item["owner_id"]) for item in items)),
                "status": dict(Counter(item["status"] for item in items)),
                "priority": dict(Counter(item["priority"] for item in items)),
                "due_date": dict(Counter(item["due_date_category"] for item in items)),
                "overdue": sum(item["due_date_category"] == "overdue" for item in items),
            },
            generated_at=current,
        )

    @staticmethod
    def _trend(items: list[dict[str, Any]]) -> dict[str, int]:
        return dict(Counter(str(item.get("due_date_category", "unknown")) for item in items))

    @staticmethod
    def _normalize_slug(value: str) -> str:
        return value.strip().lower().replace("_", "-")

    @staticmethod
    def _projection_item(row: CTMSOperationalProjection, now: datetime) -> dict[str, Any]:
        """Serialize only the already-approved projection payload and provenance."""
        source_timestamp = _timestamp(row.source_timestamp, now)
        return {
            **dict(row.payload_json or {}),
            "projection_id": str(row.id),
            "study_id": str(row.study_id) if row.study_id else None,
            "site_id": str(row.site_id) if row.site_id else None,
            "subject_id": str(row.subject_id) if row.subject_id else None,
            "visit_instance_id": str(row.visit_instance_id) if row.visit_instance_id else None,
            "query_id": str(row.query_id) if row.query_id else None,
            "source_module": row.source_module,
            "source_timestamp": source_timestamp.isoformat() if source_timestamp else None,
            "rule_version": row.rule_version,
            "read_only": True,
            "ownership": "projected",
        }

    async def _projection_rows(
        self,
        session: AsyncSession,
        study_id: UUID,
        user: Any | None,
        *,
        site_id: UUID | None,
        projection_type: str,
    ) -> list[CTMSOperationalProjection]:
        scope = self.dashboard_service._scope(user)
        self.dashboard_service._ensure_study_scope(scope, study_id)
        rows = await self.dashboard_service._rows(
            session,
            CTMSOperationalProjection,
            study_id=study_id,
            site_id=site_id,
            scope=scope,
        )
        return [
            row
            for row in rows
            if str(_value(row.status)).lower() == "current"
            and row.projection_type == projection_type
        ]

    async def _project_management_catalog_report(
        self,
        session: AsyncSession,
        study_id: UUID,
        report_type: str,
        user: Any | None,
        *,
        site_id: UUID | None,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        scope = self.dashboard_service._scope(user)
        self.dashboard_service._ensure_study_scope(scope, study_id)
        tasks = await self.dashboard_service._rows(
            session, OperationalTask, study_id=study_id, site_id=site_id, scope=scope
        )
        milestones = await self.dashboard_service._rows(
            session,
            StudyOperationalMilestone,
            study_id=study_id,
            site_id=site_id,
            scope=scope,
        )

        if report_type == "tasks":
            items = [self._task_item(row, now) for row in tasks]
            return items, {
                "count": len(items),
                "status": dict(Counter(item["status"] for item in items)),
                "overdue": sum(item["due_date_category"] == "overdue" for item in items),
            }
        if report_type == "gantt":
            task_items = [
                {
                    "id": str(row.id),
                    "item_type": "task",
                    "title": row.title,
                    "start_at": self._serialize(row.created_at),
                    "end_at": self._serialize(row.due_date),
                    "status": str(_value(row.status)),
                    "owner_id": self._serialize(row.owner_id),
                }
                for row in tasks
            ]
            milestone_items = [
                {
                    "id": str(row.id),
                    "item_type": "milestone",
                    "title": row.title,
                    "start_at": self._serialize(row.planned_at),
                    "end_at": self._serialize(row.completed_at or row.planned_at),
                    "status": str(_value(row.status)),
                    "owner_id": self._serialize(row.owner_id),
                }
                for row in milestones
            ]
            items = [*task_items, *milestone_items]
            return items, {"count": len(items), "tasks": len(tasks), "milestones": len(milestones)}
        if report_type == "raci-matrix":
            items = [
                {
                    "id": str(row.id),
                    "activity": row.title,
                    "responsible_id": self._serialize(row.owner_id),
                    "accountable_id": None,
                    "consulted_ids": [],
                    "informed_ids": [],
                    "status": str(_value(row.status)),
                }
                for row in tasks
            ]
            return items, {
                "count": len(items),
                "unassigned": sum(row.owner_id is None for row in tasks),
            }
        if report_type == "workload-assessment":
            grouped: dict[str, dict[str, Any]] = {}
            for row in tasks:
                owner = str(row.owner_id) if row.owner_id else "unassigned"
                entry = grouped.setdefault(
                    owner,
                    {
                        "owner_id": self._serialize(row.owner_id),
                        "tasks": 0,
                        "overdue": 0,
                        "status": Counter(),
                    },
                )
                entry["tasks"] += 1
                entry["status"][str(_value(row.status))] += 1
                entry["overdue"] += (
                    self._date_category(
                        row.due_date,
                        now,
                        terminal=str(_value(row.status)) in _TERMINAL_TASK_STATUSES,
                    )
                    == "overdue"
                )
            items = [{**entry, "status": dict(entry["status"])} for entry in grouped.values()]
            return items, {
                "owners": len(items),
                "tasks": len(tasks),
                "overdue": sum(item["overdue"] for item in items),
            }
        if report_type == "deliverables":
            items = [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "deliverable_type": row.milestone_type,
                    "planned_at": self._serialize(row.planned_at),
                    "completed_at": self._serialize(row.completed_at),
                    "owner_id": self._serialize(row.owner_id),
                    "status": str(_value(row.status)),
                }
                for row in milestones
            ]
            return items, {
                "count": len(items),
                "status": dict(Counter(item["status"] for item in items)),
            }
        if report_type == "activity-types":
            activities = await self.dashboard_service._rows(
                session,
                MonitoringActivity,
                study_id=study_id,
                site_id=site_id,
                scope=scope,
            )
            counts = Counter(row.activity_type for row in activities)
            items = [
                {"activity_type": activity_type, "count": count}
                for activity_type, count in sorted(counts.items())
            ]
            return items, {"count": len(activities), "types": len(items)}
        raise ValidationError("Unsupported CTMS report type", {"report_type": report_type})

    @staticmethod
    def _query_matches(report_type: str, item: dict[str, Any]) -> bool:
        query_type = str(item.get("query_type") or "").lower()
        summary = str(item.get("summary") or "").lower()
        searchable = f"{query_type} {summary}"
        if report_type in {"all-query-details", "query-aging-summary"}:
            return True
        if report_type == "manual-query-details":
            return query_type == "manual"
        if report_type == "system-query-details":
            return query_type in {"system", "automatic", "auto"}
        tokens = {
            "pd-queries": ("protocol deviation", "pd"),
            "trip-report-queries": ("trip report",),
            "ic-tracking-log-queries": ("ic tracking", "informed consent"),
            "action-item-queries": ("action item",),
        }
        return any(token in searchable for token in tokens.get(report_type, ()))

    @staticmethod
    def _opened_at(item: dict[str, Any]) -> datetime | None:
        raw = item.get("opened_at")
        if not raw:
            return None
        if isinstance(raw, datetime):
            return _timestamp(raw, datetime.now(UTC))
        try:
            return _timestamp(
                datetime.fromisoformat(str(raw).replace("Z", "+00:00")), datetime.now(UTC)
            )
        except ValueError:
            return None

    async def catalog_report(
        self,
        session: AsyncSession,
        study_id: UUID,
        category: str,
        report_type: str,
        user: Any | None = None,
        *,
        site_id: UUID | None = None,
        now: datetime | None = None,
    ) -> CTMSReportResponse:
        """Build a report from CTMS data or approved minimized projections."""
        normalized_category = self._normalize_slug(category)
        normalized_type = self._normalize_slug(report_type)
        definition = REPORT_CATALOG_BY_KEY.get((normalized_category, normalized_type))
        if definition is None:
            raise ValidationError(
                "Unsupported CTMS report",
                {"category": category, "report_type": report_type},
            )
        current = _timestamp(now, now) if now else datetime.now(UTC)
        if normalized_category == "project-management":
            items, totals = await self._project_management_catalog_report(
                session,
                study_id,
                normalized_type,
                user,
                site_id=site_id,
                now=current,
            )
        elif normalized_category == "crf":
            rows = await self._projection_rows(
                session,
                study_id,
                user,
                site_id=site_id,
                projection_type="data_quality_signal",
            )
            items = [self._projection_item(row, current) for row in rows]
            token = normalized_type.removesuffix("-summary").removesuffix("-status")
            if token not in {"", "status"}:
                items = [
                    item for item in items if token in str(item.get("signal_type") or "").lower()
                ]
            totals = {
                "count": len(items),
                "signal_type": dict(
                    Counter(str(item.get("signal_type") or "unknown") for item in items)
                ),
            }
        else:
            rows = await self._projection_rows(
                session,
                study_id,
                user,
                site_id=site_id,
                projection_type="query_summary",
            )
            items = [self._projection_item(row, current) for row in rows]
            items = [item for item in items if self._query_matches(normalized_type, item)]
            aging = Counter()
            for item in items:
                opened_at = self._opened_at(item)
                age_days = max(0, (current - opened_at).days) if opened_at else None
                bucket = None
                if age_days is not None:
                    bucket = (
                        "0-7"
                        if age_days <= 7
                        else "8-14"
                        if age_days <= 14
                        else "15-30"
                        if age_days <= 30
                        else "31+"
                    )
                    aging[bucket] += 1
                item["age_days"] = age_days
                item["age_bucket"] = bucket
            totals = {
                "count": len(items),
                "status": dict(Counter(str(item.get("status") or "unknown") for item in items)),
                "age_bucket": dict(aging),
            }
        return CTMSReportResponse(
            study_id=study_id,
            site_id=site_id,
            category=normalized_category,
            report_type=normalized_type,
            label=definition.label,
            data_source=definition.data_source,
            items=items,
            totals=totals,
            generated_at=current,
        )

    async def report(
        self,
        session: AsyncSession,
        study_id: UUID,
        report_type: str,
        user: Any | None = None,
        **filters: Any,
    ) -> CTMSReportResponse:
        normalized = report_type.lower().replace("_", "-")
        if normalized == "monitoring":
            return await self.monitoring_report(session, study_id, user, **filters)
        if normalized == "enrollment":
            return await self.enrollment_report(session, study_id, user, **filters)
        if normalized in {"tasks", "task"}:
            return await self.task_report(session, study_id, user, **filters)
        raise ValidationError("Unsupported CTMS report type", {"report_type": report_type})


ctms_report_service = CTMSReportService()

__all__ = ["CTMSReportService", "ctms_report_service"]
