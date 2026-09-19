"""Property 17: CTMS dashboards and reports are scope-consistent.

Feature: ctms-integration, Property 17: Operational dashboards and reports are scope-consistent
**Validates: Requirements 5.15, 8.5-8.7, 10.11, 11.12, 13.1-13.7**

The test uses deterministic in-memory records and an async query fake.  It
therefore exercises the task 5.1 dashboard/report services without a database,
network, clock, or external service dependency.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.ctms_dashboard_service import (
    _TERMINAL_MONITORING_STATUSES,
    _TERMINAL_TASK_STATUSES,
    CTMSDashboardService,
)
from app.services.ctms_report_service import CTMSReportService

NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
READ_PERMISSION = "ctms.operational_data_read"
STUDY_STATUSES = ("Draft", "Planning", "Ready", "Active", "Suspended", "Closed")
SITE_STATUSES = ("Not Started", "In Progress", "Ready for Activation", "Active", "Suspended", "Closed")
TARGET_TYPES = ("Recruitment", "Screening", "Enrollment")
TARGET_STATUSES = ("Draft", "Active", "Met", "Expired", "Cancelled")
SUBJECT_STATUSES = (
    "Screening",
    "Screen Failed",
    "Enrolled",
    "Randomized",
    "On Treatment",
    "Completed",
    "Early Terminated",
    "Lost to Follow-up",
    "Withdrawn",
)
ACTIVITY_STATUSES = ("Planned", "Scheduled", "In Progress", "Completed", "Rescheduled", "Cancelled")
TASK_STATUSES = ("Open", "In Progress", "Blocked", "Completed", "Cancelled", "Archived")
TASK_PRIORITIES = ("Low", "Normal", "High", "Urgent")
CONTACT_STATUSES = ("Active", "Inactive", "Archived")
DATE_FILTERS = (None, "overdue", "today", "upcoming", "no_due_date")
TREND_FILTERS = (None, "overdue", "upcoming", "today", "completed")


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _InMemorySession:
    """Minimal deterministic async session for the service read paths."""

    def __init__(self, rows_by_model: dict[type, list[Any]]) -> None:
        self.rows_by_model = rows_by_model

    async def execute(self, statement: Any) -> _FakeResult:
        model = statement.column_descriptions[0]["entity"]
        rows = self.rows_by_model.get(model, [])
        parameters = statement.compile().params
        if parameters:
            study_id = next(iter(parameters.values()))
            rows = [row for row in rows if row.study_id == study_id]
        return _FakeResult(rows)


@st.composite
def _record_specs(draw: st.DrawFn, *, kind: str) -> list[dict[str, Any]]:
    """Generate compact record descriptions that are materialized per scenario."""
    specs: list[dict[str, Any]] = []
    for _ in range(draw(st.integers(min_value=0, max_value=5))):
        spec: dict[str, Any] = {
            "study_index": draw(st.integers(min_value=0, max_value=1)),
            "site_index": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1))),
        }
        if kind == "target":
            spec.update(
                target_type=draw(st.sampled_from(TARGET_TYPES)),
                target_quantity=draw(st.integers(min_value=0, max_value=20)),
                status=draw(st.sampled_from(TARGET_STATUSES)),
                end_offset=draw(st.integers(min_value=-2, max_value=2)),
                owner_index=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1))),
            )
        elif kind == "milestone":
            spec.update(
                milestone_type=draw(st.sampled_from(("Recruitment", "Screening", "Enrollment", "Other"))),
                status=draw(st.sampled_from(SUBJECT_STATUSES)),
                date_offset=draw(st.integers(min_value=-2, max_value=2)),
            )
        elif kind == "activity":
            spec.update(
                status=draw(st.sampled_from(ACTIVITY_STATUSES)),
                date_offset=draw(st.integers(min_value=-2, max_value=2)),
                owner_index=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1))),
            )
        elif kind == "task":
            spec.update(
                status=draw(st.sampled_from(TASK_STATUSES)),
                priority=draw(st.sampled_from(TASK_PRIORITIES)),
                date_offset=draw(st.one_of(st.none(), st.integers(min_value=-2, max_value=2))),
                owner_index=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1))),
            )
        elif kind == "contact":
            spec["status"] = draw(st.sampled_from(CONTACT_STATUSES))
        elif kind == "site":
            spec["status"] = draw(st.sampled_from(SITE_STATUSES))
        elif kind == "activation":
            spec["status"] = draw(st.sampled_from(("Open", "Completed", "Cancelled")))
        elif kind == "readiness":
            spec.update(
                status=draw(st.sampled_from(("Open", "Met", "Waived"))),
                required=draw(st.booleans()),
            )
        elif kind in {"milestone_summary", "study"}:
            spec["status"] = draw(st.sampled_from(("Planned", "Completed", "Open")))
        elif kind == "projection":
            spec.update(
                status=draw(st.sampled_from(("current", "stale"))),
                source_offset=draw(st.integers(min_value=0, max_value=48)),
                value=draw(st.integers(min_value=0, max_value=100)),
            )
        specs.append(spec)
    return specs


@st.composite
def _scenario(draw: st.DrawFn) -> dict[str, Any]:
    study_ids = [draw(st.uuids(version=4)), draw(st.uuids(version=4))]
    site_ids = [
        [draw(st.uuids(version=4)), draw(st.uuids(version=4))],
        [draw(st.uuids(version=4)), draw(st.uuids(version=4))],
    ]
    owner_ids = [draw(st.uuids(version=4)), draw(st.uuids(version=4))]
    scope_kind = draw(st.sampled_from(("system", "study", "site")))
    scope_site_index = draw(st.integers(min_value=0, max_value=1))
    if scope_kind == "system":
        scope = AuthorizationScope(grants=[PermissionGrant(permission_code=READ_PERMISSION)])
    elif scope_kind == "study":
        scope = AuthorizationScope(
            grants=[PermissionGrant(permission_code=READ_PERMISSION, study_id=study_ids[0])]
        )
    else:
        scope = AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code=READ_PERMISSION,
                    study_id=study_ids[0],
                    site_id=site_ids[0][scope_site_index],
                )
            ]
        )

    report_type = draw(st.sampled_from(("monitoring", "enrollment", "tasks")))
    report_site_index = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1)))
    filters = {
        "site_index": report_site_index,
        "status": draw(st.one_of(st.none(), st.sampled_from(TASK_STATUSES + ACTIVITY_STATUSES + TARGET_STATUSES))),
        "owner_index": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1))),
        "priority": draw(st.one_of(st.none(), st.sampled_from(TASK_PRIORITIES))),
        "due_date": draw(st.sampled_from(DATE_FILTERS)),
        "trend": draw(st.sampled_from(TREND_FILTERS)),
    }
    return {
        "study_ids": study_ids,
        "site_ids": site_ids,
        "owner_ids": owner_ids,
        "scope": scope,
        "scope_kind": scope_kind,
        "scope_site_index": scope_site_index,
        "report_type": report_type,
        "report_site_index": report_site_index,
        "filters": filters,
    }


def _build_scenario(raw: dict[str, Any], specs: dict[str, list[dict[str, Any]]]) -> tuple[dict[type, list[Any]], dict[str, Any]]:
    study_ids: list[UUID] = raw["study_ids"]
    site_ids: list[list[UUID]] = raw["site_ids"]
    owner_ids: list[UUID] = raw["owner_ids"]
    rows: dict[type, list[Any]] = {}

    def identity(spec: dict[str, Any]) -> tuple[UUID, UUID | None]:
        study_index = spec["study_index"]
        site_index = spec["site_index"]
        site_id = None if site_index is None else site_ids[study_index][site_index]
        return study_ids[study_index], site_id

    def base(spec: dict[str, Any]) -> dict[str, Any]:
        study_id, site_id = identity(spec)
        return {
            "id": uuid4(),
            "study_id": study_id,
            "site_id": site_id,
            "retention_state": "active",
            "deleted_at": None,
        }

    targets: list[Any] = []
    for spec in specs["target"]:
        values = base(spec)
        values.update(
            target_type=spec["target_type"],
            target_quantity=spec["target_quantity"],
            status=spec["status"],
            planning_period_start=NOW - timedelta(days=5),
            planning_period_end=NOW + timedelta(days=spec["end_offset"]),
            owner_id=None if spec["owner_index"] is None else owner_ids[spec["owner_index"]],
        )
        targets.append(SimpleNamespace(**values))

    milestones: list[Any] = []
    for spec in specs["milestone"]:
        values = base(spec)
        values.update(
            subject_id=uuid4(),
            milestone_type=spec["milestone_type"],
            status=spec["status"],
            milestone_date=NOW + timedelta(days=spec["date_offset"]),
        )
        milestones.append(SimpleNamespace(**values))

    activities: list[Any] = []
    for spec in specs["activity"]:
        values = base(spec)
        values.update(
            status=spec["status"],
            planned_date=NOW + timedelta(days=spec["date_offset"]),
            assigned_cra_id=None if spec["owner_index"] is None else owner_ids[spec["owner_index"]],
            activity_type="Routine Monitoring",
            edc_visit_instance_id=None,
        )
        activities.append(SimpleNamespace(**values))

    tasks: list[Any] = []
    for spec in specs["task"]:
        values = base(spec)
        values.update(
            status=spec["status"],
            priority=spec["priority"],
            due_date=None if spec["date_offset"] is None else NOW + timedelta(days=spec["date_offset"]),
            owner_id=None if spec["owner_index"] is None else owner_ids[spec["owner_index"]],
            title="Generated task",
            query_id=None,
        )
        tasks.append(SimpleNamespace(**values))

    def simple_rows(kind: str, model: type, extra: Any) -> None:
        rows[model] = []
        for spec in specs[kind]:
            values = base(spec)
            values.update(extra(spec))
            rows[model].append(SimpleNamespace(**values))

    simple_rows("contact", OperationalContact, lambda spec: {"status": spec["status"], "owner_id": None, "name": "Contact"})
    simple_rows("site", OperationalSite, lambda spec: {"status": spec["status"], "monitoring_readiness": True})
    simple_rows("activation", ActivationAction, lambda spec: {"status": spec["status"], "action_type": "Contract"})
    simple_rows("readiness", ReadinessCriterion, lambda spec: {"status": spec["status"], "required": spec["required"]})
    simple_rows("milestone_summary", StudyOperationalMilestone, lambda spec: {"status": spec["status"], "title": "Study milestone"})
    simple_rows("study", OperationalStudy, lambda spec: {"status": spec["status"]})

    projections: list[Any] = []
    for spec in specs["projection"]:
        values = base(spec)
        values.update(
            projection_type="data_quality_signal",
            source_module="EDC",
            source_timestamp=NOW - timedelta(hours=spec["source_offset"]),
            rule_version=1,
            payload_json={"signal_type": "SDV Progress", "value": spec["value"]},
            status=spec["status"],
        )
        projections.append(SimpleNamespace(**values))

    rows.update(
        {
            EnrollmentTarget: targets,
            OperationalMilestone: milestones,
            MonitoringActivity: activities,
            OperationalTask: tasks,
            CTMSOperationalProjection: projections,
        }
    )
    return rows, {"targets": targets, "milestones": milestones, "activities": activities, "tasks": tasks, "projections": projections}


def _in_scope(row: Any, study_id: UUID, scope: AuthorizationScope, report_site_id: UUID | None = None) -> bool:
    if row.study_id != study_id or getattr(row, "deleted_at", None) is not None or getattr(row, "retention_state", "active") == "soft_deleted":
        return False
    if report_site_id is not None and getattr(row, "site_id", None) != report_site_id:
        return False
    return scope.has_permission(READ_PERMISSION, study_id=row.study_id, site_id=getattr(row, "site_id", None))


def _category(value: datetime | None, status: str, terminal: set[str]) -> str:
    if value is None:
        return "no_due_date"
    if value < NOW and status not in terminal:
        return "overdue"
    if value.date() == NOW.date():
        return "today"
    return "upcoming"


def _matches(row: Any, filters: dict[str, Any], *, date_attr: str, terminal: set[str], owner_attr: str) -> bool:
    status = str(getattr(row, "status", ""))
    if filters["status"] and status.lower() != filters["status"].lower():
        return False
    owner_id = getattr(row, owner_attr, None)
    if filters["owner_index"] is not None and owner_id != filters["owner_ids"][filters["owner_index"]]:
        return False
    if filters["priority"] and str(getattr(row, "priority", "")).lower() != filters["priority"].lower():
        return False
    category = _category(getattr(row, date_attr, None), status, terminal)
    due_date = filters["due_date"]
    if due_date and due_date not in {category, category.replace("_", "-"), "all"}:
        return False
    trend = filters["trend"]
    if trend == "overdue" and category != "overdue":
        return False
    if trend == "upcoming" and category != "upcoming":
        return False
    if trend == "today" and category != "today":
        return False
    return not (trend == "completed" and status not in {"Completed", "Met"})


def _expected_enrollment_item(target: Any, milestones: list[Any]) -> dict[str, Any]:
    status = str(target.status)
    matching = []
    target_type = str(target.target_type).lower()
    for milestone in milestones:
        if target.site_id is not None and milestone.site_id != target.site_id:
            continue
        milestone_type = str(milestone.milestone_type).lower()
        if target_type in milestone_type or (
            target_type == "enrollment" and milestone.status in {"Enrolled", "Randomized", "On Treatment", "Completed", "Early Terminated", "Lost to Follow-up", "Withdrawn"}
        ) or (
            target_type in {"screening", "recruitment"} and milestone.status in {"Screening", "Screen Failed"}
        ):
            matching.append(milestone)
    return {
        "id": str(target.id),
        "study_id": str(target.study_id),
        "site_id": str(target.site_id) if target.site_id else None,
        "target_type": str(target.target_type),
        "target": target.target_quantity,
        "actual": len(matching),
        "variance": target.target_quantity - len(matching),
        "status": status,
        "owner_id": str(target.owner_id) if target.owner_id else None,
        "planning_period_start": target.planning_period_start.isoformat(),
        "planning_period_end": target.planning_period_end.isoformat(),
        "due_date_category": _category(target.planning_period_end, status, {"Met", "Cancelled"}),
        "operational_only": True,
    }


def _expected_monitoring_item(row: Any) -> dict[str, Any]:
    status = str(row.status)
    return {
        "id": str(row.id),
        "study_id": str(row.study_id),
        "site_id": str(row.site_id) if row.site_id else None,
        "activity_type": row.activity_type,
        "planned_date": row.planned_date.isoformat(),
        "assigned_cra_id": str(row.assigned_cra_id) if row.assigned_cra_id else None,
        "owner_id": str(row.assigned_cra_id) if row.assigned_cra_id else None,
        "status": status,
        "due_date_category": _category(row.planned_date, status, set(_TERMINAL_MONITORING_STATUSES)),
        "edc_visit_instance_id": None,
        "operational_only": True,
    }


def _expected_task_item(row: Any) -> dict[str, Any]:
    status = str(row.status)
    return {
        "id": str(row.id),
        "study_id": str(row.study_id),
        "site_id": str(row.site_id) if row.site_id else None,
        "title": row.title,
        "owner_id": str(row.owner_id) if row.owner_id else None,
        "priority": str(row.priority),
        "status": status,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "due_date_category": _category(row.due_date, status, set(_TERMINAL_TASK_STATUSES)),
        "query_id": None,
        "operational_only": True,
    }


@st.composite
def _case(draw: st.DrawFn) -> dict[str, Any]:
    raw = draw(_scenario())
    specs = {
        kind: draw(_record_specs(kind=kind))
        for kind in ("target", "milestone", "activity", "task", "contact", "site", "activation", "readiness", "milestone_summary", "study", "projection")
    }
    rows, records = _build_scenario(raw, specs)
    records.update(
        {
            "contacts": rows[OperationalContact],
            "sites": rows[OperationalSite],
            "activation": rows[ActivationAction],
            "readiness": rows[ReadinessCriterion],
            "study_milestones": rows[StudyOperationalMilestone],
            "profiles": rows[OperationalStudy],
        }
    )
    raw["filters"]["owner_ids"] = raw["owner_ids"]
    raw["records"] = records
    raw["rows"] = rows
    return raw


@settings(max_examples=100, deadline=None)
@given(case=_case())
@pytest.mark.asyncio
async def test_operational_dashboards_and_reports_are_scope_consistent(case: dict[str, Any]) -> None:
    """Scoped dashboard/report outputs match independent in-scope calculations."""
    study_id = case["study_ids"][0]
    scope: AuthorizationScope = case["scope"]
    user = SimpleNamespace(authorization_scope=scope)
    session = _InMemorySession(case["rows"])
    dashboard_service = CTMSDashboardService()
    report_service = CTMSReportService(dashboard_service)
    records = case["records"]

    dashboard = await dashboard_service.study_dashboard(session, study_id, user, now=NOW)
    def in_scope(rows: list[Any]) -> list[Any]:
        return [row for row in rows if _in_scope(row, study_id, scope)]

    targets = [row for row in in_scope(records["targets"]) if row.status != "Cancelled"]
    milestones = in_scope(records["milestones"])
    activities = in_scope(records["activities"])
    tasks = in_scope(records["tasks"])
    contacts = in_scope(records["contacts"])
    sites = in_scope(case["rows"][OperationalSite])
    activation = in_scope(case["rows"][ActivationAction])
    readiness = in_scope(case["rows"][ReadinessCriterion])
    study_milestones = in_scope(case["rows"][StudyOperationalMilestone])
    profiles = in_scope(case["rows"][OperationalStudy])

    target_types = {str(row.target_type) for row in targets}
    target_progress = {}
    for target_type in target_types:
        matching_targets = [row for row in targets if str(row.target_type) == target_type]
        actual = sum(
            len(
                [
                    milestone
                    for milestone in milestones
                    if (target.site_id is None or milestone.site_id == target.site_id)
                    and (
                        str(target.target_type).lower() in str(milestone.milestone_type).lower()
                        or (str(target.target_type).lower() == "enrollment" and milestone.status in SUBJECT_STATUSES[2:])
                        or (str(target.target_type).lower() in {"screening", "recruitment"} and milestone.status in SUBJECT_STATUSES[:2])
                    )
                ]
            )
            for target in matching_targets
        )
        total = sum(row.target_quantity for row in matching_targets)
        target_progress[target_type] = {"target": total, "actual": actual, "variance": total - actual}

    required_readiness = [row for row in readiness if row.required]
    readiness_counts = Counter(str(row.status) for row in readiness)
    site_status_counts = Counter(str(row.status) for row in sites)
    activation_counts = Counter(str(row.status) for row in activation)
    activity_counts = Counter(str(row.status) for row in activities)
    task_counts = Counter(str(row.status) for row in tasks)
    milestone_counts = Counter(str(row.status) for row in [*milestones, *study_milestones])
    expected_dashboard = {
        "enrollment": {
            "targets": target_progress,
            "target_count": len(targets),
            "actual": len(milestones),
            "variance": sum(row.target_quantity for row in targets) - len(milestones),
        },
        "readiness": {
            "study_status": profiles[0].status if profiles else None,
            "criteria": dict(readiness_counts),
            "required_total": len(required_readiness),
            "required_met": sum(row.status in {"Met", "Waived"} for row in required_readiness),
            "completion_percentage": round(sum(row.status in {"Met", "Waived"} for row in required_readiness) / len(required_readiness) * 100, 2) if required_readiness else 0.0,
        },
        "activation": {"site_status": dict(site_status_counts), "actions": dict(activation_counts), "active_sites": site_status_counts.get("Active", 0)},
        "monitoring": {"status": dict(activity_counts), "upcoming": sum(row.planned_date >= NOW and row.status not in _TERMINAL_MONITORING_STATUSES for row in activities), "total": len(activities)},
        "tasks": {"status": dict(task_counts), "overdue": sum(row.due_date is not None and row.due_date < NOW and row.status not in _TERMINAL_TASK_STATUSES for row in tasks), "total": len(tasks)},
        "milestones": {"status": dict(milestone_counts), "total": len(milestones) + len(study_milestones)},
        "contacts": {"total": len(contacts), "active": sum(row.status == "Active" for row in contacts)},
    }
    assert dashboard.operational == expected_dashboard
    assert all(
        signal["read_only"]
        and signal["ownership"] == "projected"
        and signal["source_module"] == "EDC"
        and signal["source_timestamp"] is not None
        and signal["freshness"] in {"fresh", "stale"}
        for signal in dashboard.projected_clinical
    )
    assert {signal["projection_id"] for signal in dashboard.projected_clinical} == {
        str(row.id) for row in in_scope(records["projections"]) if row.status == "current"
    }

    report_site_id = None if case["report_site_index"] is None else case["site_ids"][0][case["report_site_index"]]
    filters = case["filters"]
    filters = {**filters, "site_index": case["report_site_index"]}
    common = {"site_id": report_site_id, "now": NOW}
    if case["report_type"] == "monitoring":
        report = await report_service.monitoring_report(session, study_id, user, **common, status=filters["status"], owner_id=None if filters["owner_index"] is None else case["owner_ids"][filters["owner_index"]], due_date=filters["due_date"], trend=filters["trend"])
        expected_rows = [row for row in in_scope(records["activities"]) if (report_site_id is None or row.site_id == report_site_id) and _matches(row, {**filters, "priority": None, "owner_ids": case["owner_ids"]}, date_attr="planned_date", terminal=set(_TERMINAL_MONITORING_STATUSES), owner_attr="assigned_cra_id")]
        expected_items = [_expected_monitoring_item(row) for row in expected_rows]
        expected_totals = {"count": len(expected_items), "status": dict(Counter(item["status"] for item in expected_items)), "planned": sum(item["status"] in {"Planned", "Scheduled", "In Progress"} for item in expected_items), "completed": sum(item["status"] == "Completed" for item in expected_items), "overdue": sum(item["due_date_category"] == "overdue" for item in expected_items), "rescheduled": sum(item["status"] == "Rescheduled" for item in expected_items), "cancelled": sum(item["status"] == "Cancelled" for item in expected_items)}
    elif case["report_type"] == "enrollment":
        report = await report_service.enrollment_report(session, study_id, user, **common, status=filters["status"], owner_id=None if filters["owner_index"] is None else case["owner_ids"][filters["owner_index"]], due_date=filters["due_date"], trend=filters["trend"])
        expected_targets = [row for row in in_scope(records["targets"]) if (report_site_id is None or row.site_id == report_site_id) and _matches(row, {**filters, "priority": None, "owner_ids": case["owner_ids"]}, date_attr="planning_period_end", terminal={"Met", "Cancelled"}, owner_attr="owner_id")]
        expected_items = [_expected_enrollment_item(row, [m for m in in_scope(records["milestones"]) if report_site_id is None or m.site_id == report_site_id]) for row in expected_targets]
        expected_totals = {"count": len(expected_items), "target": sum(item["target"] for item in expected_items), "actual": sum(item["actual"] for item in expected_items), "variance": sum(item["variance"] for item in expected_items), "status": dict(Counter(item["status"] for item in expected_items)), "trend": dict(Counter(item["due_date_category"] for item in expected_items))}
    else:
        report = await report_service.task_report(session, study_id, user, **common, status=filters["status"], owner_id=None if filters["owner_index"] is None else case["owner_ids"][filters["owner_index"]], priority=filters["priority"], due_date=filters["due_date"], trend=filters["trend"])
        expected_rows = [row for row in in_scope(records["tasks"]) if (report_site_id is None or row.site_id == report_site_id) and _matches(row, {**filters, "owner_ids": case["owner_ids"]}, date_attr="due_date", terminal=set(_TERMINAL_TASK_STATUSES), owner_attr="owner_id")]
        expected_items = [_expected_task_item(row) for row in expected_rows]
        expected_totals = {"count": len(expected_items), "owner": dict(Counter(str(item["owner_id"]) for item in expected_items)), "status": dict(Counter(item["status"] for item in expected_items)), "priority": dict(Counter(item["priority"] for item in expected_items)), "due_date": dict(Counter(item["due_date_category"] for item in expected_items)), "overdue": sum(item["due_date_category"] == "overdue" for item in expected_items)}

    assert report.items == expected_items
    assert report.totals == expected_totals
    assert all(item["operational_only"] for item in report.items)
