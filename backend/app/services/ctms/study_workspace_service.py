"""Scoped queries and lifecycle rules for completed CTMS study workspaces."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_service
from app.core.ctms import Module
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone
from app.models.ctms.entity_management import (
    ManagedEntity,
    ManagedEntityType,
)
from app.models.ctms.financial import (
    FinancialBudget,
    FinancialBudgetLine,
    FinancialBudgetVersion,
    FinancialContract,
    FinancialContractVersion,
    FinancialInvoice,
    FinancialPayment,
    PayableItem,
)
from app.models.ctms.monitoring import MonitoringActionItem, MonitoringActivity, MonitoringFinding
from app.models.ctms.operational_site import (
    ActivationAction,
    OperationalSite,
    OperationalSiteStatus,
)
from app.models.ctms.portfolio_management import (
    CorrectiveActionPlan,
    SitePerformanceSnapshot,
)
from app.models.ctms.projection import CTMSOperationalProjection, ProjectionStatus
from app.models.ctms.study_workspace import (
    ICFSiteRollout,
    ICFVersion,
    KRIDefinition,
    KRIObservation,
    KRIVersion,
    ProtocolDeviationFollowUp,
    RiskAssessment,
    RiskAssessmentVersion,
    RiskItem,
    SiteCloseoutItem,
    SiteCloseoutPlan,
    SiteCloseoutTransition,
    StudyAmendment,
    StudyAmendmentImpact,
    StudyAmendmentTransition,
    StudyTeamAssignment,
    StudyTrackingLog,
    TrackingLogDefinition,
    TrackingLogDefinitionVersion,
    TrackingLogEntry,
    TrackingLogEntryRevision,
    utc_now,
)
from app.models.ctms.work import OperationalTask, TaskEscalation
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.audit import AuditEvent
from app.models.shared.identity import User, UserStatus
from app.schemas.ctms.study_workspace import (
    AmendmentCreate,
    AmendmentImpactCreate,
    CloseoutCreate,
    CloseoutItemCreate,
    CloseoutItemUpdate,
    ICFEvidenceUpdate,
    ICFRolloutCreate,
    ICFVersionCreate,
    KRICreate,
    KRIObservationCreate,
    KRIVersionCreate,
    ProtocolDeviationCreate,
    RiskAssessmentCreate,
    RiskAssessmentVersionCreate,
    RiskItemCreate,
    TeamAssignmentCreate,
    TeamAssignmentUpdate,
    TrackingDefinitionCreate,
    TrackingDefinitionVersionCreate,
    TrackingEntryCreate,
    TrackingEntryRevisionCreate,
    TrackingLogCreate,
    TransitionRequest,
)

TERMINAL_TASKS = {"Completed", "Cancelled", "Archived"}
TERMINAL_CAPAS = {"Closed", "Cancelled"}
AMENDMENT_TRANSITIONS = {
    "Draft": {"Impact Assessment", "Cancelled"},
    "Impact Assessment": {"Approved for Implementation", "Draft", "Cancelled"},
    "Approved for Implementation": {"In Progress", "Cancelled"},
    "In Progress": {"Completed", "Cancelled"},
    "Completed": {"In Progress"},
    "Cancelled": {"Draft"},
}
CLOSEOUT_TRANSITIONS = {
    "Not Started": {"In Progress", "Cancelled"},
    "In Progress": {"Ready for Review", "Cancelled"},
    "Ready for Review": {"Approved", "In Progress", "Cancelled"},
    "Approved": {"Closed", "In Progress"},
    "Closed": {"In Progress"},
    "Cancelled": {"Not Started"},
}
RACT_TRANSITIONS = {
    "Draft": {"Under Review"},
    "Under Review": {"Draft", "Approved"},
    "Approved": {"Retired"},
    "Retired": set(),
}
KRI_TRANSITIONS = {
    "Draft": {"Active"},
    "Active": {"Paused", "Retired"},
    "Paused": {"Active", "Retired"},
    "Retired": set(),
}
PD_TRANSITIONS = {
    "New": {"Under Review"},
    "Under Review": {"Action Required", "Resolved"},
    "Action Required": {"Resolved"},
    "Resolved": {"Closed", "Action Required"},
    "Closed": {"Under Review"},
}
ICF_TRANSITIONS = {
    "Planned": {"Distributed", "Withdrawn"},
    "Distributed": {"Site Acknowledged", "Withdrawn"},
    "Site Acknowledged": {"Training Complete", "Withdrawn"},
    "Training Complete": {"Effective", "Withdrawn"},
    "Effective": {"Superseded", "Withdrawn"},
    "Superseded": set(),
    "Withdrawn": set(),
}


def _name(first: str | None, last: str | None) -> str:
    return " ".join(filter(None, (first, last))).strip() or "Unknown user"


class StudyWorkspaceService:
    async def record_in_study(self, session: AsyncSession, model, record_id: UUID, study_id: UUID):
        item = await session.get(model, record_id)
        if not item or getattr(item, "deleted_at", None) or item.study_id != study_id:
            raise NotFoundError("Study workspace record not found")
        return item

    async def _study(self, session: AsyncSession, study_id: UUID) -> Study:
        study = await session.get(Study, study_id)
        if not study or study.deleted_at:
            raise NotFoundError("Study not found")
        return study

    async def _site(self, session: AsyncSession, study_id: UUID, site_id: UUID) -> Site:
        site = await session.get(Site, site_id)
        if not site or site.deleted_at or site.study_id != study_id:
            raise NotFoundError("Site not found in this study")
        return site

    @staticmethod
    async def _page(session: AsyncSession, query, page: int, page_size: int):
        total = int(
            await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
            or 0
        )
        rows = (await session.execute(query.offset((page - 1) * page_size).limit(page_size))).all()
        return rows, total

    async def _audit(
        self,
        session: AsyncSession,
        actor: User,
        entity_type: str,
        entity_id: UUID,
        action: str,
        *,
        study_id: UUID,
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

    async def summary(self, session: AsyncSession, study_id: UUID) -> dict[str, Any]:
        await self._study(session, study_id)
        now = datetime.now(UTC)
        site_count = int(
            await session.scalar(
                select(func.count(Site.id)).where(
                    Site.study_id == study_id, Site.deleted_at.is_(None)
                )
            )
            or 0
        )
        active_sites = int(
            await session.scalar(
                select(func.count(OperationalSite.id)).where(
                    OperationalSite.study_id == study_id,
                    OperationalSite.deleted_at.is_(None),
                    OperationalSite.status == "Active",
                )
            )
            or 0
        )
        open_tasks = int(
            await session.scalar(
                select(func.count(OperationalTask.id)).where(
                    OperationalTask.study_id == study_id,
                    OperationalTask.deleted_at.is_(None),
                    ~OperationalTask.status.in_(TERMINAL_TASKS),
                )
            )
            or 0
        )
        total_tasks = int(
            await session.scalar(
                select(func.count(OperationalTask.id)).where(
                    OperationalTask.study_id == study_id,
                    OperationalTask.deleted_at.is_(None),
                )
            )
            or 0
        )
        overdue_tasks = int(
            await session.scalar(
                select(func.count(OperationalTask.id)).where(
                    OperationalTask.study_id == study_id,
                    OperationalTask.deleted_at.is_(None),
                    OperationalTask.due_date < now,
                    ~OperationalTask.status.in_(TERMINAL_TASKS),
                )
            )
            or 0
        )
        monitoring_total = int(
            await session.scalar(
                select(func.count(MonitoringActivity.id)).where(
                    MonitoringActivity.study_id == study_id, MonitoringActivity.deleted_at.is_(None)
                )
            )
            or 0
        )
        monitoring_overdue = int(
            await session.scalar(
                select(func.count(MonitoringActivity.id)).where(
                    MonitoringActivity.study_id == study_id,
                    MonitoringActivity.deleted_at.is_(None),
                    MonitoringActivity.planned_date < now,
                    ~MonitoringActivity.status.in_(("Completed", "Cancelled")),
                )
            )
            or 0
        )
        open_findings = int(
            await session.scalar(
                select(func.count(MonitoringFinding.id)).where(
                    MonitoringFinding.study_id == study_id,
                    MonitoringFinding.deleted_at.is_(None),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                )
            )
            or 0
        )
        open_capas = int(
            await session.scalar(
                select(func.count(CorrectiveActionPlan.id)).where(
                    CorrectiveActionPlan.study_id == study_id,
                    CorrectiveActionPlan.deleted_at.is_(None),
                    ~CorrectiveActionPlan.status.in_(TERMINAL_CAPAS),
                )
            )
            or 0
        )
        contracts = int(
            await session.scalar(
                select(func.count(FinancialContract.id)).where(
                    FinancialContract.study_id == study_id
                )
            )
            or 0
        )
        enrollment_targets = {
            str(target_type): int(quantity or 0)
            for target_type, quantity in (
                await session.execute(
                    select(
                        EnrollmentTarget.target_type,
                        func.sum(EnrollmentTarget.target_quantity),
                    )
                    .where(
                        EnrollmentTarget.study_id == study_id,
                        EnrollmentTarget.deleted_at.is_(None),
                        EnrollmentTarget.status != "Cancelled",
                    )
                    .group_by(EnrollmentTarget.target_type)
                )
            ).all()
        }
        operational_subjects = int(
            await session.scalar(
                select(func.count(func.distinct(OperationalMilestone.subject_id))).where(
                    OperationalMilestone.study_id == study_id,
                    OperationalMilestone.deleted_at.is_(None),
                )
            )
            or 0
        )
        latest_contract_versions = (
            select(
                FinancialContractVersion.contract_id,
                func.max(FinancialContractVersion.version_number).label("version_number"),
            )
            .where(FinancialContractVersion.status.in_(("approved", "executed")))
            .group_by(FinancialContractVersion.contract_id)
            .subquery()
        )
        contracted = (
            await session.execute(
                select(
                    FinancialContract.currency,
                    func.coalesce(func.sum(FinancialContractVersion.total_value), 0),
                )
                .join(
                    FinancialContractVersion,
                    FinancialContractVersion.contract_id == FinancialContract.id,
                )
                .join(
                    latest_contract_versions,
                    and_(
                        latest_contract_versions.c.contract_id
                        == FinancialContractVersion.contract_id,
                        latest_contract_versions.c.version_number
                        == FinancialContractVersion.version_number,
                    ),
                )
                .where(
                    FinancialContract.study_id == study_id,
                )
                .group_by(FinancialContract.currency)
            )
        ).all()
        approved_budgets = (
            await session.execute(
                select(
                    FinancialBudget.currency,
                    func.coalesce(func.sum(FinancialBudgetLine.planned_amount), 0),
                )
                .join(
                    FinancialBudgetVersion,
                    FinancialBudgetVersion.budget_id == FinancialBudget.id,
                )
                .join(
                    FinancialBudgetLine,
                    FinancialBudgetLine.version_id == FinancialBudgetVersion.id,
                )
                .where(
                    FinancialBudget.study_id == study_id,
                    FinancialBudgetVersion.status == "approved",
                )
                .group_by(FinancialBudget.currency)
            )
        ).all()
        approved_payables = (
            await session.execute(
                select(PayableItem.currency, func.coalesce(func.sum(PayableItem.net_amount), 0))
                .where(
                    PayableItem.study_id == study_id,
                    PayableItem.status.in_(("approved", "partially_invoiced", "invoiced", "paid")),
                )
                .group_by(PayableItem.currency)
            )
        ).all()
        calculated_payables = (
            await session.execute(
                select(PayableItem.currency, func.coalesce(func.sum(PayableItem.net_amount), 0))
                .where(
                    PayableItem.study_id == study_id,
                    PayableItem.status == "calculated",
                )
                .group_by(PayableItem.currency)
            )
        ).all()
        invoiced = (
            await session.execute(
                select(
                    FinancialInvoice.currency,
                    func.coalesce(func.sum(FinancialInvoice.amount), 0),
                )
                .where(FinancialInvoice.study_id == study_id)
                .group_by(FinancialInvoice.currency)
            )
        ).all()
        paid = (
            await session.execute(
                select(
                    FinancialPayment.currency,
                    func.coalesce(func.sum(FinancialPayment.amount), 0),
                )
                .where(
                    FinancialPayment.study_id == study_id,
                    FinancialPayment.status == "settled",
                )
                .group_by(FinancialPayment.currency)
            )
        ).all()
        financials: dict[str, dict[str, Any]] = {}
        for field, values in (
            ("contracted_value", contracted),
            ("approved_budget", approved_budgets),
            ("calculated_payables", calculated_payables),
            ("approved_payables", approved_payables),
            ("invoiced", invoiced),
            ("paid", paid),
        ):
            for currency, amount in values:
                financials.setdefault(
                    currency,
                    {
                        "currency": currency,
                        "contracted_value": Decimal("0"),
                        "approved_budget": Decimal("0"),
                        "calculated_payables": Decimal("0"),
                        "approved_payables": Decimal("0"),
                        "invoiced": Decimal("0"),
                        "paid": Decimal("0"),
                    },
                )[field] = Decimal(str(amount))
        for values in financials.values():
            values["outstanding"] = max(values["invoiced"] - values["paid"], Decimal("0"))
            values["budget_variance"] = values["approved_budget"] - values["approved_payables"]
        return {
            "study_id": study_id,
            "site_count": site_count,
            "active_sites": active_sites,
            "enrollment": {
                "targets": enrollment_targets,
                "operational_subjects": operational_subjects,
            },
            "monitoring": {
                "visits": monitoring_total,
                "overdue_visits": monitoring_overdue,
                "open_findings": open_findings,
            },
            "work": {"total": total_tasks, "open": open_tasks, "overdue": overdue_tasks},
            "capas": {"open": open_capas},
            "contracts": {"total": contracts},
            "financials_by_currency": list(financials.values()),
            "generated_at": now,
        }

    async def health(self, session: AsyncSession, study_id: UUID) -> list[dict[str, Any]]:
        summary = await self.summary(session, study_id)
        task_source = await session.scalar(
            select(func.max(OperationalTask.updated_at)).where(
                OperationalTask.study_id == study_id,
                OperationalTask.deleted_at.is_(None),
            )
        )
        monitoring_sources = (
            await session.scalar(
                select(func.max(MonitoringActivity.updated_at)).where(
                    MonitoringActivity.study_id == study_id,
                    MonitoringActivity.deleted_at.is_(None),
                )
            ),
            await session.scalar(
                select(func.max(MonitoringFinding.updated_at)).where(
                    MonitoringFinding.study_id == study_id,
                    MonitoringFinding.deleted_at.is_(None),
                )
            ),
        )
        monitoring_source = max((value for value in monitoring_sources if value), default=None)
        capa_source = await session.scalar(
            select(func.max(CorrectiveActionPlan.updated_at)).where(
                CorrectiveActionPlan.study_id == study_id,
                CorrectiveActionPlan.deleted_at.is_(None),
            )
        )
        site_source = await session.scalar(
            select(func.max(OperationalSite.updated_at)).where(
                OperationalSite.study_id == study_id,
                OperationalSite.deleted_at.is_(None),
            )
        )
        dimensions = []

        def signal(
            name: str,
            red: bool,
            amber: bool,
            summary_text: str,
            path: str,
            factors: list[dict[str, Any]],
            source_date: datetime | None,
            unknown: bool = False,
        ):
            dimensions.append(
                {
                    "dimension": name,
                    "status": (
                        "Unknown" if unknown else "Red" if red else "Amber" if amber else "Green"
                    ),
                    "summary": summary_text,
                    "factors": factors,
                    "source_date": source_date,
                    "destination_path": f"/studies/{study_id}/ctms{path}",
                }
            )

        overdue = int(summary["work"]["overdue"])
        task_total = int(summary["work"]["total"])
        signal(
            "Work",
            overdue >= 5,
            overdue > 0,
            f"{overdue} overdue operational tasks",
            "/tasks",
            [
                {"metric": "overdue_tasks", "value": overdue},
                {"metric": "task_count", "value": task_total},
            ],
            task_source,
            unknown=task_total == 0,
        )
        visits = int(summary["monitoring"]["overdue_visits"])
        findings = int(summary["monitoring"]["open_findings"])
        signal(
            "Monitoring",
            visits >= 3 or findings >= 10,
            visits > 0 or findings > 0,
            f"{visits} overdue visits and {findings} open findings",
            "/monitoring",
            [
                {"metric": "overdue_visits", "value": visits},
                {"metric": "open_findings", "value": findings},
            ],
            monitoring_source,
            unknown=int(summary["monitoring"]["visits"]) == 0 and findings == 0,
        )
        capas = int(summary["capas"]["open"])
        signal(
            "CAPA",
            capas >= 3,
            capas > 0,
            f"{capas} open corrective action plans",
            "/tasks/capa",
            [{"metric": "open_capas", "value": capas}],
            capa_source,
        )
        site_count, active = int(summary["site_count"]), int(summary["active_sites"])
        signal(
            "Sites",
            site_count > 0 and active == 0,
            site_count > active,
            f"{active} of {site_count} sites active",
            "/sites/startup",
            [
                {"metric": "active_sites", "value": active},
                {"metric": "site_count", "value": site_count},
            ],
            site_source,
            unknown=site_count == 0,
        )
        dimensions.append(
            {
                "dimension": "Financial",
                "status": "Unknown" if not summary["financials_by_currency"] else "Green",
                "summary": "Financial position is reported separately by currency",
                "factors": summary["financials_by_currency"],
                "source_date": summary["generated_at"]
                if summary["financials_by_currency"]
                else None,
                "destination_path": f"/studies/{study_id}/ctms/financial-management",
            }
        )
        return dimensions

    async def activity(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        await self._study(session, study_id)
        q = (
            select(AuditEvent, User.first_name, User.last_name)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .where(AuditEvent.study_id == study_id, AuditEvent.module == "CTMS")
            .order_by(AuditEvent.timestamp.desc())
        )
        rows, total = await self._page(session, q, page, page_size)
        return [
            {
                "id": event.id,
                "timestamp": event.timestamp,
                "actor_id": event.actor_id,
                "actor_name": _name(first, last) if event.actor_id else "System",
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "action": event.action,
                "description": f"{event.action.replace('_', ' ').title()} {event.entity_type.replace('_', ' ')}",
                "site_id": event.site_id,
                "destination_path": self.destination(study_id, event.entity_type),
            }
            for event, first, last in rows
        ], total

    @staticmethod
    def destination(study_id: UUID, entity_type: str) -> str:
        if "monitor" in entity_type or "finding" in entity_type:
            return f"/studies/{study_id}/ctms/monitoring"
        if "capa" in entity_type:
            return f"/studies/{study_id}/ctms/tasks/capa"
        if "site" in entity_type or "activation" in entity_type:
            return f"/studies/{study_id}/ctms/sites"
        if "contract" in entity_type or "financial" in entity_type:
            return f"/studies/{study_id}/ctms/financial-management"
        return f"/studies/{study_id}/ctms"

    async def team(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        q = (
            select(StudyTeamAssignment, User.first_name, User.last_name, ManagedEntity.name)
            .outerjoin(User, User.id == StudyTeamAssignment.user_id)
            .outerjoin(ManagedEntity, ManagedEntity.id == StudyTeamAssignment.staff_entity_id)
            .where(
                StudyTeamAssignment.study_id == study_id, StudyTeamAssignment.deleted_at.is_(None)
            )
            .order_by(StudyTeamAssignment.active.desc(), StudyTeamAssignment.role)
        )
        rows, total = await self._page(session, q, page, page_size)
        return [
            {
                "id": item.id,
                "study_id": item.study_id,
                "site_id": item.site_id,
                "user_id": item.user_id,
                "staff_entity_id": item.staff_entity_id,
                "organization_id": item.organization_id,
                "display_name": _name(first, last)
                if item.user_id
                else entity_name or "Unknown staff",
                "role": item.role,
                "assignment_type": item.assignment_type,
                "responsibilities": item.responsibilities,
                "effective_from": item.effective_from,
                "effective_to": item.effective_to,
                "active": item.active,
                "version": item.version,
                "created_at": item.created_at,
                "destination_path": f"/studies/{study_id}/ctms/contacts",
            }
            for item, first, last, entity_name in rows
        ], total

    async def create_team(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: TeamAssignmentCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        if body.site_id:
            await self._site(session, study_id, body.site_id)
        if body.user_id:
            user = await session.get(User, body.user_id)
            if not user or user.status != UserStatus.active:
                raise ValidationError("Study team user must be active")
        if body.staff_entity_id:
            staff = await session.get(ManagedEntity, body.staff_entity_id)
            if not staff or staff.entity_type != ManagedEntityType.STAFF.value or not staff.active:
                raise ValidationError("Study team staff record must be active")
        if body.organization_id:
            organization = await session.get(ManagedEntity, body.organization_id)
            if (
                not organization
                or organization.entity_type != ManagedEntityType.PARTICIPATING_ORGANIZATION.value
                or not organization.active
            ):
                raise ValidationError("Study team organization must be active")
        duplicate = await session.scalar(
            select(StudyTeamAssignment.id).where(
                StudyTeamAssignment.study_id == study_id,
                StudyTeamAssignment.site_id == body.site_id,
                StudyTeamAssignment.user_id == body.user_id,
                StudyTeamAssignment.staff_entity_id == body.staff_entity_id,
                StudyTeamAssignment.role == body.role,
                StudyTeamAssignment.active.is_(True),
                StudyTeamAssignment.deleted_at.is_(None),
            )
        )
        if duplicate:
            raise ConflictError("An active matching study team assignment already exists")
        item = StudyTeamAssignment(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_study_team_assignment",
            item.id,
            "create",
            study_id=study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def update_team(
        self,
        session: AsyncSession,
        study_id: UUID,
        item_id: UUID,
        actor: User,
        body: TeamAssignmentUpdate,
        correlation: str,
    ):
        item = await self.record_in_study(session, StudyTeamAssignment, item_id, study_id)
        if item.version != body.expected_version:
            raise ConflictError("Study team assignment was updated by another user")
        values = body.model_dump(
            exclude={"reason", "expected_version"},
            exclude_unset=True,
        )
        effective_from = values.get("effective_from", item.effective_from)
        effective_to = values.get("effective_to", item.effective_to)
        if effective_to and effective_to < effective_from:
            raise ValidationError("effective_to must not precede effective_from")
        for field, value in values.items():
            setattr(item, field, value)
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_study_team_assignment",
            item.id,
            "update",
            study_id=study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def amendments(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        q = (
            select(StudyAmendment)
            .where(StudyAmendment.study_id == study_id, StudyAmendment.deleted_at.is_(None))
            .order_by(StudyAmendment.created_at.desc())
        )
        rows, total = await self._page(session, q, page, page_size)
        return [
            {
                **{
                    key: getattr(item, key)
                    for key in (
                        "id",
                        "study_id",
                        "amendment_number",
                        "title",
                        "source_module",
                        "source_reference_id",
                        "source_version",
                        "owner_id",
                        "effective_date",
                        "due_date",
                        "status",
                        "summary",
                        "version",
                        "created_at",
                    )
                },
                "destination_path": f"/studies/{study_id}/ctms/amendments",
            }
            for (item,) in rows
        ], total

    async def create_amendment(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: AmendmentCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        item = StudyAmendment(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_study_amendment",
            item.id,
            "create",
            study_id=study_id,
            correlation_id=correlation,
        )
        return item

    async def add_amendment_impact(
        self,
        session: AsyncSession,
        amendment_id: UUID,
        actor: User,
        body: AmendmentImpactCreate,
        correlation: str,
    ):
        amendment = await session.get(StudyAmendment, amendment_id)
        if not amendment or amendment.deleted_at:
            raise NotFoundError("Study amendment not found")
        if body.site_id:
            await self._site(session, amendment.study_id, body.site_id)
        item = StudyAmendmentImpact(
            amendment_id=amendment.id,
            study_id=amendment.study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_study_amendment_impact",
            item.id,
            "create",
            study_id=amendment.study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def transition_amendment(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(StudyAmendment, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Study amendment not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("Study amendment was updated by another user")
        if body.status not in AMENDMENT_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError(
                f"Cannot transition amendment from {item.status} to {body.status}"
            )
        if body.status == "Completed":
            open_impacts = int(
                await session.scalar(
                    select(func.count(StudyAmendmentImpact.id)).where(
                        StudyAmendmentImpact.amendment_id == item.id,
                        StudyAmendmentImpact.deleted_at.is_(None),
                        ~StudyAmendmentImpact.status.in_(("Completed", "Cancelled")),
                    )
                )
                or 0
            )
            if open_impacts:
                raise BusinessRuleError("All amendment impacts must be completed before closure")
            item.completed_at = utc_now()
        elif item.status in {"Completed", "Cancelled"}:
            item.completed_at = None
        old = item.status
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        session.add(
            StudyAmendmentTransition(
                amendment_id=item.id,
                from_status=old,
                to_status=body.status,
                reason=body.reason,
                actor_id=actor.id,
                correlation_id=correlation,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_study_amendment",
            item.id,
            f"transition:{old}->{body.status}",
            study_id=item.study_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def sites(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        latest = (
            select(
                SitePerformanceSnapshot.site_id,
                func.max(SitePerformanceSnapshot.snapshot_date).label("max_date"),
            )
            .group_by(SitePerformanceSnapshot.site_id)
            .subquery()
        )
        open_actions = (
            select(ActivationAction.site_id, func.count(ActivationAction.id).label("count"))
            .where(
                ActivationAction.deleted_at.is_(None),
                ~ActivationAction.status.in_(("Completed", "Cancelled", "Archived")),
            )
            .group_by(ActivationAction.site_id)
            .subquery()
        )
        q = (
            select(
                Site, OperationalSite, SitePerformanceSnapshot.overall_score, open_actions.c.count
            )
            .outerjoin(
                OperationalSite,
                and_(OperationalSite.site_id == Site.id, OperationalSite.deleted_at.is_(None)),
            )
            .outerjoin(latest, latest.c.site_id == Site.id)
            .outerjoin(
                SitePerformanceSnapshot,
                and_(
                    SitePerformanceSnapshot.site_id == Site.id,
                    SitePerformanceSnapshot.snapshot_date == latest.c.max_date,
                ),
            )
            .outerjoin(open_actions, open_actions.c.site_id == Site.id)
            .where(Site.study_id == study_id, Site.deleted_at.is_(None))
            .order_by(Site.site_number)
        )
        rows, total = await self._page(session, q, page, page_size)
        return [
            {
                "site_id": site.id,
                "site_number": site.site_number,
                "site_name": site.name,
                "country": site.country,
                "region": site.region,
                "operational_status": profile.status if profile else None,
                "planned_activation_date": profile.planned_activation_date if profile else None,
                "open_activation_actions": int(action_count or 0),
                "performance_score": score,
                "destination_path": f"/sites/{site.id}/ctms",
            }
            for site, profile, score, action_count in rows
        ], total

    async def closeouts(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        required = (
            select(
                SiteCloseoutItem.plan_id,
                func.count(SiteCloseoutItem.id).label("required"),
                func.sum(func.cast(SiteCloseoutItem.status == "Completed", Integer)).label(
                    "completed"
                ),
            )
            .where(SiteCloseoutItem.required.is_(True), SiteCloseoutItem.deleted_at.is_(None))
            .group_by(SiteCloseoutItem.plan_id)
            .subquery()
        )
        critical_findings = (
            select(
                MonitoringFinding.site_id,
                func.count(MonitoringFinding.id).label("critical_findings"),
            )
            .where(
                MonitoringFinding.deleted_at.is_(None),
                MonitoringFinding.severity.in_(("Critical", "High")),
                ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
            )
            .group_by(MonitoringFinding.site_id)
            .subquery()
        )
        open_capas = (
            select(
                CorrectiveActionPlan.site_id,
                func.count(CorrectiveActionPlan.id).label("open_capas"),
            )
            .where(
                CorrectiveActionPlan.deleted_at.is_(None),
                ~CorrectiveActionPlan.status.in_(TERMINAL_CAPAS),
            )
            .group_by(CorrectiveActionPlan.site_id)
            .subquery()
        )
        q = (
            select(
                SiteCloseoutPlan,
                Site.site_number,
                Site.name,
                required.c.required,
                required.c.completed,
                critical_findings.c.critical_findings,
                open_capas.c.open_capas,
                OperationalSite.id.label("profile_id"),
            )
            .join(Site, Site.id == SiteCloseoutPlan.site_id)
            .outerjoin(required, required.c.plan_id == SiteCloseoutPlan.id)
            .outerjoin(critical_findings, critical_findings.c.site_id == SiteCloseoutPlan.site_id)
            .outerjoin(open_capas, open_capas.c.site_id == SiteCloseoutPlan.site_id)
            .outerjoin(
                OperationalSite,
                and_(
                    OperationalSite.site_id == SiteCloseoutPlan.site_id,
                    OperationalSite.deleted_at.is_(None),
                ),
            )
            .where(SiteCloseoutPlan.study_id == study_id, SiteCloseoutPlan.deleted_at.is_(None))
            .order_by(SiteCloseoutPlan.planned_date.asc().nullslast())
        )
        rows, total = await self._page(session, q, page, page_size)
        result = []
        for item, number, name, req, done, finding_count, capa_count, profile_id in rows:
            blockers = []
            if not req:
                blockers.append("At least one required closeout item is required")
            incomplete = int(req or 0) - int(done or 0)
            if incomplete:
                blockers.append(f"{incomplete} required closeout items are incomplete")
            if finding_count:
                blockers.append(f"{finding_count} high or critical findings remain open")
            if capa_count:
                blockers.append(f"{capa_count} CAPA records remain open")
            if not profile_id:
                blockers.append("An operational site profile is required")
            result.append(
                {
                    "id": item.id,
                    "study_id": item.study_id,
                    "site_id": item.site_id,
                    "site_label": " — ".join(filter(None, (number, name))),
                    "owner_id": item.owner_id,
                    "planned_date": item.planned_date,
                    "status": item.status,
                    "required_items": int(req or 0),
                    "completed_required_items": int(done or 0),
                    "blockers": blockers,
                    "version": item.version,
                    "created_at": item.created_at,
                    "destination_path": f"/studies/{study_id}/ctms/sites/closeout",
                }
            )
        return result, total

    async def closeout_blockers(self, session: AsyncSession, item: SiteCloseoutPlan) -> list[str]:
        blockers = []
        required = int(
            await session.scalar(
                select(func.count(SiteCloseoutItem.id)).where(
                    SiteCloseoutItem.plan_id == item.id,
                    SiteCloseoutItem.deleted_at.is_(None),
                    SiteCloseoutItem.required.is_(True),
                )
            )
            or 0
        )
        if required == 0:
            blockers.append("At least one required closeout item is required")
        incomplete = int(
            await session.scalar(
                select(func.count(SiteCloseoutItem.id)).where(
                    SiteCloseoutItem.plan_id == item.id,
                    SiteCloseoutItem.deleted_at.is_(None),
                    SiteCloseoutItem.required.is_(True),
                    SiteCloseoutItem.status != "Completed",
                )
            )
            or 0
        )
        if incomplete:
            blockers.append(f"{incomplete} required closeout items are incomplete")
        critical_findings = int(
            await session.scalar(
                select(func.count(MonitoringFinding.id)).where(
                    MonitoringFinding.site_id == item.site_id,
                    MonitoringFinding.deleted_at.is_(None),
                    MonitoringFinding.severity.in_(("Critical", "High")),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                )
            )
            or 0
        )
        if critical_findings:
            blockers.append(f"{critical_findings} high or critical findings remain open")
        critical_capas = int(
            await session.scalar(
                select(func.count(CorrectiveActionPlan.id)).where(
                    CorrectiveActionPlan.site_id == item.site_id,
                    CorrectiveActionPlan.deleted_at.is_(None),
                    ~CorrectiveActionPlan.status.in_(TERMINAL_CAPAS),
                )
            )
            or 0
        )
        if critical_capas:
            blockers.append(f"{critical_capas} CAPA records remain open")
        profile = await session.scalar(
            select(OperationalSite.id).where(
                OperationalSite.site_id == item.site_id,
                OperationalSite.deleted_at.is_(None),
            )
        )
        if not profile:
            blockers.append("An operational site profile is required")
        return blockers

    async def create_closeout(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: CloseoutCreate,
        correlation: str,
    ):
        await self._site(session, study_id, body.site_id)
        if await session.scalar(
            select(SiteCloseoutPlan.id).where(
                SiteCloseoutPlan.site_id == body.site_id, SiteCloseoutPlan.deleted_at.is_(None)
            )
        ):
            raise ConflictError("A site closeout plan already exists")
        item = SiteCloseoutPlan(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_site_closeout",
            item.id,
            "create",
            study_id=study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def add_closeout_item(
        self,
        session: AsyncSession,
        plan_id: UUID,
        actor: User,
        body: CloseoutItemCreate,
        correlation: str,
    ):
        plan = await session.get(SiteCloseoutPlan, plan_id)
        if not plan or plan.deleted_at:
            raise NotFoundError("Site closeout plan not found")
        item = SiteCloseoutItem(
            plan_id=plan.id,
            study_id=plan.study_id,
            site_id=plan.site_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_site_closeout_item",
            item.id,
            "create",
            study_id=plan.study_id,
            site_id=plan.site_id,
            correlation_id=correlation,
        )
        return item

    async def update_closeout_item(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: CloseoutItemUpdate,
        correlation: str,
    ):
        item = await session.get(SiteCloseoutItem, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Site closeout item not found")
        if item.version != body.expected_version:
            raise ConflictError("Closeout item was updated by another user")
        target_status = body.status or item.status
        target_evidence = (
            body.evidence_references
            if body.evidence_references is not None
            else item.evidence_references
        )
        if target_status == "Completed" and not target_evidence:
            raise BusinessRuleError("Completion evidence is required")
        for field, value in body.model_dump(
            exclude={"reason", "expected_version"}, exclude_none=True
        ).items():
            setattr(item, field, value)
        if body.status == "Completed":
            item.completed_at = utc_now()
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_site_closeout_item",
            item.id,
            "update",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def transition_closeout(
        self,
        session: AsyncSession,
        plan_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(SiteCloseoutPlan, plan_id)
        if not item or item.deleted_at:
            raise NotFoundError("Site closeout plan not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("Closeout plan was updated by another user")
        if body.status not in CLOSEOUT_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError(
                f"Cannot transition closeout from {item.status} to {body.status}"
            )
        if body.status in {"Approved", "Closed"}:
            blockers = await self.closeout_blockers(session, item)
            if blockers:
                raise BusinessRuleError(
                    "Site closeout has unresolved blockers", {"blockers": blockers}
                )
        old = item.status
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        if body.status == "Closed":
            item.closed_at = utc_now()
            item.closure_reason = body.reason
            profile = await session.scalar(
                select(OperationalSite).where(
                    OperationalSite.site_id == item.site_id, OperationalSite.deleted_at.is_(None)
                )
            )
            if profile:
                profile.status = OperationalSiteStatus.CLOSED.value
                profile.updated_by = actor.id
                profile.updated_at = utc_now()
        elif old == "Closed":
            item.closed_at = None
            item.closure_reason = None
            profile = await session.scalar(
                select(OperationalSite).where(
                    OperationalSite.site_id == item.site_id,
                    OperationalSite.deleted_at.is_(None),
                )
            )
            if profile:
                profile.status = OperationalSiteStatus.IN_PROGRESS.value
                profile.updated_by = actor.id
                profile.updated_at = utc_now()
        session.add(
            SiteCloseoutTransition(
                plan_id=item.id,
                from_status=old,
                to_status=body.status,
                reason=body.reason,
                actor_id=actor.id,
                correlation_id=correlation,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_site_closeout",
            item.id,
            f"transition:{old}->{body.status}",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def action_items(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        now = utc_now()
        rows: list[dict[str, Any]] = []
        for item in (
            await session.scalars(
                select(MonitoringActionItem).where(
                    MonitoringActionItem.study_id == study_id,
                    MonitoringActionItem.deleted_at.is_(None),
                    MonitoringActionItem.status != "Completed",
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "monitoring_action",
                    item.title,
                    f"/studies/{study_id}/ctms/monitoring/findings",
                    now,
                )
            )
        for item in (
            await session.scalars(
                select(ActivationAction).where(
                    ActivationAction.study_id == study_id,
                    ActivationAction.deleted_at.is_(None),
                    ~ActivationAction.status.in_(("Completed", "Cancelled", "Archived")),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "activation_action",
                    item.action_type,
                    f"/studies/{study_id}/ctms/sites/startup",
                    now,
                    due="planned_date",
                )
            )
        for item in (
            await session.scalars(
                select(StudyAmendmentImpact).where(
                    StudyAmendmentImpact.study_id == study_id,
                    StudyAmendmentImpact.deleted_at.is_(None),
                    ~StudyAmendmentImpact.status.in_(("Completed", "Cancelled")),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "amendment_impact",
                    item.description[:255],
                    f"/studies/{study_id}/ctms/amendments",
                    now,
                    due="due_date",
                )
            )
        for item in (
            await session.scalars(
                select(SiteCloseoutItem).where(
                    SiteCloseoutItem.study_id == study_id,
                    SiteCloseoutItem.deleted_at.is_(None),
                    ~SiteCloseoutItem.status.in_(("Completed", "Cancelled")),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "site_closeout_item",
                    item.title,
                    f"/studies/{study_id}/ctms/sites/closeout",
                    now,
                    due="due_date",
                )
            )
        for item in (
            await session.scalars(
                select(OperationalTask).where(
                    OperationalTask.study_id == study_id,
                    OperationalTask.deleted_at.is_(None),
                    ~OperationalTask.status.in_(TERMINAL_TASKS),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "operational_task",
                    item.title,
                    f"/studies/{study_id}/ctms/tasks",
                    now,
                    due="due_date",
                    severity=item.priority,
                )
            )
        rows.sort(key=lambda row: (not row["is_overdue"], row["due_at"] or now))
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    @staticmethod
    def action_row(
        item,
        source: str,
        title: str,
        path: str,
        now: datetime,
        *,
        due: str = "due_date",
        severity: str | None = None,
    ):
        due_at = getattr(item, due, None)
        if isinstance(due_at, date) and not isinstance(due_at, datetime):
            due_at = datetime.combine(due_at, datetime.min.time(), tzinfo=UTC)
        return {
            "source_type": source,
            "source_id": item.id,
            "study_id": item.study_id,
            "site_id": getattr(item, "site_id", None),
            "title": title,
            "status": item.status,
            "severity": severity,
            "owner_id": getattr(item, "owner_id", None)
            or getattr(item, "responsible_user_id", None),
            "due_at": due_at,
            "is_overdue": bool(due_at and due_at < now),
            "permitted_actions": ["open", "transition"],
            "destination_path": path,
        }

    async def issues(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        now = utc_now()
        rows = []
        for item in (
            await session.scalars(
                select(MonitoringFinding).where(
                    MonitoringFinding.study_id == study_id,
                    MonitoringFinding.deleted_at.is_(None),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "monitoring_finding",
                    item.description[:255],
                    f"/studies/{study_id}/ctms/monitoring/findings",
                    now,
                    severity=item.severity,
                )
            )
        for item in (
            await session.scalars(
                select(OperationalTask).where(
                    OperationalTask.study_id == study_id,
                    OperationalTask.deleted_at.is_(None),
                    or_(
                        OperationalTask.status == "Blocked",
                        and_(
                            OperationalTask.due_date < now,
                            ~OperationalTask.status.in_(TERMINAL_TASKS),
                        ),
                    ),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "operational_task",
                    item.title,
                    f"/studies/{study_id}/ctms/tasks",
                    now,
                    severity=item.priority,
                )
            )
        for item in (
            await session.scalars(
                select(ProtocolDeviationFollowUp).where(
                    ProtocolDeviationFollowUp.study_id == study_id,
                    ProtocolDeviationFollowUp.deleted_at.is_(None),
                    ~ProtocolDeviationFollowUp.status.in_(("Closed",)),
                )
            )
        ).all():
            rows.append(
                self.action_row(
                    item,
                    "protocol_deviation",
                    item.approved_reference,
                    f"/studies/{study_id}/ctms/protocol-deviations",
                    now,
                    severity=item.severity,
                )
            )
        breaches = (
            await session.execute(
                select(KRIObservation, KRIDefinition.name)
                .join(KRIDefinition, KRIDefinition.id == KRIObservation.kri_id)
                .where(
                    KRIObservation.study_id == study_id, KRIObservation.level.in_(("Amber", "Red"))
                )
            )
        ).all()
        for item, name in breaches:
            rows.append(
                {
                    "source_type": "kri_breach",
                    "source_id": item.id,
                    "study_id": study_id,
                    "site_id": item.site_id,
                    "title": name,
                    "status": item.level,
                    "severity": item.level,
                    "owner_id": None,
                    "due_at": None,
                    "is_overdue": False,
                    "permitted_actions": ["open"],
                    "destination_path": f"/studies/{study_id}/ctms/rbm/kri",
                }
            )
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    async def escalations(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        q = (
            select(TaskEscalation, OperationalTask)
            .join(OperationalTask, OperationalTask.id == TaskEscalation.task_id)
            .where(OperationalTask.study_id == study_id)
            .order_by(TaskEscalation.deadline.asc().nullslast())
        )
        rows, total = await self._page(session, q, page, page_size)
        now = utc_now()
        return [
            {
                "id": esc.id,
                "task_id": task.id,
                "study_id": study_id,
                "site_id": task.site_id,
                "title": task.title,
                "status": esc.status,
                "reason": esc.reason,
                "owner_id": esc.owner_id,
                "due_at": esc.deadline,
                "is_overdue": bool(
                    esc.deadline
                    and esc.deadline < now
                    and esc.status not in ("Resolved", "Cancelled")
                ),
                "destination_path": f"/studies/{study_id}/ctms/tasks",
            }
            for esc, task in rows
        ], total

    async def startup(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        await self._study(session, study_id)
        query = (
            select(ActivationAction)
            .where(
                ActivationAction.study_id == study_id,
                ActivationAction.deleted_at.is_(None),
            )
            .order_by(ActivationAction.planned_date.asc().nullslast())
        )
        rows, total = await self._page(session, query, page, page_size)
        return [row[0] for row in rows], total

    async def racts(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        counts = (
            select(
                RiskAssessmentVersion.assessment_id,
                func.count(RiskItem.id).label("item_count"),
                func.max(RiskItem.risk_score).label("highest"),
            )
            .join(RiskItem, RiskItem.version_id == RiskAssessmentVersion.id)
            .group_by(RiskAssessmentVersion.assessment_id)
            .subquery()
        )
        query = (
            select(RiskAssessment, counts.c.item_count, counts.c.highest)
            .outerjoin(counts, counts.c.assessment_id == RiskAssessment.id)
            .where(RiskAssessment.study_id == study_id, RiskAssessment.deleted_at.is_(None))
            .order_by(RiskAssessment.updated_at.desc())
        )
        rows, total = await self._page(session, query, page, page_size)
        return [
            {
                "id": item.id,
                "study_id": item.study_id,
                "name": item.name,
                "owner_id": item.owner_id,
                "current_version": item.current_version,
                "status": item.status,
                "version": item.version,
                "risk_item_count": int(count or 0),
                "highest_risk_score": highest,
                "created_at": item.created_at,
                "destination_path": f"/studies/{study_id}/ctms/monitoring/ract",
            }
            for item, count, highest in rows
        ], total

    async def kris(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        latest = (
            select(
                KRIObservation.kri_id,
                func.max(KRIObservation.observed_at).label("latest_at"),
            )
            .group_by(KRIObservation.kri_id)
            .subquery()
        )
        query = (
            select(
                KRIDefinition,
                KRIObservation.value,
                KRIObservation.level,
                KRIObservation.observed_at,
            )
            .outerjoin(latest, latest.c.kri_id == KRIDefinition.id)
            .outerjoin(
                KRIObservation,
                and_(
                    KRIObservation.kri_id == KRIDefinition.id,
                    KRIObservation.observed_at == latest.c.latest_at,
                ),
            )
            .where(KRIDefinition.study_id == study_id, KRIDefinition.deleted_at.is_(None))
            .order_by(KRIDefinition.code)
        )
        rows, total = await self._page(session, query, page, page_size)
        return [
            {
                "id": item.id,
                "study_id": item.study_id,
                "code": item.code,
                "name": item.name,
                "owner_id": item.owner_id,
                "current_version": item.current_version,
                "status": item.status,
                "latest_value": value,
                "latest_level": level,
                "latest_observed_at": observed_at,
                "version": item.version,
                "created_at": item.created_at,
                "destination_path": f"/studies/{study_id}/ctms/monitoring/kris",
            }
            for item, value, level, observed_at in rows
        ], total

    async def protocol_deviations(
        self, session: AsyncSession, study_id: UUID, page: int, page_size: int
    ):
        rows, total = await self.simple_list(
            session,
            ProtocolDeviationFollowUp,
            study_id,
            page,
            page_size,
            ProtocolDeviationFollowUp.updated_at.desc(),
        )
        fields = (
            "id",
            "study_id",
            "site_id",
            "projection_id",
            "source_record_id",
            "approved_reference",
            "classification",
            "severity",
            "owner_id",
            "due_date",
            "status",
            "action_summary",
            "version",
            "created_at",
        )
        return [
            {
                **{key: getattr(item, key) for key in fields},
                "destination_path": f"/studies/{study_id}/ctms/compliance/protocol-deviations",
            }
            for (item,) in rows
        ], total

    async def icf_rollouts(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        query = (
            select(ICFSiteRollout, ICFVersion, Site.site_number, Site.name)
            .join(ICFVersion, ICFVersion.id == ICFSiteRollout.icf_version_id)
            .join(Site, Site.id == ICFSiteRollout.site_id)
            .where(ICFSiteRollout.study_id == study_id, ICFSiteRollout.deleted_at.is_(None))
            .order_by(ICFSiteRollout.updated_at.desc())
        )
        rows, total = await self._page(session, query, page, page_size)
        return [
            {
                "id": item.id,
                "icf_version_id": item.icf_version_id,
                "study_id": item.study_id,
                "site_id": item.site_id,
                "site_label": " — ".join(filter(None, (number, name))),
                "version_code": version.version_code,
                "country_code": version.country_code,
                "owner_id": item.owner_id,
                "status": item.status,
                "evidence_references": item.evidence_references,
                "version": item.version,
                "created_at": item.created_at,
                "destination_path": f"/studies/{study_id}/ctms/compliance/icf-rollout",
            }
            for item, version, number, name in rows
        ], total

    async def tracking_logs(self, session: AsyncSession, study_id: UUID, page: int, page_size: int):
        counts = (
            select(TrackingLogEntry.log_id, func.count(TrackingLogEntry.id).label("count"))
            .where(TrackingLogEntry.deleted_at.is_(None))
            .group_by(TrackingLogEntry.log_id)
            .subquery()
        )
        query = (
            select(StudyTrackingLog, counts.c.count)
            .outerjoin(counts, counts.c.log_id == StudyTrackingLog.id)
            .where(StudyTrackingLog.study_id == study_id, StudyTrackingLog.deleted_at.is_(None))
            .order_by(StudyTrackingLog.updated_at.desc())
        )
        rows, total = await self._page(session, query, page, page_size)
        return [
            {
                "id": item.id,
                "study_id": item.study_id,
                "definition_version_id": item.definition_version_id,
                "name": item.name,
                "owner_id": item.owner_id,
                "status": item.status,
                "entry_count": int(count or 0),
                "version": item.version,
                "created_at": item.created_at,
                "destination_path": f"/studies/{study_id}/ctms/compliance/tracking-logs",
            }
            for item, count in rows
        ], total

    async def simple_list(
        self, session: AsyncSession, model, study_id: UUID, page: int, page_size: int, order=None
    ):
        q = select(model).where(model.study_id == study_id, model.deleted_at.is_(None))
        if order is not None:
            q = q.order_by(order)
        return await self._page(session, q, page, page_size)

    async def create_ract(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: RiskAssessmentCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        item = RiskAssessment(
            study_id=study_id,
            name=body.name,
            owner_id=body.owner_id,
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        session.add(
            RiskAssessmentVersion(
                assessment_id=item.id,
                version_number=1,
                rationale=body.rationale,
                created_by=actor.id,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_risk_assessment",
            item.id,
            "create",
            study_id=study_id,
            correlation_id=correlation,
        )
        return item

    async def add_risk_item(
        self,
        session: AsyncSession,
        assessment_id: UUID,
        actor: User,
        body: RiskItemCreate,
        correlation: str,
    ):
        assessment = await session.get(RiskAssessment, assessment_id)
        if not assessment or assessment.deleted_at:
            raise NotFoundError("Risk assessment not found")
        version = await session.scalar(
            select(RiskAssessmentVersion).where(
                RiskAssessmentVersion.assessment_id == assessment.id,
                RiskAssessmentVersion.version_number == assessment.current_version,
            )
        )
        if not version or assessment.status not in ("Draft", "Under Review"):
            raise BusinessRuleError("Approved risk assessment versions are immutable")
        item = RiskItem(
            version_id=version.id,
            study_id=assessment.study_id,
            risk_score=body.probability * body.impact * body.detectability,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_risk_item",
            item.id,
            "create",
            study_id=assessment.study_id,
            correlation_id=correlation,
        )
        return item

    async def create_ract_version(
        self,
        session: AsyncSession,
        assessment_id: UUID,
        actor: User,
        body: RiskAssessmentVersionCreate,
        correlation: str,
    ):
        item = await session.get(RiskAssessment, assessment_id)
        if not item or item.deleted_at:
            raise NotFoundError("Risk assessment not found")
        if item.version != body.expected_version:
            raise ConflictError("Risk assessment was updated by another user")
        if item.status not in {"Approved", "Retired"}:
            raise BusinessRuleError("A new RACT version can only follow an approved version")
        item.current_version += 1
        item.status = "Draft"
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        version = RiskAssessmentVersion(
            assessment_id=item.id,
            version_number=item.current_version,
            rationale=body.rationale,
            created_by=actor.id,
        )
        session.add(version)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_risk_assessment",
            item.id,
            "new_version",
            study_id=item.study_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return version

    async def transition_ract(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(RiskAssessment, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Risk assessment not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("Risk assessment was updated by another user")
        if body.status not in RACT_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError("Invalid RACT transition")
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        version = await session.scalar(
            select(RiskAssessmentVersion).where(
                RiskAssessmentVersion.assessment_id == item.id,
                RiskAssessmentVersion.version_number == item.current_version,
            )
        )
        if version:
            version.status = body.status
            version.approved_by = actor.id if body.status == "Approved" else version.approved_by
            version.approved_at = utc_now() if body.status == "Approved" else version.approved_at
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_risk_assessment",
            item.id,
            f"transition:{body.status}",
            study_id=item.study_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def create_kri(
        self, session: AsyncSession, study_id: UUID, actor: User, body: KRICreate, correlation: str
    ):
        await self._study(session, study_id)
        base = body.model_dump(
            exclude={"source_type", "unit", "amber_threshold", "red_threshold", "direction"}
        )
        item = KRIDefinition(
            study_id=study_id,
            **base,
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        session.add(
            KRIVersion(
                kri_id=item.id,
                version_number=1,
                source_type=body.source_type,
                unit=body.unit,
                amber_threshold=body.amber_threshold,
                red_threshold=body.red_threshold,
                direction=body.direction,
                created_by=actor.id,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_kri",
            item.id,
            "create",
            study_id=study_id,
            correlation_id=correlation,
        )
        return item

    async def observe_kri(
        self,
        session: AsyncSession,
        kri_id: UUID,
        actor: User,
        body: KRIObservationCreate,
        correlation: str,
    ):
        kri = await session.get(KRIDefinition, kri_id)
        if not kri or kri.deleted_at:
            raise NotFoundError("KRI not found")
        if kri.status != "Active":
            raise BusinessRuleError("Only active KRIs accept observations")
        version = await session.scalar(
            select(KRIVersion).where(
                KRIVersion.kri_id == kri.id, KRIVersion.version_number == kri.current_version
            )
        )
        if not version:
            raise NotFoundError("KRI version not found")
        if body.site_id:
            await self._site(session, kri.study_id, body.site_id)
        if version.direction == "above":
            level = (
                "Red"
                if body.value >= version.red_threshold
                else "Amber"
                if body.value >= version.amber_threshold
                else "Green"
            )
        else:
            level = (
                "Red"
                if body.value <= version.red_threshold
                else "Amber"
                if body.value <= version.amber_threshold
                else "Green"
            )
        item = KRIObservation(
            kri_id=kri.id,
            version_id=version.id,
            study_id=kri.study_id,
            level=level,
            **body.model_dump(),
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_kri_observation",
            item.id,
            "create",
            study_id=kri.study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def create_kri_version(
        self,
        session: AsyncSession,
        kri_id: UUID,
        actor: User,
        body: KRIVersionCreate,
        correlation: str,
    ):
        item = await session.get(KRIDefinition, kri_id)
        if not item or item.deleted_at:
            raise NotFoundError("KRI not found")
        if item.version != body.expected_version:
            raise ConflictError("KRI was updated by another user")
        if item.status not in {"Paused", "Retired"}:
            raise BusinessRuleError("Pause or retire the current KRI before creating a version")
        item.current_version += 1
        item.status = "Draft"
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        version = KRIVersion(
            kri_id=item.id,
            version_number=item.current_version,
            **body.model_dump(exclude={"reason", "expected_version"}),
            created_by=actor.id,
        )
        session.add(version)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_kri",
            item.id,
            "new_version",
            study_id=item.study_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return version

    async def transition_kri(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(KRIDefinition, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("KRI not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("KRI was updated by another user")
        if body.status not in KRI_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError("Invalid KRI transition")
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_kri",
            item.id,
            f"transition:{body.status}",
            study_id=item.study_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def create_pd(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: ProtocolDeviationCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        if body.site_id:
            await self._site(session, study_id, body.site_id)
        projection = await session.get(CTMSOperationalProjection, body.projection_id)
        if (
            not projection
            or projection.deleted_at
            or projection.status != ProjectionStatus.CURRENT
            or projection.source_module != "EDC"
            or projection.study_id != study_id
            or projection.site_id != body.site_id
            or projection.source_record_id != body.source_record_id
            or "deviation" not in projection.projection_type.lower()
        ):
            raise ValidationError(
                "Protocol deviation follow-up requires the current approved EDC projection"
            )
        item = ProtocolDeviationFollowUp(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_protocol_deviation_followup",
            item.id,
            "create",
            study_id=study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def transition_pd(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(ProtocolDeviationFollowUp, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("Protocol deviation follow-up not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("Protocol deviation follow-up was updated by another user")
        if body.status not in PD_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError("Invalid protocol deviation transition")
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_protocol_deviation_followup",
            item.id,
            f"transition:{body.status}",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def create_icf_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: ICFVersionCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        item = ICFVersion(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_icf_version",
            item.id,
            "create",
            study_id=study_id,
            correlation_id=correlation,
        )
        return item

    async def create_icf_rollout(
        self,
        session: AsyncSession,
        version_id: UUID,
        actor: User,
        body: ICFRolloutCreate,
        correlation: str,
    ):
        version = await session.get(ICFVersion, version_id)
        if not version or version.deleted_at:
            raise NotFoundError("ICF version not found")
        await self._site(session, version.study_id, body.site_id)
        item = ICFSiteRollout(
            icf_version_id=version.id,
            study_id=version.study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_icf_site_rollout",
            item.id,
            "create",
            study_id=item.study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def transition_icf(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: TransitionRequest,
        correlation: str,
    ):
        item = await session.get(ICFSiteRollout, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("ICF rollout not found")
        if body.expected_version and body.expected_version != item.version:
            raise ConflictError("ICF rollout was updated by another user")
        if body.status not in ICF_TRANSITIONS.get(item.status, set()):
            raise BusinessRuleError("Invalid ICF rollout transition")
        if body.status == "Effective" and not item.evidence_references:
            raise BusinessRuleError(
                "Training and acknowledgement evidence is required before an ICF rollout is effective"
            )
        now = utc_now()
        item.status = body.status
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = now
        stamps = {
            "Distributed": "distributed_at",
            "Site Acknowledged": "acknowledged_at",
            "Training Complete": "training_completed_at",
            "Effective": "effective_at",
        }
        if body.status in stamps:
            setattr(item, stamps[body.status], now)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_icf_site_rollout",
            item.id,
            f"transition:{body.status}",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def update_icf_evidence(
        self,
        session: AsyncSession,
        item_id: UUID,
        actor: User,
        body: ICFEvidenceUpdate,
        correlation: str,
    ):
        item = await session.get(ICFSiteRollout, item_id)
        if not item or item.deleted_at:
            raise NotFoundError("ICF rollout not found")
        if item.version != body.expected_version:
            raise ConflictError("ICF rollout was updated by another user")
        item.evidence_references = body.evidence_references
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_icf_site_rollout",
            item.id,
            "evidence_update",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def create_tracking_definition(
        self, session: AsyncSession, actor: User, body: TrackingDefinitionCreate, correlation: str
    ):
        item = TrackingLogDefinition(
            code=body.code.upper(),
            name=body.name,
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        version = TrackingLogDefinitionVersion(
            definition_id=item.id, version_number=1, columns_json=body.columns, created_by=actor.id
        )
        session.add(version)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="ctms_tracking_log_definition",
            entity_id=item.id,
            action="create",
            module=Module.CTMS,
            actor_id=actor.id,
            correlation_id=correlation,
        )
        return item, version

    async def create_tracking_definition_version(
        self,
        session: AsyncSession,
        definition_id: UUID,
        actor: User,
        body: TrackingDefinitionVersionCreate,
        correlation: str,
    ):
        definition = await session.get(TrackingLogDefinition, definition_id)
        if not definition or definition.deleted_at:
            raise NotFoundError("Tracking log definition not found")
        if definition.version != body.expected_version:
            raise ConflictError("Tracking log definition was updated by another user")
        if definition.status not in {"Published", "Retired"}:
            raise BusinessRuleError(
                "A new tracking log definition version can only follow a published version"
            )
        definition.current_version += 1
        definition.status = "Draft"
        definition.version += 1
        definition.updated_by = actor.id
        definition.updated_at = utc_now()
        version = TrackingLogDefinitionVersion(
            definition_id=definition.id,
            version_number=definition.current_version,
            columns_json=body.columns,
            created_by=actor.id,
        )
        session.add(version)
        await session.flush()
        await audit_service.record(
            session,
            entity_type="ctms_tracking_log_definition",
            entity_id=definition.id,
            action="new_version",
            module=Module.CTMS,
            actor_id=actor.id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return version

    async def transition_tracking_definition(
        self,
        session: AsyncSession,
        version_id: UUID,
        actor: User,
        body: TransitionRequest,
    ):
        version = await session.get(TrackingLogDefinitionVersion, version_id)
        if not version:
            raise NotFoundError("Tracking log definition version not found")
        definition = await session.get(TrackingLogDefinition, version.definition_id)
        if body.expected_version and body.expected_version != definition.version:
            raise ConflictError("Tracking log definition was updated by another user")
        allowed = {"Draft": {"Published"}, "Published": {"Retired"}, "Retired": set()}
        if body.status not in allowed.get(version.status, set()):
            raise BusinessRuleError("Invalid tracking log definition transition")
        version.status = body.status
        definition.status = body.status
        definition.version += 1
        definition.updated_by = actor.id
        definition.updated_at = utc_now()
        await session.flush()
        await audit_service.record(
            session,
            entity_type="ctms_tracking_log_definition",
            entity_id=definition.id,
            action=f"transition:{body.status}",
            module=Module.CTMS,
            actor_id=actor.id,
            reason=body.reason,
        )
        return version

    async def create_tracking_log(
        self,
        session: AsyncSession,
        study_id: UUID,
        actor: User,
        body: TrackingLogCreate,
        correlation: str,
    ):
        await self._study(session, study_id)
        definition = await session.get(TrackingLogDefinitionVersion, body.definition_version_id)
        if not definition or definition.status != "Published":
            raise ValidationError("A published tracking log definition version is required")
        item = StudyTrackingLog(
            study_id=study_id,
            **body.model_dump(),
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_tracking_log",
            item.id,
            "create",
            study_id=study_id,
            correlation_id=correlation,
        )
        return item

    async def create_tracking_entry(
        self,
        session: AsyncSession,
        log_id: UUID,
        actor: User,
        body: TrackingEntryCreate,
        correlation: str,
    ):
        log = await session.get(StudyTrackingLog, log_id)
        if not log or log.deleted_at:
            raise NotFoundError("Tracking log not found")
        if log.status != "Active":
            raise BusinessRuleError("Only active logs accept entries")
        if body.site_id:
            await self._site(session, log.study_id, body.site_id)
        await self.validate_tracking_values(session, log.definition_version_id, body.values)
        item = TrackingLogEntry(
            log_id=log.id,
            study_id=log.study_id,
            site_id=body.site_id,
            row_key=body.row_key,
            values_json=body.values,
            created_by=actor.id,
            updated_by=actor.id,
            correlation_id=correlation,
        )
        session.add(item)
        await session.flush()
        session.add(
            TrackingLogEntryRevision(
                entry_id=item.id,
                revision_number=1,
                values_json=body.values,
                reason="Initial entry",
                actor_id=actor.id,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_tracking_log_entry",
            item.id,
            "create",
            study_id=log.study_id,
            site_id=item.site_id,
            correlation_id=correlation,
        )
        return item

    async def revise_tracking_entry(
        self,
        session: AsyncSession,
        entry_id: UUID,
        actor: User,
        body: TrackingEntryRevisionCreate,
        correlation: str,
    ):
        item = await session.get(TrackingLogEntry, entry_id)
        if not item or item.deleted_at:
            raise NotFoundError("Tracking log entry not found")
        if item.version != body.expected_version:
            raise ConflictError("Tracking entry was updated by another user")
        log = await session.get(StudyTrackingLog, item.log_id)
        await self.validate_tracking_values(session, log.definition_version_id, body.values)
        item.values_json = body.values
        item.current_revision += 1
        item.version += 1
        item.updated_by = actor.id
        item.updated_at = utc_now()
        session.add(
            TrackingLogEntryRevision(
                entry_id=item.id,
                revision_number=item.current_revision,
                values_json=body.values,
                reason=body.reason,
                actor_id=actor.id,
            )
        )
        await session.flush()
        await self._audit(
            session,
            actor,
            "ctms_tracking_log_entry",
            item.id,
            "revise",
            study_id=item.study_id,
            site_id=item.site_id,
            reason=body.reason,
            correlation_id=correlation,
        )
        return item

    async def validate_tracking_values(
        self, session: AsyncSession, version_id: UUID, values: dict[str, Any]
    ):
        version = await session.get(TrackingLogDefinitionVersion, version_id)
        if not version:
            raise NotFoundError("Tracking log definition version not found")
        allowed = {str(col.get("key")) for col in version.columns_json}
        unknown = set(values) - allowed
        if unknown:
            raise ValidationError(
                "Tracking entry contains undefined columns", {"columns": sorted(unknown)}
            )
        missing = {
            str(col.get("key"))
            for col in version.columns_json
            if col.get("required")
            and (
                str(col.get("key")) not in values
                or values.get(str(col.get("key"))) is None
                or values.get(str(col.get("key"))) == ""
            )
        }
        if missing:
            raise ValidationError(
                "Tracking entry is missing required columns", {"columns": sorted(missing)}
            )
        invalid_types = []
        for column in version.columns_json:
            key = str(column.get("key"))
            if key not in values or values[key] is None:
                continue
            value = values[key]
            data_type = str(column.get("type")).lower()
            valid = {
                "string": isinstance(value, str),
                "number": isinstance(value, (int, float, Decimal)) and not isinstance(value, bool),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "date": isinstance(value, (date, str)),
                "datetime": isinstance(value, (datetime, str)),
            }.get(data_type, False)
            if not valid:
                invalid_types.append(key)
        if invalid_types:
            raise ValidationError(
                "Tracking entry contains values with invalid types",
                {"columns": sorted(invalid_types)},
            )


study_workspace_service = StudyWorkspaceService()

__all__ = ["StudyWorkspaceService", "study_workspace_service"]
