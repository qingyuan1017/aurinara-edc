"""Business rules and scoped queries for CTMS portfolio completion features."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import (
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.monitoring import MonitoringActivity, MonitoringFinding
from app.models.ctms.operational_site import ActivationAction
from app.models.ctms.portfolio_management import (
    CAPAStatus,
    CAPATransition,
    CorrectiveActionPlan,
    CRAAssignment,
    CRAAvailabilityException,
    CRACapacityPlan,
    OperationalTemplate,
    OperationalTemplateVersion,
    SiteFeasibilityAssessment,
    SitePerformanceScorecard,
    SitePerformanceSnapshot,
    TemplateApplication,
    VersionStatus,
    WorkflowExecution,
    WorkflowRule,
    WorkflowRuleVersion,
    WorkflowStatus,
    utc_now,
)
from app.models.ctms.projection import CTMSOperationalProjection
from app.models.ctms.work import OperationalTask, TaskEscalation
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User, UserStatus
from app.repositories.ctms.portfolio_repository import PortfolioScope, _scope_condition
from app.schemas.ctms.portfolio_management import (
    AvailabilityExceptionCreate,
    CapacityPlanCreate,
    CAPACreate,
    CAPAUpdate,
    CRAAssignmentCreate,
    FeasibilityCreate,
    FeasibilityUpdate,
    LifecycleTransition,
    OperationalTemplateCreate,
    ScorecardCreate,
    TemplateApplyRequest,
    TemplateVersionCreate,
    WorkflowRuleCreate,
    WorkflowRuleVersionCreate,
)
from app.schemas.ctms.work import TaskCreate, TaskUpdate
from app.services.ctms.portfolio_service import portfolio_service
from app.services.ctms.work_management_service import work_management_service
from app.services.shared.notification_service import notification_service

TERMINAL_TASKS = {"Completed", "Cancelled", "Archived"}
TERMINAL_FEASIBILITY = {"Selected", "Not Selected", "Withdrawn"}
TERMINAL_CAPA = {"Closed", "Cancelled"}
ALLOWED_TEMPLATE_TYPES = {
    "study_startup",
    "site_startup",
    "feasibility_questionnaire",
    "monitoring_checklist",
    "operational_task_pack",
}
ALLOWED_TRIGGERS = {
    "task_due",
    "task_overdue",
    "monitoring_overdue",
    "finding_severity",
    "site_activation_delay",
    "contract_expiration",
    "invoice_overdue",
    "capa_due",
    "capacity_overload",
}
ALLOWED_ACTIONS = {"create_task", "send_notification", "assign_owner", "escalate_task"}
FEASIBILITY_TRANSITIONS = {
    "Draft": {"Questionnaire Sent", "Withdrawn"},
    "Questionnaire Sent": {"Response Received", "Withdrawn"},
    "Response Received": {"Under Review", "Questionnaire Sent", "Withdrawn"},
    "Under Review": {"Selected", "Not Selected", "Questionnaire Sent", "Withdrawn"},
    "Selected": {"Under Review"},
    "Not Selected": {"Under Review"},
    "Withdrawn": {"Draft"},
}
CAPA_TRANSITIONS = {
    "Draft": {"Investigation", "Cancelled"},
    "Investigation": {"Action Plan Approved", "Cancelled"},
    "Action Plan Approved": {"Implementation", "Cancelled"},
    "Implementation": {"Effectiveness Review", "Cancelled"},
    "Effectiveness Review": {"Implementation", "Closed", "Cancelled"},
    "Closed": {"Effectiveness Review"},
    "Cancelled": {"Draft"},
}
DEFAULT_SCORE_WEIGHTS = {
    "startup_timeliness": 15,
    "enrollment_attainment": 25,
    "monitoring_timeliness": 20,
    "finding_aging": 15,
    "task_timeliness": 10,
    "data_quality": 15,
}


def calculate_weighted_score(
    components: dict[str, Decimal | float | int | None],
    weights: dict[str, int],
) -> tuple[Decimal, Decimal]:
    """Return a weighted score and data coverage using available components only."""
    available = {
        key: Decimal(str(value))
        for key, value in components.items()
        if value is not None and weights.get(key, 0) > 0
    }
    available_weight = sum(Decimal(weights[key]) for key in available)
    total_weight = sum(Decimal(value) for value in weights.values())
    if available_weight <= 0 or total_weight <= 0:
        return Decimal("0.00"), Decimal("0.00")
    score = sum(available[key] * Decimal(weights[key]) for key in available) / available_weight
    coverage = available_weight / total_weight * Decimal("100")
    return score.quantize(Decimal("0.01")), coverage.quantize(Decimal("0.01"))


def _name(first: str | None, last: str | None) -> str | None:
    value = " ".join(filter(None, (first, last))).strip()
    return value or None


class PortfolioManagementService:
    async def scope(self, session: AsyncSession, user: User) -> PortfolioScope:
        return await portfolio_service.resolve_scope(session, user)

    @staticmethod
    def assert_scope(scope: PortfolioScope, study_id: UUID, site_id: UUID | None = None) -> None:
        allowed = study_id in scope.study_wide_ids or (
            site_id is not None and site_id in scope.site_ids
        )
        if not allowed:
            raise AuthorizationError(
                "Insufficient permissions", {"required_permission": "ctms.operational_data_read"}
            )

    @staticmethod
    async def _page(session: AsyncSession, query, page: int, page_size: int):
        total = int(
            await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
            or 0
        )
        rows = (
            (await session.execute(query.offset((page - 1) * page_size).limit(page_size)))
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], total

    async def summary(self, session: AsyncSession, user: User) -> dict[str, Any]:
        scope = await self.scope(session, user)
        now = datetime.now(UTC)
        study_count = len(scope.study_ids)
        site_count = int(
            await session.scalar(
                select(func.count(Site.id)).where(
                    Site.deleted_at.is_(None), _scope_condition(Site, scope)
                )
            )
            or 0
        )
        open_work = int(
            await session.scalar(
                select(func.count(OperationalTask.id)).where(
                    OperationalTask.deleted_at.is_(None),
                    ~OperationalTask.status.in_(TERMINAL_TASKS),
                    _scope_condition(OperationalTask, scope),
                )
            )
            or 0
        )
        overdue_work = int(
            await session.scalar(
                select(func.count(OperationalTask.id)).where(
                    OperationalTask.deleted_at.is_(None),
                    ~OperationalTask.status.in_(TERMINAL_TASKS),
                    OperationalTask.due_date < now,
                    _scope_condition(OperationalTask, scope),
                )
            )
            or 0
        )
        open_findings = int(
            await session.scalar(
                select(func.count(MonitoringFinding.id)).where(
                    MonitoringFinding.deleted_at.is_(None),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                    _scope_condition(MonitoringFinding, scope),
                )
            )
            or 0
        )
        overdue_visits = int(
            await session.scalar(
                select(func.count(MonitoringActivity.id)).where(
                    MonitoringActivity.deleted_at.is_(None),
                    MonitoringActivity.planned_date < now,
                    ~MonitoringActivity.status.in_(("Completed", "Cancelled")),
                    _scope_condition(MonitoringActivity, scope),
                )
            )
            or 0
        )
        active_feasibility = int(
            await session.scalar(
                select(func.count(SiteFeasibilityAssessment.id)).where(
                    SiteFeasibilityAssessment.deleted_at.is_(None),
                    ~SiteFeasibilityAssessment.status.in_(TERMINAL_FEASIBILITY),
                    _scope_condition(SiteFeasibilityAssessment, scope),
                )
            )
            or 0
        )
        open_capas = int(
            await session.scalar(
                select(func.count(CorrectiveActionPlan.id)).where(
                    CorrectiveActionPlan.deleted_at.is_(None),
                    ~CorrectiveActionPlan.status.in_(TERMINAL_CAPA),
                    _scope_condition(CorrectiveActionPlan, scope),
                )
            )
            or 0
        )
        financials = await portfolio_service.financial_summary(session, user)
        utilization, _ = await self.utilization(session, user, page=1, page_size=100)
        return {
            "studies": study_count,
            "sites": site_count,
            "open_work": open_work,
            "overdue_work": overdue_work,
            "open_findings": open_findings,
            "overdue_visits": overdue_visits,
            "active_feasibility": active_feasibility,
            "open_capas": open_capas,
            "overloaded_cras": sum(1 for row in utilization if row["is_over_capacity"]),
            "financials_by_currency": financials,
        }

    async def studies(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
    ):
        scope = await self.scope(session, user)
        now = datetime.now(UTC)
        site_count = (
            select(func.count(Site.id))
            .where(Site.study_id == Study.id, Site.deleted_at.is_(None))
            .scalar_subquery()
        )
        open_work = (
            select(func.count(OperationalTask.id))
            .where(
                OperationalTask.study_id == Study.id,
                OperationalTask.deleted_at.is_(None),
                ~OperationalTask.status.in_(TERMINAL_TASKS),
            )
            .scalar_subquery()
        )
        overdue_work = (
            select(func.count(OperationalTask.id))
            .where(
                OperationalTask.study_id == Study.id,
                OperationalTask.deleted_at.is_(None),
                ~OperationalTask.status.in_(TERMINAL_TASKS),
                OperationalTask.due_date < now,
            )
            .scalar_subquery()
        )
        overdue_visits = (
            select(func.count(MonitoringActivity.id))
            .where(
                MonitoringActivity.study_id == Study.id,
                MonitoringActivity.deleted_at.is_(None),
                MonitoringActivity.planned_date < now,
                ~MonitoringActivity.status.in_(("Completed", "Cancelled")),
            )
            .scalar_subquery()
        )
        findings = (
            select(func.count(MonitoringFinding.id))
            .where(
                MonitoringFinding.study_id == Study.id,
                MonitoringFinding.deleted_at.is_(None),
                ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
            )
            .scalar_subquery()
        )
        capas = (
            select(func.count(CorrectiveActionPlan.id))
            .where(
                CorrectiveActionPlan.study_id == Study.id,
                CorrectiveActionPlan.deleted_at.is_(None),
                ~CorrectiveActionPlan.status.in_(TERMINAL_CAPA),
            )
            .scalar_subquery()
        )
        perf = (
            select(func.max(SitePerformanceSnapshot.overall_score))
            .where(SitePerformanceSnapshot.study_id == Study.id)
            .scalar_subquery()
        )
        q = select(
            Study.id.label("study_id"),
            Study.study_code,
            Study.title.label("study_title"),
            Study.status,
            site_count.label("site_count"),
            open_work.label("open_work"),
            overdue_work.label("overdue_work"),
            overdue_visits.label("overdue_visits"),
            findings.label("open_findings"),
            capas.label("open_capas"),
            perf.label("performance_score"),
        ).where(Study.deleted_at.is_(None), Study.id.in_(scope.study_ids))
        if search:
            q = q.where(
                or_(Study.study_code.ilike(f"%{search}%"), Study.title.ilike(f"%{search}%"))
            )
        rows, total = await self._page(session, q.order_by(Study.study_code), page, page_size)
        for row in rows:
            row["destination_path"] = f"/studies/{row['study_id']}/ctms"
            row["financials_by_currency"] = []
        return rows, total

    async def tasks(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        owner_id: UUID | None = None,
        status: str | None = None,
        mine: bool = False,
    ):
        scope = await self.scope(session, user)
        owner = user.id if mine else owner_id
        q = (
            select(
                OperationalTask.id.label("source_id"),
                OperationalTask.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                OperationalTask.site_id,
                Site.site_number,
                Site.name.label("site_name"),
                OperationalTask.title,
                OperationalTask.owner_id,
                User.first_name,
                User.last_name,
                OperationalTask.status,
                OperationalTask.priority,
                OperationalTask.due_date.label("due_at"),
            )
            .join(Study, Study.id == OperationalTask.study_id)
            .outerjoin(Site, Site.id == OperationalTask.site_id)
            .outerjoin(User, User.id == OperationalTask.owner_id)
            .where(OperationalTask.deleted_at.is_(None), _scope_condition(OperationalTask, scope))
        )
        if owner:
            q = q.where(OperationalTask.owner_id == owner)
        if status:
            q = q.where(OperationalTask.status == status)
        rows, total = await self._page(
            session, q.order_by(OperationalTask.due_date.asc().nullslast()), page, page_size
        )
        now = datetime.now(UTC)
        for row in rows:
            row.update(
                source_type="operational_task",
                site_label=" — ".join(filter(None, (row.pop("site_number"), row.pop("site_name"))))
                or None,
                owner_name=_name(row.pop("first_name"), row.pop("last_name")),
                is_overdue=bool(
                    row["due_at"] and row["due_at"] < now and row["status"] not in TERMINAL_TASKS
                ),
                destination_path=f"/studies/{row['study_id']}/ctms/tasks",
                permitted_actions=["update", "transition"],
            )
        return rows, total

    async def work(self, session: AsyncSession, user: User, *, page: int, page_size: int):
        # The task queue is authoritative for actionable cross-domain follow-up;
        # monitoring and feasibility rows are also surfaced below.
        task_rows, _ = await self.tasks(session, user, page=1, page_size=100, mine=True)
        scope = await self.scope(session, user)
        q = (
            select(
                MonitoringActivity.id.label("source_id"),
                MonitoringActivity.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                MonitoringActivity.site_id,
                Site.site_number,
                Site.name.label("site_name"),
                MonitoringActivity.activity_type.label("title"),
                MonitoringActivity.assigned_cra_id.label("owner_id"),
                User.first_name,
                User.last_name,
                MonitoringActivity.status,
                MonitoringActivity.planned_date.label("due_at"),
            )
            .join(Study, Study.id == MonitoringActivity.study_id)
            .outerjoin(Site, Site.id == MonitoringActivity.site_id)
            .outerjoin(User, User.id == MonitoringActivity.assigned_cra_id)
            .where(
                MonitoringActivity.deleted_at.is_(None),
                MonitoringActivity.assigned_cra_id == user.id,
                _scope_condition(MonitoringActivity, scope),
            )
        )
        visits = [dict(row) for row in (await session.execute(q)).mappings().all()]
        now = datetime.now(UTC)
        for row in visits:
            row.update(
                source_type="monitoring_visit",
                site_label=" — ".join(filter(None, (row.pop("site_number"), row.pop("site_name"))))
                or None,
                owner_name=_name(row.pop("first_name"), row.pop("last_name")),
                priority=None,
                is_overdue=bool(
                    row["due_at"]
                    and row["due_at"] < now
                    and row["status"] not in ("Completed", "Cancelled")
                ),
                destination_path=f"/studies/{row['study_id']}/ctms/monitoring/visits/{row['source_id']}",
                permitted_actions=["open"],
            )
        combined = sorted(
            task_rows + visits, key=lambda row: (row["due_at"] is None, row["due_at"] or now)
        )
        return combined[(page - 1) * page_size : page * page_size], len(combined)

    async def feasibility(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        study_id: UUID | None = None,
    ):
        scope = await self.scope(session, user)
        q = (
            select(
                SiteFeasibilityAssessment,
                Study.study_code,
                Study.title.label("study_title"),
                Site.site_number,
                Site.name.label("site_name"),
                User.first_name,
                User.last_name,
            )
            .join(Study, Study.id == SiteFeasibilityAssessment.study_id)
            .join(Site, Site.id == SiteFeasibilityAssessment.site_id)
            .outerjoin(User, User.id == SiteFeasibilityAssessment.owner_id)
            .where(
                SiteFeasibilityAssessment.deleted_at.is_(None),
                _scope_condition(SiteFeasibilityAssessment, scope),
            )
        )
        if status:
            q = q.where(SiteFeasibilityAssessment.status == status)
        if study_id:
            self.assert_scope(scope, study_id)
            q = q.where(SiteFeasibilityAssessment.study_id == study_id)
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(SiteFeasibilityAssessment.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = []
        for (
            assessment,
            study_code,
            study_title,
            site_number,
            site_name,
            first,
            last,
        ) in result.all():
            data = {
                key: getattr(assessment, key)
                for key in (
                    "id",
                    "study_id",
                    "site_id",
                    "owner_id",
                    "questionnaire_version_id",
                    "status",
                    "criteria_json",
                    "responses_json",
                    "score",
                    "recommendation",
                    "decision_reason",
                    "notes",
                    "sent_at",
                    "responded_at",
                    "decided_at",
                    "version",
                    "created_at",
                    "updated_at",
                )
            }
            data.update(
                study_code=study_code,
                study_title=study_title,
                site_number=site_number,
                site_name=site_name,
                owner_name=_name(first, last),
                destination_path=f"/studies/{assessment.study_id}/ctms/sites/feasibility",
            )
            rows.append(data)
        return rows, total

    async def performance(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        site_id: UUID | None = None,
        study_id: UUID | None = None,
    ):
        scope = await self.scope(session, user)
        latest = (
            select(
                SitePerformanceSnapshot.site_id,
                func.max(SitePerformanceSnapshot.snapshot_date).label("max_date"),
            )
            .group_by(SitePerformanceSnapshot.site_id)
            .subquery()
        )
        q = (
            select(
                Study.id.label("study_id"),
                Study.study_code,
                Study.title.label("study_title"),
                Site.id.label("site_id"),
                Site.site_number,
                Site.name.label("site_name"),
                SitePerformanceSnapshot.scorecard_id,
                SitePerformanceScorecard.version_number.label("scorecard_version"),
                SitePerformanceSnapshot.overall_score,
                SitePerformanceSnapshot.coverage_percent,
                SitePerformanceSnapshot.component_scores_json.label("component_scores"),
                SitePerformanceSnapshot.component_sources_json.label("component_sources"),
                SitePerformanceSnapshot.snapshot_date,
            )
            .join(Study, Study.id == Site.study_id)
            .outerjoin(latest, latest.c.site_id == Site.id)
            .outerjoin(
                SitePerformanceSnapshot,
                and_(
                    SitePerformanceSnapshot.site_id == Site.id,
                    SitePerformanceSnapshot.snapshot_date == latest.c.max_date,
                ),
            )
            .outerjoin(
                SitePerformanceScorecard,
                SitePerformanceScorecard.id == SitePerformanceSnapshot.scorecard_id,
            )
            .where(Site.deleted_at.is_(None), _scope_condition(Site, scope))
        )
        if site_id:
            q = q.where(Site.id == site_id)
        if study_id:
            self.assert_scope(scope, study_id)
            q = q.where(Site.study_id == study_id)
        rows, total = await self._page(
            session,
            q.order_by(SitePerformanceSnapshot.overall_score.asc().nullsfirst()),
            page,
            page_size,
        )
        for row in rows:
            row["destination_path"] = f"/studies/{row['study_id']}/ctms/sites/performance"
        return rows, total

    async def performance_trend(self, session: AsyncSession, user: User, site_id: UUID):
        scope = await self.scope(session, user)
        site = await session.get(Site, site_id)
        if not site:
            raise NotFoundError("Site not found")
        self.assert_scope(scope, site.study_id, site.id)
        rows = (
            (
                await session.execute(
                    select(SitePerformanceSnapshot)
                    .where(SitePerformanceSnapshot.site_id == site_id)
                    .order_by(SitePerformanceSnapshot.snapshot_date)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "snapshot_date": r.snapshot_date,
                "overall_score": r.overall_score,
                "coverage_percent": r.coverage_percent,
                "component_scores": r.component_scores_json,
                "scorecard_id": r.scorecard_id,
            }
            for r in rows
        ]

    async def list_scorecards(self, session: AsyncSession, *, page: int, page_size: int):
        query = select(SitePerformanceScorecard).order_by(
            SitePerformanceScorecard.name, SitePerformanceScorecard.version_number.desc()
        )
        total = int(await session.scalar(select(func.count(SitePerformanceScorecard.id))) or 0)
        rows = list(
            (await session.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
        )
        return rows, total

    async def create_scorecard(
        self, session: AsyncSession, user: User, body: ScorecardCreate
    ) -> SitePerformanceScorecard:
        version_number = (
            int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(SitePerformanceScorecard.version_number), 0)
                    ).where(SitePerformanceScorecard.name == body.name)
                )
                or 0
            )
            + 1
        )
        scorecard = SitePerformanceScorecard(
            name=body.name,
            version_number=version_number,
            weights_json=body.weights,
            thresholds_json=body.thresholds,
            created_by=user.id,
        )
        session.add(scorecard)
        await session.flush()
        await self._audit(session, "ctms_site_performance_scorecard", scorecard.id, "create", user)
        return scorecard

    async def publish_scorecard(
        self, session: AsyncSession, user: User, scorecard_id: UUID, reason: str
    ) -> SitePerformanceScorecard:
        scorecard = await session.get(SitePerformanceScorecard, scorecard_id)
        if scorecard is None:
            raise NotFoundError("Site performance scorecard not found")
        if scorecard.status != VersionStatus.DRAFT.value:
            raise BusinessRuleError("Only draft scorecards can be published")
        scorecard.status = VersionStatus.PUBLISHED.value
        scorecard.published_at = utc_now()
        scorecard.published_by = user.id
        await self._audit(
            session,
            "ctms_site_performance_scorecard",
            scorecard.id,
            "publish",
            user,
            reason=reason,
        )
        await session.flush()
        return scorecard

    async def capas(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        study_id: UUID | None = None,
    ):
        scope = await self.scope(session, user)
        now = datetime.now(UTC)
        q = (
            select(
                CorrectiveActionPlan,
                Study.study_code,
                Study.title.label("study_title"),
                Site.site_number,
                Site.name.label("site_name"),
                User.first_name,
                User.last_name,
            )
            .join(Study, Study.id == CorrectiveActionPlan.study_id)
            .outerjoin(Site, Site.id == CorrectiveActionPlan.site_id)
            .outerjoin(User, User.id == CorrectiveActionPlan.owner_id)
            .where(
                CorrectiveActionPlan.deleted_at.is_(None),
                _scope_condition(CorrectiveActionPlan, scope),
            )
        )
        if status:
            q = q.where(CorrectiveActionPlan.status == status)
        if study_id:
            self.assert_scope(scope, study_id)
            q = q.where(CorrectiveActionPlan.study_id == study_id)
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(CorrectiveActionPlan.due_date.asc().nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = []
        for capa, study_code, study_title, site_number, site_name, first, last in result.all():
            data = {
                key: getattr(capa, key)
                for key in (
                    "id",
                    "study_id",
                    "site_id",
                    "source_type",
                    "source_id",
                    "title",
                    "owner_id",
                    "status",
                    "root_cause",
                    "corrective_actions_json",
                    "preventive_actions_json",
                    "evidence_references_json",
                    "effectiveness_criteria",
                    "effectiveness_result",
                    "due_date",
                    "closed_at",
                    "closure_reason",
                    "version",
                    "created_at",
                    "updated_at",
                )
            }
            data.update(
                study_code=study_code,
                study_title=study_title,
                site_label=" — ".join(filter(None, (site_number, site_name))) or None,
                owner_name=_name(first, last),
                is_overdue=bool(
                    capa.due_date and capa.due_date < now and capa.status not in TERMINAL_CAPA
                ),
                destination_path=f"/studies/{capa.study_id}/ctms/tasks/capa",
            )
            rows.append(data)
        return rows, total

    async def issues(self, session: AsyncSession, user: User, *, page: int, page_size: int):
        scope = await self.scope(session, user)
        now = datetime.now(UTC)
        rows = []
        findings = (
            await session.execute(
                select(
                    MonitoringFinding, Study.study_code, Study.title, Site.site_number, Site.name
                )
                .join(Study, Study.id == MonitoringFinding.study_id)
                .outerjoin(Site, Site.id == MonitoringFinding.site_id)
                .where(
                    MonitoringFinding.deleted_at.is_(None),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                    _scope_condition(MonitoringFinding, scope),
                )
            )
        ).all()
        capa_map = {
            str(source_id): capa_id
            for source_id, capa_id in (
                await session.execute(
                    select(CorrectiveActionPlan.source_id, CorrectiveActionPlan.id).where(
                        CorrectiveActionPlan.deleted_at.is_(None)
                    )
                )
            ).all()
        }
        for item, code, title, num, name in findings:
            rows.append(
                {
                    "source_type": "monitoring_finding",
                    "source_id": item.id,
                    "study_id": item.study_id,
                    "study_code": code,
                    "study_title": title,
                    "site_id": item.site_id,
                    "site_label": " — ".join(filter(None, (num, name))) or None,
                    "title": item.description[:255],
                    "severity": item.severity,
                    "status": item.status,
                    "owner_id": item.owner_id,
                    "due_at": item.due_date,
                    "is_overdue": bool(item.due_date and item.due_date < now),
                    "capa_id": capa_map.get(str(item.id)),
                    "destination_path": f"/studies/{item.study_id}/ctms/monitoring/findings",
                }
            )
        tasks = (
            await session.execute(
                select(OperationalTask, Study.study_code, Study.title, Site.site_number, Site.name)
                .join(Study, Study.id == OperationalTask.study_id)
                .outerjoin(Site, Site.id == OperationalTask.site_id)
                .where(
                    OperationalTask.deleted_at.is_(None),
                    or_(
                        OperationalTask.status == "Blocked",
                        and_(
                            OperationalTask.due_date < now,
                            ~OperationalTask.status.in_(TERMINAL_TASKS),
                        ),
                    ),
                    _scope_condition(OperationalTask, scope),
                )
            )
        ).all()
        for item, code, title, num, name in tasks:
            rows.append(
                {
                    "source_type": "operational_task",
                    "source_id": item.id,
                    "study_id": item.study_id,
                    "study_code": code,
                    "study_title": title,
                    "site_id": item.site_id,
                    "site_label": " — ".join(filter(None, (num, name))) or None,
                    "title": item.title,
                    "severity": item.priority,
                    "status": item.status,
                    "owner_id": item.owner_id,
                    "due_at": item.due_date,
                    "is_overdue": bool(item.due_date and item.due_date < now),
                    "capa_id": capa_map.get(str(item.id)),
                    "destination_path": f"/studies/{item.study_id}/ctms/tasks",
                }
            )
        rows.sort(key=lambda x: (not x["is_overdue"], x["due_at"] or now))
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    async def escalations(self, session: AsyncSession, user: User, *, page: int, page_size: int):
        scope = await self.scope(session, user)
        now = datetime.now(UTC)
        q = (
            select(
                TaskEscalation,
                OperationalTask,
                Study.study_code,
                Study.title,
                User.first_name,
                User.last_name,
            )
            .join(OperationalTask, OperationalTask.id == TaskEscalation.task_id)
            .join(Study, Study.id == OperationalTask.study_id)
            .outerjoin(User, User.id == TaskEscalation.owner_id)
            .where(_scope_condition(OperationalTask, scope))
        )
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(TaskEscalation.deadline.asc().nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = []
        for esc, task, code, title, first, last in result.all():
            rows.append(
                {
                    "id": esc.id,
                    "task_id": task.id,
                    "study_id": task.study_id,
                    "study_code": code,
                    "study_title": title,
                    "site_id": task.site_id,
                    "task_title": task.title,
                    "owner_id": esc.owner_id,
                    "owner_name": _name(first, last),
                    "status": esc.status,
                    "reason": esc.reason,
                    "deadline": esc.deadline,
                    "is_overdue": bool(
                        esc.deadline
                        and esc.deadline < now
                        and esc.status not in ("Resolved", "Cancelled")
                    ),
                    "destination_path": f"/studies/{task.study_id}/ctms/tasks",
                }
            )
        return rows, total

    async def cra_assignments(
        self, session: AsyncSession, user: User, *, page: int, page_size: int
    ):
        scope = await self.scope(session, user)
        q = (
            select(
                CRAAssignment,
                User.first_name,
                User.last_name,
                Study.study_code,
                Site.site_number,
                Site.name,
            )
            .join(User, User.id == CRAAssignment.user_id)
            .join(Study, Study.id == CRAAssignment.study_id)
            .outerjoin(Site, Site.id == CRAAssignment.site_id)
            .where(_scope_condition(CRAAssignment, scope))
        )
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(User.last_name, User.first_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = []
        for a, first, last, code, num, name in result.all():
            rows.append(
                {
                    "id": a.id,
                    "user_id": a.user_id,
                    "user_name": _name(first, last),
                    "study_id": a.study_id,
                    "study_code": code,
                    "site_id": a.site_id,
                    "site_label": " — ".join(filter(None, (num, name))) or None,
                    "role": a.role,
                    "planned_hours_per_week": a.planned_hours_per_week,
                    "effective_from": a.effective_from,
                    "effective_to": a.effective_to,
                    "active": a.active,
                    "over_capacity_reason": a.over_capacity_reason,
                    "created_at": a.created_at,
                }
            )
        return rows, total

    async def capacity(self, session: AsyncSession, user: User, *, page: int, page_size: int):
        # Capacity is user-level, but only CRAs assigned into an authorized study are visible.
        scope = await self.scope(session, user)
        allowed_users = (
            select(CRAAssignment.user_id).where(_scope_condition(CRAAssignment, scope)).distinct()
        )
        q = (
            select(CRACapacityPlan, User.first_name, User.last_name)
            .join(User, User.id == CRACapacityPlan.user_id)
            .where(CRACapacityPlan.user_id.in_(allowed_users))
        )
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(CRACapacityPlan.week_start.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = [
            {
                "id": p.id,
                "user_id": p.user_id,
                "user_name": _name(first_name, last_name),
                "week_start": p.week_start,
                "capacity_hours": p.capacity_hours,
                "timezone": p.timezone,
                "created_at": p.created_at,
            }
            for p, first_name, last_name in result.all()
        ]
        return rows, total

    async def utilization(
        self,
        session: AsyncSession,
        user: User,
        *,
        page: int,
        page_size: int,
        week_start: date | None = None,
    ):
        scope = await self.scope(session, user)
        week_start = week_start or (date.today() - timedelta(days=date.today().weekday()))
        week_end = week_start + timedelta(days=6)
        allowed_users = (
            select(CRAAssignment.user_id).where(_scope_condition(CRAAssignment, scope)).distinct()
        )
        plans = (
            await session.execute(
                select(CRACapacityPlan, User.first_name, User.last_name)
                .join(User, User.id == CRACapacityPlan.user_id)
                .where(
                    CRACapacityPlan.week_start == week_start,
                    CRACapacityPlan.user_id.in_(allowed_users),
                )
                .order_by(User.last_name, User.first_name)
            )
        ).all()
        rows = []
        for plan, first, last in plans:
            exception = Decimal(
                str(
                    await session.scalar(
                        select(
                            func.coalesce(func.sum(CRAAvailabilityException.unavailable_hours), 0)
                        ).where(
                            CRAAvailabilityException.user_id == plan.user_id,
                            CRAAvailabilityException.exception_date.between(week_start, week_end),
                        )
                    )
                    or 0
                )
            )
            allocated = Decimal(
                str(
                    await session.scalar(
                        select(
                            func.coalesce(func.sum(CRAAssignment.planned_hours_per_week), 0)
                        ).where(
                            CRAAssignment.user_id == plan.user_id,
                            CRAAssignment.active.is_(True),
                            CRAAssignment.effective_from <= week_end,
                            or_(
                                CRAAssignment.effective_to.is_(None),
                                CRAAssignment.effective_to >= week_start,
                            ),
                            _scope_condition(CRAAssignment, scope),
                        )
                    )
                    or 0
                )
            )
            available = max(Decimal("0"), Decimal(plan.capacity_hours) - exception)
            utilization = (
                (allocated / available * 100).quantize(Decimal("0.01"))
                if available
                else (Decimal("100") if allocated else Decimal("0"))
            )
            start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC)
            end_dt = start_dt + timedelta(days=7)
            counts = (
                await session.execute(
                    select(
                        func.sum(
                            func.cast(
                                and_(
                                    MonitoringActivity.planned_date >= start_dt,
                                    MonitoringActivity.planned_date < end_dt,
                                    MonitoringActivity.status.not_in(("Completed", "Cancelled")),
                                ),
                                Integer,
                            )
                        ),
                        func.sum(
                            func.cast(
                                and_(
                                    MonitoringActivity.planned_date < datetime.now(UTC),
                                    MonitoringActivity.status.not_in(("Completed", "Cancelled")),
                                ),
                                Integer,
                            )
                        ),
                    ).where(
                        MonitoringActivity.assigned_cra_id == plan.user_id,
                        _scope_condition(MonitoringActivity, scope),
                    )
                )
            ).one()
            rows.append(
                {
                    "user_id": plan.user_id,
                    "user_name": _name(first, last) or "Unknown user",
                    "week_start": week_start,
                    "timezone": plan.timezone,
                    "capacity_hours": plan.capacity_hours,
                    "exception_hours": exception,
                    "available_hours": available,
                    "allocated_hours": allocated,
                    "utilization_percent": utilization,
                    "upcoming_visits": int(counts[0] or 0),
                    "overdue_visits": int(counts[1] or 0),
                    "is_over_capacity": allocated > available,
                }
            )
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    async def refresh_performance_snapshots(
        self, session: AsyncSession, *, snapshot_date: date | None = None
    ) -> int:
        """Refresh one idempotent daily snapshot per active canonical site.

        Clinical quality contributes only through a current, minimized
        ``data_quality_signal`` projection whose payload contains an aggregate
        ``score``. Raw EDC records are never queried here.
        """
        run_date = snapshot_date or date.today()
        now = datetime.now(UTC)
        scorecard = await session.scalar(
            select(SitePerformanceScorecard)
            .where(SitePerformanceScorecard.status == VersionStatus.PUBLISHED.value)
            .order_by(
                SitePerformanceScorecard.version_number.desc(),
                SitePerformanceScorecard.published_at.desc(),
            )
            .limit(1)
        )
        if scorecard is None:
            raise BusinessRuleError("No published site performance scorecard is available")
        sites = list(
            (
                await session.scalars(
                    select(Site).where(Site.deleted_at.is_(None)).order_by(Site.id)
                )
            ).all()
        )
        refreshed = 0
        for site in sites:
            activation = list(
                (
                    await session.scalars(
                        select(ActivationAction).where(
                            ActivationAction.site_id == site.id,
                            ActivationAction.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            startup = None
            if activation:
                on_time = sum(
                    1
                    for item in activation
                    if item.status == "Completed"
                    and (
                        item.planned_date is None
                        or (
                            item.completed_at is not None and item.completed_at <= item.planned_date
                        )
                    )
                )
                startup = Decimal(on_time) / Decimal(len(activation)) * 100

            target = await session.scalar(
                select(func.sum(EnrollmentTarget.target_quantity)).where(
                    EnrollmentTarget.site_id == site.id,
                    EnrollmentTarget.deleted_at.is_(None),
                    EnrollmentTarget.status.in_(("Active", "Met")),
                )
            )
            enrolled = await session.scalar(
                select(func.count(func.distinct(OperationalMilestone.subject_id))).where(
                    OperationalMilestone.site_id == site.id,
                    OperationalMilestone.deleted_at.is_(None),
                    OperationalMilestone.status.in_(
                        ("Enrolled", "Randomized", "On Treatment", "Completed")
                    ),
                )
            )
            enrollment = (
                min(Decimal("100"), Decimal(enrolled or 0) / Decimal(target) * 100)
                if target
                else None
            )

            visits = list(
                (
                    await session.scalars(
                        select(MonitoringActivity).where(
                            MonitoringActivity.site_id == site.id,
                            MonitoringActivity.deleted_at.is_(None),
                            MonitoringActivity.planned_date <= now,
                            MonitoringActivity.status != "Cancelled",
                        )
                    )
                ).all()
            )
            monitoring = None
            if visits:
                on_time = sum(
                    1
                    for item in visits
                    if item.status == "Completed"
                    and item.completed_at is not None
                    and item.completed_at <= item.planned_date
                )
                monitoring = Decimal(on_time) / Decimal(len(visits)) * 100

            findings = list(
                (
                    await session.scalars(
                        select(MonitoringFinding).where(
                            MonitoringFinding.site_id == site.id,
                            MonitoringFinding.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            finding_score = None
            if findings:
                healthy = sum(
                    1
                    for item in findings
                    if item.status in ("Closed", "Cancelled")
                    or item.due_date is None
                    or item.due_date >= now
                )
                finding_score = Decimal(healthy) / Decimal(len(findings)) * 100

            tasks = list(
                (
                    await session.scalars(
                        select(OperationalTask).where(
                            OperationalTask.site_id == site.id,
                            OperationalTask.deleted_at.is_(None),
                            OperationalTask.due_date.is_not(None),
                        )
                    )
                ).all()
            )
            task_score = None
            if tasks:
                timely = sum(
                    1
                    for item in tasks
                    if item.status == "Completed"
                    and item.due_date is not None
                    and item.updated_at <= item.due_date
                )
                task_score = Decimal(timely) / Decimal(len(tasks)) * 100

            projection = await session.scalar(
                select(CTMSOperationalProjection)
                .where(
                    CTMSOperationalProjection.site_id == site.id,
                    CTMSOperationalProjection.projection_type == "data_quality_signal",
                    CTMSOperationalProjection.status == "current",
                    CTMSOperationalProjection.deleted_at.is_(None),
                )
                .order_by(CTMSOperationalProjection.source_timestamp.desc())
                .limit(1)
            )
            data_quality = None
            projected_score = projection.payload_json.get("score") if projection else None
            if isinstance(projected_score, (int, float)) and not isinstance(projected_score, bool):
                data_quality = Decimal(str(projection.payload_json["score"]))

            components = {
                "startup_timeliness": startup,
                "enrollment_attainment": enrollment,
                "monitoring_timeliness": monitoring,
                "finding_aging": finding_score,
                "task_timeliness": task_score,
                "data_quality": data_quality,
            }
            overall, coverage = calculate_weighted_score(components, scorecard.weights_json)
            sources = {
                key: {
                    "available": value is not None,
                    "source": "approved_minimized_edc_projection"
                    if key == "data_quality"
                    else "ctms_operational",
                    "source_date": (
                        projection.source_timestamp.isoformat()
                        if key == "data_quality" and projection is not None
                        else now.isoformat()
                    ),
                }
                for key, value in components.items()
            }
            existing = await session.scalar(
                select(SitePerformanceSnapshot).where(
                    SitePerformanceSnapshot.study_id == site.study_id,
                    SitePerformanceSnapshot.site_id == site.id,
                    SitePerformanceSnapshot.scorecard_id == scorecard.id,
                    SitePerformanceSnapshot.snapshot_date == run_date,
                )
            )
            serializable_components = {
                key: float(value.quantize(Decimal("0.01"))) if value is not None else None
                for key, value in components.items()
            }
            if existing is None:
                existing = SitePerformanceSnapshot(
                    study_id=site.study_id,
                    site_id=site.id,
                    scorecard_id=scorecard.id,
                    snapshot_date=run_date,
                    component_scores_json=serializable_components,
                    component_sources_json=sources,
                    overall_score=overall,
                    coverage_percent=coverage,
                    source_date=now,
                )
                session.add(existing)
            else:
                existing.component_scores_json = serializable_components
                existing.component_sources_json = sources
                existing.overall_score = overall
                existing.coverage_percent = coverage
                existing.source_date = now
            refreshed += 1
        await session.flush()
        return refreshed

    async def _audit(
        self,
        session: AsyncSession,
        entity_type: str,
        entity_id: UUID,
        action: str,
        actor: User,
        *,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ):
        await audit_service.record(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            module=Module.CTMS,
            actor_id=actor.id,
            study_id=study_id,
            site_id=site_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    async def create_feasibility(
        self, session: AsyncSession, user: User, body: FeasibilityCreate, correlation_id: str
    ):
        scope = await self.scope(session, user)
        self.assert_scope(scope, body.study_id, body.site_id)
        site = await session.get(Site, body.site_id)
        if not site or site.study_id != body.study_id:
            raise ValidationError("Site does not belong to the study")
        existing = await session.scalar(
            select(SiteFeasibilityAssessment.id).where(
                SiteFeasibilityAssessment.study_id == body.study_id,
                SiteFeasibilityAssessment.site_id == body.site_id,
            )
        )
        if existing:
            raise ConflictError("A feasibility assessment already exists for this study and site")
        item = SiteFeasibilityAssessment(
            study_id=body.study_id,
            site_id=body.site_id,
            owner_id=body.owner_id,
            questionnaire_version_id=body.questionnaire_version_id,
            criteria_json=body.criteria,
            notes=body.notes,
            created_by=user.id,
            correlation_id=correlation_id,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            "ctms_site_feasibility",
            item.id,
            "create",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            correlation_id=correlation_id,
        )
        return item

    async def update_feasibility(
        self,
        session: AsyncSession,
        user: User,
        item_id: UUID,
        body: FeasibilityUpdate,
        correlation_id: str,
    ):
        item = await session.get(SiteFeasibilityAssessment, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Feasibility assessment not found")
        self.assert_scope(await self.scope(session, user), item.study_id, item.site_id)
        if item.version != body.expected_version:
            raise ConflictError("Feasibility assessment was updated by another user")
        for field, target in (
            ("owner_id", "owner_id"),
            ("responses", "responses_json"),
            ("score", "score"),
            ("recommendation", "recommendation"),
            ("notes", "notes"),
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(item, target, value)
        item.version += 1
        item.updated_by = user.id
        item.updated_at = utc_now()
        await self._audit(
            session,
            "ctms_site_feasibility",
            item.id,
            "update",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            correlation_id=correlation_id,
        )
        await session.flush()
        return item

    async def transition_feasibility(
        self,
        session: AsyncSession,
        user: User,
        item_id: UUID,
        body: LifecycleTransition,
        correlation_id: str,
    ):
        item = await session.get(SiteFeasibilityAssessment, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Feasibility assessment not found")
        self.assert_scope(await self.scope(session, user), item.study_id, item.site_id)
        if body.status not in FEASIBILITY_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError(
                f"Cannot transition feasibility from {item.status} to {body.status}"
            )
        old = item.status
        item.status = body.status
        item.decision_reason = (
            body.reason
            if body.status in TERMINAL_FEASIBILITY or old in TERMINAL_FEASIBILITY
            else item.decision_reason
        )
        now = utc_now()
        if body.status == "Questionnaire Sent":
            item.sent_at = now
        if body.status == "Response Received":
            item.responded_at = now
        if body.status in TERMINAL_FEASIBILITY:
            item.decided_at = now
        item.version += 1
        item.updated_by = user.id
        item.updated_at = now
        await self._audit(
            session,
            "ctms_site_feasibility",
            item.id,
            f"transition:{old}->{body.status}",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation_id,
        )
        await session.flush()
        return item

    async def create_capa(
        self, session: AsyncSession, user: User, body: CAPACreate, correlation_id: str
    ):
        self.assert_scope(await self.scope(session, user), body.study_id, body.site_id)
        existing = await session.scalar(
            select(CorrectiveActionPlan.id).where(
                CorrectiveActionPlan.source_type == body.source_type,
                CorrectiveActionPlan.source_id == body.source_id,
                CorrectiveActionPlan.deleted_at.is_(None),
            )
        )
        if existing:
            raise ConflictError("A CAPA already exists for this source")
        item = CorrectiveActionPlan(
            **body.model_dump(), created_by=user.id, correlation_id=correlation_id
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            "ctms_capa",
            item.id,
            "create",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            correlation_id=correlation_id,
        )
        return item

    async def update_capa(
        self,
        session: AsyncSession,
        user: User,
        item_id: UUID,
        body: CAPAUpdate,
        correlation_id: str,
    ):
        item = await session.get(CorrectiveActionPlan, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("CAPA not found")
        self.assert_scope(await self.scope(session, user), item.study_id, item.site_id)
        if item.status in TERMINAL_CAPA:
            raise BusinessRuleError(
                "Closed or cancelled CAPA records must be reopened before editing"
            )
        if item.version != body.expected_version:
            raise ConflictError("CAPA was updated by another user")
        mapping = {
            "corrective_actions": "corrective_actions_json",
            "preventive_actions": "preventive_actions_json",
            "evidence_references": "evidence_references_json",
        }
        for field, value in body.model_dump(exclude={"reason", "expected_version"}).items():
            if value is not None:
                setattr(item, mapping.get(field, field), value)
        item.version += 1
        item.updated_by = user.id
        item.updated_at = utc_now()
        await self._audit(
            session,
            "ctms_capa",
            item.id,
            "update",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation_id,
        )
        await session.flush()
        return item

    async def transition_capa(
        self,
        session: AsyncSession,
        user: User,
        item_id: UUID,
        body: LifecycleTransition,
        correlation_id: str,
    ):
        item = await session.get(CorrectiveActionPlan, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("CAPA not found")
        self.assert_scope(await self.scope(session, user), item.study_id, item.site_id)
        if body.status not in CAPA_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError(f"Cannot transition CAPA from {item.status} to {body.status}")
        if body.status == CAPAStatus.ACTION_PLAN_APPROVED.value and (
            not item.root_cause or not item.corrective_actions_json
        ):
            raise BusinessRuleError(
                "Root cause and corrective actions are required before approval"
            )
        if body.status == CAPAStatus.CLOSED.value and (
            not item.effectiveness_criteria or not item.effectiveness_result
        ):
            raise BusinessRuleError("Effectiveness criteria and result are required before closure")
        old = item.status
        item.status = body.status
        item.version += 1
        item.updated_by = user.id
        item.updated_at = utc_now()
        if body.status == "Closed":
            item.closed_at = utc_now()
            item.closure_reason = body.reason
        elif old in TERMINAL_CAPA:
            item.closed_at = None
            item.closure_reason = None
        session.add(
            CAPATransition(
                capa_id=item.id,
                from_status=old,
                to_status=body.status,
                reason=body.reason,
                actor_id=user.id,
                correlation_id=correlation_id,
            )
        )
        await self._audit(
            session,
            "ctms_capa",
            item.id,
            f"transition:{old}->{body.status}",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation_id,
        )
        await session.flush()
        return item

    async def list_templates(
        self, session: AsyncSession, *, page: int, page_size: int, published_only: bool = False
    ):
        latest = (
            select(
                OperationalTemplateVersion.template_id,
                func.max(OperationalTemplateVersion.version_number).label("version_number"),
            )
            .group_by(OperationalTemplateVersion.template_id)
            .subquery()
        )
        q = (
            select(OperationalTemplate, OperationalTemplateVersion)
            .join(latest, latest.c.template_id == OperationalTemplate.id)
            .join(
                OperationalTemplateVersion,
                and_(
                    OperationalTemplateVersion.template_id == latest.c.template_id,
                    OperationalTemplateVersion.version_number == latest.c.version_number,
                ),
            )
        )
        if published_only:
            q = q.where(
                OperationalTemplateVersion.status == VersionStatus.PUBLISHED.value,
                OperationalTemplate.retired_at.is_(None),
            )
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(OperationalTemplate.name).offset((page - 1) * page_size).limit(page_size)
        )
        return [
            {
                "id": t.id,
                "name": t.name,
                "template_type": t.template_type,
                "description": t.description,
                "retired_at": t.retired_at,
                "version_id": v.id,
                "version_number": v.version_number,
                "version_status": v.status,
                "content": v.content_json,
                "created_at": t.created_at,
            }
            for t, v in result.all()
        ], total

    async def create_template(
        self, session: AsyncSession, user: User, body: OperationalTemplateCreate
    ):
        if body.template_type not in ALLOWED_TEMPLATE_TYPES:
            raise ValidationError("Unsupported operational template type")
        template = OperationalTemplate(
            name=body.name,
            template_type=body.template_type,
            description=body.description,
            created_by=user.id,
        )
        session.add(template)
        await session.flush()
        version = OperationalTemplateVersion(
            template_id=template.id, version_number=1, content_json=body.content, created_by=user.id
        )
        session.add(version)
        await session.flush()
        await self._audit(session, "ctms_operational_template", template.id, "create", user)
        return template, version

    async def create_template_version(
        self, session: AsyncSession, user: User, template_id: UUID, body: TemplateVersionCreate
    ):
        template = await session.get(OperationalTemplate, template_id)
        if not template:
            raise NotFoundError("Operational template not found")
        number = (
            int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(OperationalTemplateVersion.version_number), 0)
                    ).where(OperationalTemplateVersion.template_id == template_id)
                )
                or 0
            )
            + 1
        )
        version = OperationalTemplateVersion(
            template_id=template_id,
            version_number=number,
            content_json=body.content,
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        await self._audit(session, "ctms_operational_template", template.id, "create_version", user)
        return template, version

    async def publish_template(
        self, session: AsyncSession, user: User, version_id: UUID, reason: str
    ):
        version = await session.get(OperationalTemplateVersion, version_id)
        if not version:
            raise NotFoundError("Template version not found")
        if version.status != VersionStatus.DRAFT.value:
            raise BusinessRuleError("Only draft template versions can be published")
        previous = list(
            (
                await session.scalars(
                    select(OperationalTemplateVersion).where(
                        OperationalTemplateVersion.template_id == version.template_id,
                        OperationalTemplateVersion.status == VersionStatus.PUBLISHED.value,
                        OperationalTemplateVersion.id != version.id,
                    )
                )
            ).all()
        )
        for published in previous:
            published.status = VersionStatus.RETIRED.value
        version.status = VersionStatus.PUBLISHED.value
        version.published_at = utc_now()
        version.published_by = user.id
        await self._audit(
            session, "ctms_operational_template_version", version.id, "publish", user, reason=reason
        )
        await session.flush()
        return version

    async def retire_template(
        self, session: AsyncSession, user: User, template_id: UUID, reason: str
    ):
        template = await session.get(OperationalTemplate, template_id)
        if not template:
            raise NotFoundError("Operational template not found")
        if template.retired_at is not None:
            raise BusinessRuleError("Operational template is already retired")
        template.retired_at = utc_now()
        versions = list(
            (
                await session.scalars(
                    select(OperationalTemplateVersion).where(
                        OperationalTemplateVersion.template_id == template_id,
                        OperationalTemplateVersion.status != VersionStatus.RETIRED.value,
                    )
                )
            ).all()
        )
        for version in versions:
            version.status = VersionStatus.RETIRED.value
        await self._audit(
            session, "ctms_operational_template", template.id, "retire", user, reason=reason
        )
        await session.flush()
        return template

    async def apply_template(
        self,
        session: AsyncSession,
        user: User,
        version_id: UUID,
        body: TemplateApplyRequest,
        correlation_id: str,
    ):
        version = await session.get(OperationalTemplateVersion, version_id)
        if not version or version.status != VersionStatus.PUBLISHED.value:
            raise NotFoundError("Published template version not found")
        self.assert_scope(await self.scope(session, user), body.study_id)
        preview = {
            "tasks": len(version.content_json.get("tasks", [])),
            "content_sections": sorted(version.content_json.keys()),
        }
        if body.preview_only:
            return None, preview
        existing = await session.scalar(
            select(TemplateApplication).where(
                TemplateApplication.study_id == body.study_id,
                TemplateApplication.idempotency_key == body.idempotency_key,
            )
        )
        if existing:
            return existing, existing.result_json
        created = []
        for spec in version.content_json.get("tasks", []):
            task = await work_management_service.create_task(
                session,
                TaskCreate(
                    study_id=body.study_id,
                    title=str(spec.get("title") or "Operational template task"),
                    description=spec.get("description"),
                    priority=spec.get("priority", "Normal"),
                ),
                user.id,
                correlation_id=correlation_id,
            )
            created.append(str(task.id))
        result = {**preview, "created_task_ids": created}
        application = TemplateApplication(
            template_version_id=version.id,
            study_id=body.study_id,
            idempotency_key=body.idempotency_key,
            result_json=result,
            applied_by=user.id,
        )
        session.add(application)
        await session.flush()
        await self._audit(
            session,
            "ctms_template_application",
            application.id,
            "apply",
            user,
            study_id=body.study_id,
            correlation_id=correlation_id,
        )
        return application, result

    async def list_workflows(self, session: AsyncSession, *, page: int, page_size: int):
        latest = (
            select(
                WorkflowRuleVersion.rule_id,
                func.max(WorkflowRuleVersion.version_number).label("version_number"),
            )
            .group_by(WorkflowRuleVersion.rule_id)
            .subquery()
        )
        q = (
            select(WorkflowRule, WorkflowRuleVersion)
            .join(latest, latest.c.rule_id == WorkflowRule.id)
            .join(
                WorkflowRuleVersion,
                and_(
                    WorkflowRuleVersion.rule_id == latest.c.rule_id,
                    WorkflowRuleVersion.version_number == latest.c.version_number,
                ),
            )
        )
        total = int(
            await session.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        )
        result = await session.execute(
            q.order_by(WorkflowRule.name).offset((page - 1) * page_size).limit(page_size)
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "version_id": v.id,
                "version_number": v.version_number,
                "status": v.status,
                "trigger_type": v.trigger_type,
                "conditions": v.conditions_json,
                "actions": v.actions_json,
                "created_at": r.created_at,
            }
            for r, v in result.all()
        ], total

    def validate_workflow(self, body: WorkflowRuleCreate | WorkflowRuleVersionCreate):
        if body.trigger_type not in ALLOWED_TRIGGERS:
            raise ValidationError("Unsupported workflow trigger")
        invalid = {str(action.get("type")) for action in body.actions} - ALLOWED_ACTIONS
        if invalid:
            raise ValidationError(
                "Workflow contains prohibited actions", {"actions": sorted(invalid)}
            )

    async def create_workflow(self, session: AsyncSession, user: User, body: WorkflowRuleCreate):
        self.validate_workflow(body)
        rule = WorkflowRule(name=body.name, description=body.description, created_by=user.id)
        session.add(rule)
        await session.flush()
        version = WorkflowRuleVersion(
            rule_id=rule.id,
            version_number=1,
            trigger_type=body.trigger_type,
            conditions_json=body.conditions,
            actions_json=body.actions,
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        await self._audit(session, "ctms_workflow_rule", rule.id, "create", user)
        return rule, version

    async def create_workflow_version(
        self,
        session: AsyncSession,
        user: User,
        rule_id: UUID,
        body: WorkflowRuleVersionCreate,
    ):
        self.validate_workflow(body)
        rule = await session.get(WorkflowRule, rule_id)
        if not rule:
            raise NotFoundError("Workflow rule not found")
        number = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(WorkflowRuleVersion.version_number), 0)).where(
                        WorkflowRuleVersion.rule_id == rule_id
                    )
                )
                or 0
            )
            + 1
        )
        version = WorkflowRuleVersion(
            rule_id=rule_id,
            version_number=number,
            trigger_type=body.trigger_type,
            conditions_json=body.conditions,
            actions_json=body.actions,
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        await self._audit(session, "ctms_workflow_rule", rule.id, "create_version", user)
        return rule, version

    async def set_workflow_status(
        self, session: AsyncSession, user: User, version_id: UUID, status: str, reason: str
    ):
        version = await session.get(WorkflowRuleVersion, version_id)
        if not version:
            raise NotFoundError("Workflow version not found")
        allowed = {
            "Draft": {"Published"},
            "Published": {"Paused", "Retired"},
            "Paused": {"Published", "Retired"},
            "Retired": set(),
        }
        if status not in allowed.get(version.status, set()):
            raise BusinessRuleError(f"Cannot transition workflow from {version.status} to {status}")
        if status == WorkflowStatus.PUBLISHED.value:
            previous = list(
                (
                    await session.scalars(
                        select(WorkflowRuleVersion).where(
                            WorkflowRuleVersion.rule_id == version.rule_id,
                            WorkflowRuleVersion.status == WorkflowStatus.PUBLISHED.value,
                            WorkflowRuleVersion.id != version.id,
                        )
                    )
                ).all()
            )
            for published in previous:
                published.status = WorkflowStatus.RETIRED.value
        version.status = status
        if status == "Published":
            version.published_at = utc_now()
            version.published_by = user.id
        await self._audit(
            session,
            "ctms_workflow_rule_version",
            version.id,
            f"transition:{status}",
            user,
            reason=reason,
        )
        await session.flush()
        return version

    async def execute_workflow_trigger(
        self,
        session: AsyncSession,
        *,
        trigger_type: str,
        source_type: str,
        source_id: UUID,
        occurrence_key: str,
        context: dict[str, Any],
        actor_id: UUID,
        correlation_id: str,
    ) -> list[WorkflowExecution]:
        """Execute matching published rules once for a stable occurrence key."""
        if trigger_type not in ALLOWED_TRIGGERS:
            raise ValidationError("Unsupported workflow trigger")
        rules = list(
            (
                await session.scalars(
                    select(WorkflowRuleVersion).where(
                        WorkflowRuleVersion.status == WorkflowStatus.PUBLISHED.value,
                        WorkflowRuleVersion.trigger_type == trigger_type,
                    )
                )
            ).all()
        )
        executions: list[WorkflowExecution] = []
        for rule in rules:
            if not all(context.get(key) == value for key, value in rule.conditions_json.items()):
                continue
            existing = await session.scalar(
                select(WorkflowExecution).where(
                    WorkflowExecution.rule_version_id == rule.id,
                    WorkflowExecution.source_type == source_type,
                    WorkflowExecution.source_id == source_id,
                    WorkflowExecution.occurrence_key == occurrence_key,
                )
            )
            if existing is not None:
                executions.append(existing)
                continue
            execution = WorkflowExecution(
                rule_version_id=rule.id,
                source_type=source_type,
                source_id=source_id,
                occurrence_key=occurrence_key,
                correlation_id=correlation_id,
                status="Running",
            )
            session.add(execution)
            await session.flush()
            results: list[dict[str, Any]] = []
            study_id = UUID(str(context["study_id"])) if context.get("study_id") else None
            site_id = UUID(str(context["site_id"])) if context.get("site_id") else None
            nested = await session.begin_nested()
            try:
                for action in rule.actions_json:
                    action_type = str(action.get("type"))
                    if action_type == "create_task":
                        if study_id is None:
                            raise ValidationError("create_task workflow action requires study_id")
                        task = await work_management_service.create_task(
                            session,
                            TaskCreate(
                                study_id=study_id,
                                site_id=site_id,
                                title=str(
                                    action.get("title")
                                    or context.get("title")
                                    or "Automated operational follow-up"
                                ),
                                description=action.get("description"),
                                owner_id=UUID(str(action["owner_id"]))
                                if action.get("owner_id")
                                else None,
                                priority=str(action.get("priority") or "Normal"),
                            ),
                            actor_id,
                            correlation_id=correlation_id,
                        )
                        results.append({"type": action_type, "task_id": str(task.id)})
                    elif action_type == "send_notification":
                        recipients = [UUID(str(value)) for value in action.get("user_ids", [])]
                        if not recipients and context.get("owner_id"):
                            recipients = [UUID(str(context["owner_id"]))]
                        notifications = await notification_service.create_ctms_notification(
                            session,
                            user_ids=recipients,
                            notification_type=str(
                                action.get("notification_type") or "ctms_workflow_alert"
                            ),
                            payload={
                                "source_type": source_type,
                                "source_id": str(source_id),
                                "message": action.get("message"),
                            },
                            study_id=study_id,
                            site_id=site_id,
                            correlation_id=correlation_id,
                        )
                        results.append(
                            {"type": action_type, "notification_count": len(notifications)}
                        )
                    elif action_type == "assign_owner":
                        if source_type != "operational_task" or not action.get("owner_id"):
                            raise ValidationError(
                                "assign_owner supports operational tasks and requires owner_id"
                            )
                        task = await work_management_service.update_task(
                            session,
                            source_id,
                            TaskUpdate(owner_id=UUID(str(action["owner_id"]))),
                            actor_id,
                            correlation_id=correlation_id,
                        )
                        results.append({"type": action_type, "task_id": str(task.id)})
                    elif action_type == "escalate_task":
                        if source_type != "operational_task":
                            raise ValidationError("escalate_task supports operational tasks only")
                        escalation = await work_management_service.create_escalation(
                            session,
                            {
                                "task_id": source_id,
                                "owner_id": UUID(str(action["owner_id"]))
                                if action.get("owner_id")
                                else None,
                                "reason": str(
                                    action.get("reason") or "Automated escalation rule matched"
                                ),
                                "deadline": action.get("deadline"),
                            },
                            actor_id,
                            correlation_id=correlation_id,
                        )
                        results.append({"type": action_type, "escalation_id": str(escalation.id)})
                    else:
                        raise ValidationError("Workflow contains a prohibited action")
                await nested.commit()
                execution.status = "Completed"
                execution.result_json = {"actions": results}
                execution.completed_at = utc_now()
            except Exception:
                await nested.rollback()
                execution.status = "Failed"
                execution.result_json = {"error": "Workflow action could not be completed"}
                execution.completed_at = utc_now()
            executions.append(execution)
        await session.flush()
        return executions

    async def create_assignment(
        self,
        session: AsyncSession,
        user: User,
        body: CRAAssignmentCreate,
        correlation_id: str,
        can_override: bool = False,
    ):
        self.assert_scope(await self.scope(session, user), body.study_id, body.site_id)
        cra = await session.get(User, body.user_id)
        if not cra or cra.status != UserStatus.active:
            raise ValidationError("CRA must be an active platform user")
        if body.site_id:
            site = await session.get(Site, body.site_id)
            if not site or site.study_id != body.study_id:
                raise ValidationError("Site does not belong to the study")
        overlap = await session.scalar(
            select(CRAAssignment.id).where(
                CRAAssignment.user_id == body.user_id,
                CRAAssignment.study_id == body.study_id,
                CRAAssignment.site_id == body.site_id,
                CRAAssignment.active.is_(True),
                CRAAssignment.effective_from <= body.effective_to
                if body.effective_to
                else CRAAssignment.effective_from <= date.max,
                or_(
                    CRAAssignment.effective_to.is_(None),
                    CRAAssignment.effective_to >= body.effective_from,
                ),
            )
        )
        if overlap:
            raise ConflictError("An overlapping CRA assignment already exists")
        week = body.effective_from - timedelta(days=body.effective_from.weekday())
        capacity = await session.scalar(
            select(CRACapacityPlan.capacity_hours).where(
                CRACapacityPlan.user_id == body.user_id, CRACapacityPlan.week_start == week
            )
        )
        allocated = Decimal(
            str(
                await session.scalar(
                    select(func.coalesce(func.sum(CRAAssignment.planned_hours_per_week), 0)).where(
                        CRAAssignment.user_id == body.user_id,
                        CRAAssignment.active.is_(True),
                        CRAAssignment.effective_from <= week + timedelta(days=6),
                        or_(
                            CRAAssignment.effective_to.is_(None), CRAAssignment.effective_to >= week
                        ),
                    )
                )
                or 0
            )
        )
        over = capacity is not None and allocated + body.planned_hours_per_week > Decimal(capacity)
        if over and not (body.allow_over_capacity and can_override):
            raise BusinessRuleError("Assignment exceeds the CRA's weekly capacity")
        data = body.model_dump(exclude={"allow_over_capacity", "over_capacity_reason"})
        item = CRAAssignment(
            **data,
            over_capacity_reason=body.over_capacity_reason if over else None,
            created_by=user.id,
            correlation_id=correlation_id,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            "ctms_cra_assignment",
            item.id,
            "create",
            user,
            study_id=item.study_id,
            site_id=item.site_id,
            reason=item.over_capacity_reason,
            correlation_id=correlation_id,
        )
        return item

    async def create_capacity(self, session: AsyncSession, user: User, body: CapacityPlanCreate):
        cra = await session.get(User, body.user_id)
        if not cra or cra.status != UserStatus.active:
            raise ValidationError("CRA must be an active platform user")
        existing = await session.scalar(
            select(CRACapacityPlan).where(
                CRACapacityPlan.user_id == body.user_id,
                CRACapacityPlan.week_start == body.week_start,
            )
        )
        if existing:
            existing.capacity_hours = body.capacity_hours
            existing.timezone = body.timezone
            existing.updated_by = user.id
            existing.updated_at = utc_now()
            item = existing
        else:
            item = CRACapacityPlan(**body.model_dump(), created_by=user.id)
            session.add(item)
        await session.flush()
        await self._audit(session, "ctms_cra_capacity", item.id, "upsert", user)
        return item

    async def create_exception(
        self, session: AsyncSession, user: User, body: AvailabilityExceptionCreate
    ):
        item = CRAAvailabilityException(**body.model_dump(), created_by=user.id)
        session.add(item)
        await session.flush()
        await self._audit(
            session, "ctms_cra_availability_exception", item.id, "create", user, reason=body.reason
        )
        return item


portfolio_management_service = PortfolioManagementService()

__all__ = ["DEFAULT_SCORE_WEIGHTS", "PortfolioManagementService", "portfolio_management_service"]
