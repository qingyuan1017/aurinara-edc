"""Cross-study read models for CTMS portfolio operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.ctms.financial import (
    ContractPaymentTerm,
    FinancialBudget,
    FinancialBudgetLine,
    FinancialBudgetVersion,
    FinancialContract,
    FinancialContractVersion,
    FinancialInvoice,
    FinancialInvoiceLine,
    FinancialPayment,
    PayableItem,
    PaymentAllocation,
)
from app.models.ctms.monitoring import (
    MonitoringActionItem,
    MonitoringActivity,
    MonitoringActivityScheduleHistory,
    MonitoringFinding,
    MonitoringVisitReport,
)
from app.models.edc.site import Site
from app.models.edc.study import Study
from app.models.shared.identity import User


@dataclass(frozen=True)
class PortfolioScope:
    study_ids: tuple[UUID, ...]
    study_wide_ids: tuple[UUID, ...]
    site_ids: tuple[UUID, ...]


def _scope_condition(model: Any, scope: PortfolioScope, *, site_capable: bool = True):
    conditions = []
    if scope.study_wide_ids:
        conditions.append(model.study_id.in_(scope.study_wide_ids))
    if site_capable and scope.site_ids and hasattr(model, "site_id"):
        conditions.append(model.site_id.in_(scope.site_ids))
    return or_(*conditions) if conditions else model.study_id.in_([])


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class PortfolioRepository:
    async def scope_catalog(self, session: AsyncSession) -> tuple[list[UUID], dict[UUID, UUID]]:
        study_ids = list(await session.scalars(select(Study.id).where(Study.deleted_at.is_(None))))
        site_rows = await session.execute(
            select(Site.id, Site.study_id).where(Site.deleted_at.is_(None))
        )
        return study_ids, {row.id: row.study_id for row in site_rows}

    @staticmethod
    async def _paged(session: AsyncSession, query: Select, page: int, page_size: int):
        total = int(
            await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
            or 0
        )
        rows = (
            await session.execute(query.offset((page - 1) * page_size).limit(page_size))
        ).mappings()
        return [dict(row) for row in rows], total

    @staticmethod
    def _sorted(query: Select, sort: str | None, columns: dict[str, Any], default: Any):
        if not sort:
            return query.order_by(default)
        descending = sort.startswith("-")
        column = columns.get(sort.removeprefix("-"))
        if column is None:
            return query.order_by(default)
        return query.order_by(column.desc() if descending else column.asc())

    async def monitoring_summary(
        self, session: AsyncSession, scope: PortfolioScope
    ) -> dict[str, int]:
        now = datetime.now(UTC)
        access = _scope_condition(MonitoringActivity, scope)
        active = MonitoringActivity.deleted_at.is_(None)
        terminal = MonitoringActivity.status.in_(("Completed", "Cancelled"))
        row = (
            (
                await session.execute(
                    select(
                        func.count(MonitoringActivity.id).label("total"),
                        func.sum(
                            case((MonitoringActivity.assigned_cra_id.is_(None), 1), else_=0)
                        ).label("unassigned"),
                        func.sum(
                            case((MonitoringActivity.status == "In Progress", 1), else_=0)
                        ).label("in_progress"),
                        func.sum(
                            case((MonitoringActivity.status == "Completed", 1), else_=0)
                        ).label("completed"),
                        func.sum(
                            case(
                                (
                                    and_(
                                        MonitoringActivity.planned_date < now,
                                        ~terminal,
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("overdue"),
                        func.sum(
                            case(
                                (
                                    and_(
                                        MonitoringActivity.planned_date >= now,
                                        ~terminal,
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("upcoming"),
                    ).where(access, active)
                )
            )
            .mappings()
            .one()
        )
        finding_access = _scope_condition(MonitoringFinding, scope)
        open_findings = int(
            await session.scalar(
                select(func.count(MonitoringFinding.id)).where(
                    finding_access,
                    MonitoringFinding.deleted_at.is_(None),
                    ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
                )
            )
            or 0
        )
        return {key: int(row[key] or 0) for key in row} | {"open_findings": open_findings}

    async def monitoring_activities(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        cra_id: UUID | None = None,
        status: str | None = None,
        activity_type: str | None = None,
        modality: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        unassigned: bool | None = None,
        overdue: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ):
        now = datetime.now(UTC)
        cra = aliased(User)
        open_findings = (
            select(func.count(MonitoringFinding.id))
            .where(
                MonitoringFinding.visit_id == MonitoringActivity.id,
                MonitoringFinding.deleted_at.is_(None),
                ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
            )
            .correlate(MonitoringActivity)
            .scalar_subquery()
        )
        report_status = (
            select(MonitoringVisitReport.status)
            .where(MonitoringVisitReport.visit_id == MonitoringActivity.id)
            .order_by(MonitoringVisitReport.version_number.desc())
            .limit(1)
            .correlate(MonitoringActivity)
            .scalar_subquery()
        )
        reschedule_count = (
            select(func.count(MonitoringActivityScheduleHistory.id))
            .where(MonitoringActivityScheduleHistory.activity_id == MonitoringActivity.id)
            .correlate(MonitoringActivity)
            .scalar_subquery()
        )
        overdue_expr = and_(
            MonitoringActivity.planned_date < now,
            ~MonitoringActivity.status.in_(("Completed", "Cancelled")),
        )
        query = (
            select(
                MonitoringActivity.id,
                MonitoringActivity.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                MonitoringActivity.site_id,
                Site.site_number,
                Site.name.label("site_name"),
                MonitoringActivity.activity_type,
                MonitoringActivity.modality,
                MonitoringActivity.planned_date,
                MonitoringActivity.assigned_cra_id,
                func.trim(
                    func.coalesce(cra.first_name, "") + " " + func.coalesce(cra.last_name, "")
                ).label("assigned_cra_name"),
                MonitoringActivity.status,
                overdue_expr.label("is_overdue"),
                open_findings.label("open_findings"),
                report_status.label("report_status"),
                reschedule_count.label("reschedule_count"),
                MonitoringActivity.escalation_reference,
            )
            .join(Study, Study.id == MonitoringActivity.study_id)
            .outerjoin(Site, Site.id == MonitoringActivity.site_id)
            .outerjoin(cra, cra.id == MonitoringActivity.assigned_cra_id)
            .where(
                _scope_condition(MonitoringActivity, scope),
                MonitoringActivity.deleted_at.is_(None),
            )
        )
        if study_id:
            query = query.where(MonitoringActivity.study_id == study_id)
        if site_id:
            query = query.where(MonitoringActivity.site_id == site_id)
        if cra_id:
            query = query.where(MonitoringActivity.assigned_cra_id == cra_id)
        if status:
            query = query.where(MonitoringActivity.status == status)
        if activity_type:
            query = query.where(MonitoringActivity.activity_type == activity_type)
        if modality:
            query = query.where(MonitoringActivity.modality == modality)
        if date_from:
            query = query.where(MonitoringActivity.planned_date >= date_from)
        if date_to:
            query = query.where(MonitoringActivity.planned_date <= date_to)
        if unassigned is True:
            query = query.where(MonitoringActivity.assigned_cra_id.is_(None))
        if unassigned is False:
            query = query.where(MonitoringActivity.assigned_cra_id.is_not(None))
        if overdue is True:
            query = query.where(overdue_expr)
        if overdue is False:
            query = query.where(~overdue_expr)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Study.study_code.ilike(term),
                    Study.title.ilike(term),
                    Site.site_number.ilike(term),
                    Site.name.ilike(term),
                )
            )
        query = self._sorted(
            query,
            sort,
            {
                "planned_date": MonitoringActivity.planned_date,
                "status": MonitoringActivity.status,
                "study": Study.study_code,
                "site": Site.site_number,
                "cra": cra.last_name,
            },
            MonitoringActivity.planned_date.asc(),
        ).order_by(MonitoringActivity.id)
        rows, total = await self._paged(session, query, page, page_size)
        for row in rows:
            planned_date = row["planned_date"]
            if planned_date.tzinfo is None:
                planned_date = planned_date.replace(tzinfo=UTC)
            row["overdue_days"] = max(0, (now - planned_date).days) if row["is_overdue"] else 0
            row["assigned_cra_name"] = row["assigned_cra_name"] or None
        return rows, total

    async def monitoring_workload(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        cra = aliased(User)
        terminal = MonitoringActivity.status.in_(("Completed", "Cancelled"))
        overdue = and_(MonitoringActivity.planned_date < now, ~terminal)
        upcoming = and_(MonitoringActivity.planned_date >= now, ~terminal)
        query = (
            select(
                MonitoringActivity.assigned_cra_id.label("cra_id"),
                func.trim(
                    func.coalesce(cra.first_name, "") + " " + func.coalesce(cra.last_name, "")
                ).label("cra_name"),
                func.count(MonitoringActivity.id).label("total"),
                func.sum(case((upcoming, 1), else_=0)).label("upcoming"),
                func.sum(case((overdue, 1), else_=0)).label("overdue"),
                func.sum(case((MonitoringActivity.status == "In Progress", 1), else_=0)).label(
                    "in_progress"
                ),
                func.sum(case((MonitoringActivity.status == "Completed", 1), else_=0)).label(
                    "completed"
                ),
            )
            .outerjoin(cra, cra.id == MonitoringActivity.assigned_cra_id)
            .where(
                _scope_condition(MonitoringActivity, scope),
                MonitoringActivity.deleted_at.is_(None),
            )
            .group_by(MonitoringActivity.assigned_cra_id, cra.first_name, cra.last_name)
            .order_by(func.count(MonitoringActivity.id).desc())
        )
        if date_from:
            query = query.where(MonitoringActivity.planned_date >= date_from)
        if date_to:
            query = query.where(MonitoringActivity.planned_date <= date_to)
        rows = [dict(row) for row in (await session.execute(query)).mappings()]
        for row in rows:
            row["cra_name"] = row["cra_name"] or "Unassigned"
            for key in ("total", "upcoming", "overdue", "in_progress", "completed"):
                row[key] = int(row[key] or 0)
        return rows

    async def monitoring_findings(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        owner_id: UUID | None = None,
        status: str | None = None,
        severity: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        overdue: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ):
        now = datetime.now(UTC)
        owner = aliased(User)
        open_actions = (
            select(func.count(MonitoringActionItem.id))
            .where(
                MonitoringActionItem.finding_id == MonitoringFinding.id,
                MonitoringActionItem.deleted_at.is_(None),
                MonitoringActionItem.status != "Completed",
            )
            .correlate(MonitoringFinding)
            .scalar_subquery()
        )
        overdue_expr = and_(
            MonitoringFinding.due_date.is_not(None),
            MonitoringFinding.due_date < now,
            ~MonitoringFinding.status.in_(("Closed", "Cancelled")),
        )
        query = (
            select(
                MonitoringFinding.id,
                MonitoringFinding.finding_code,
                MonitoringFinding.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                MonitoringFinding.site_id,
                Site.site_number,
                Site.name.label("site_name"),
                MonitoringFinding.visit_id,
                MonitoringFinding.category,
                MonitoringFinding.severity,
                MonitoringFinding.description,
                MonitoringFinding.owner_id,
                func.trim(
                    func.coalesce(owner.first_name, "") + " " + func.coalesce(owner.last_name, "")
                ).label("owner_name"),
                MonitoringFinding.responsible_party,
                MonitoringFinding.due_date,
                MonitoringFinding.status,
                MonitoringFinding.capa_required,
                open_actions.label("open_actions"),
                overdue_expr.label("is_overdue"),
            )
            .join(Study, Study.id == MonitoringFinding.study_id)
            .outerjoin(Site, Site.id == MonitoringFinding.site_id)
            .outerjoin(owner, owner.id == MonitoringFinding.owner_id)
            .where(
                _scope_condition(MonitoringFinding, scope),
                MonitoringFinding.deleted_at.is_(None),
            )
        )
        if study_id:
            query = query.where(MonitoringFinding.study_id == study_id)
        if site_id:
            query = query.where(MonitoringFinding.site_id == site_id)
        if owner_id:
            query = query.where(MonitoringFinding.owner_id == owner_id)
        if status:
            query = query.where(MonitoringFinding.status == status)
        if severity:
            query = query.where(MonitoringFinding.severity == severity)
        if date_from:
            query = query.where(MonitoringFinding.due_date >= date_from)
        if date_to:
            query = query.where(MonitoringFinding.due_date <= date_to)
        if overdue is True:
            query = query.where(overdue_expr)
        if overdue is False:
            query = query.where(~overdue_expr)
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    MonitoringFinding.finding_code.ilike(term),
                    MonitoringFinding.category.ilike(term),
                    MonitoringFinding.description.ilike(term),
                    Study.study_code.ilike(term),
                )
            )
        query = self._sorted(
            query,
            sort,
            {
                "due_date": MonitoringFinding.due_date,
                "status": MonitoringFinding.status,
                "severity": MonitoringFinding.severity,
                "study": Study.study_code,
                "site": Site.site_number,
                "owner": owner.last_name,
            },
            MonitoringFinding.due_date.asc().nullslast(),
        ).order_by(MonitoringFinding.id)
        rows, total = await self._paged(session, query, page, page_size)
        for row in rows:
            row["owner_name"] = row["owner_name"] or None
        return rows, total

    def _latest_contract_version(self):
        return (
            select(FinancialContractVersion.id)
            .where(FinancialContractVersion.contract_id == FinancialContract.id)
            .order_by(
                case(
                    (FinancialContractVersion.status == "executed", 0),
                    (FinancialContractVersion.status == "approved", 1),
                    else_=2,
                ),
                FinancialContractVersion.version_number.desc(),
            )
            .limit(1)
            .correlate(FinancialContract)
            .scalar_subquery()
        )

    async def contract_summary(
        self, session: AsyncSession, scope: PortfolioScope
    ) -> dict[str, int]:
        today = date.today()
        version = aliased(FinancialContractVersion)
        latest_id = self._latest_contract_version()
        access = _scope_condition(FinancialContract, scope)
        row = (
            (
                await session.execute(
                    select(
                        func.count(FinancialContract.id).label("total"),
                        func.sum(
                            case((FinancialContract.status == "internal_review", 1), else_=0)
                        ).label("internal_review"),
                        func.sum(
                            case((FinancialContract.status == "negotiation", 1), else_=0)
                        ).label("negotiation"),
                        func.sum(case((FinancialContract.status == "approved", 1), else_=0)).label(
                            "approved_awaiting_execution"
                        ),
                        func.sum(case((FinancialContract.status == "active", 1), else_=0)).label(
                            "active"
                        ),
                        func.sum(
                            case(
                                (
                                    and_(
                                        FinancialContract.status.in_(("executed", "active")),
                                        version.status == "executed",
                                        version.effective_to < today,
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("expired"),
                        func.sum(
                            case(
                                (
                                    and_(
                                        FinancialContract.status.in_(("executed", "active")),
                                        version.status == "executed",
                                        version.effective_to >= today,
                                        version.effective_to <= today + timedelta(days=30),
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("expiring_30_days"),
                    )
                    .select_from(FinancialContract)
                    .outerjoin(version, version.id == latest_id)
                    .where(access)
                )
            )
            .mappings()
            .one()
        )
        return {key: int(row[key] or 0) for key in row}

    async def contracts(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        study_id: UUID | None = None,
        site_id: UUID | None = None,
        organization_id: UUID | None = None,
        owner_id: UUID | None = None,
        status: str | None = None,
        contract_type: str | None = None,
        direction: str | None = None,
        currency: str | None = None,
        expires_within_days: int | None = None,
        expired: bool | None = None,
        search: str | None = None,
        sort: str | None = None,
    ):
        today = date.today()
        version = aliased(FinancialContractVersion)
        owner = aliased(User)
        latest_id = self._latest_contract_version()
        query = (
            select(
                FinancialContract.id,
                FinancialContract.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                FinancialContract.site_id,
                Site.site_number,
                Site.name.label("site_name"),
                FinancialContract.organization_id,
                FinancialContract.contract_number,
                FinancialContract.title,
                FinancialContract.contract_type,
                FinancialContract.direction,
                FinancialContract.party_name,
                FinancialContract.status,
                FinancialContract.currency,
                FinancialContract.owner_id,
                func.trim(
                    func.coalesce(owner.first_name, "") + " " + func.coalesce(owner.last_name, "")
                ).label("owner_name"),
                version.id.label("current_version_id"),
                version.status.label("version_status"),
                version.total_value,
                version.effective_from,
                version.effective_to,
            )
            .join(Study, Study.id == FinancialContract.study_id)
            .outerjoin(Site, Site.id == FinancialContract.site_id)
            .outerjoin(owner, owner.id == FinancialContract.owner_id)
            .outerjoin(version, version.id == latest_id)
            .where(_scope_condition(FinancialContract, scope))
        )
        if study_id:
            query = query.where(FinancialContract.study_id == study_id)
        if site_id:
            query = query.where(FinancialContract.site_id == site_id)
        if organization_id:
            query = query.where(FinancialContract.organization_id == organization_id)
        if owner_id:
            query = query.where(FinancialContract.owner_id == owner_id)
        if status:
            query = query.where(FinancialContract.status == status)
        if contract_type:
            query = query.where(FinancialContract.contract_type == contract_type)
        if direction:
            query = query.where(FinancialContract.direction == direction)
        if currency:
            query = query.where(FinancialContract.currency == currency.upper())
        if expires_within_days is not None:
            query = query.where(
                FinancialContract.status.in_(("executed", "active")),
                version.status == "executed",
                version.effective_to >= today,
                version.effective_to <= today + timedelta(days=expires_within_days),
            )
        if expired is True:
            query = query.where(
                FinancialContract.status.in_(("executed", "active")),
                version.status == "executed",
                version.effective_to < today,
            )
        if expired is False:
            query = query.where(or_(version.effective_to.is_(None), version.effective_to >= today))
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    FinancialContract.contract_number.ilike(term),
                    FinancialContract.title.ilike(term),
                    FinancialContract.party_name.ilike(term),
                    Study.study_code.ilike(term),
                )
            )
        query = self._sorted(
            query,
            sort,
            {
                "effective_to": version.effective_to,
                "status": FinancialContract.status,
                "value": version.total_value,
                "study": Study.study_code,
                "party": FinancialContract.party_name,
            },
            version.effective_to.asc().nullslast(),
        ).order_by(FinancialContract.created_at.desc())
        rows, total = await self._paged(session, query, page, page_size)
        for row in rows:
            row["owner_name"] = row["owner_name"] or None
            row["days_to_expiry"] = (
                (row["effective_to"] - today).days if row["effective_to"] else None
            )
        return rows, total

    async def _financial_groups(
        self, session: AsyncSession, scope: PortfolioScope
    ) -> dict[tuple[UUID, str], dict[str, Decimal]]:
        result: dict[tuple[UUID, str], dict[str, Decimal]] = {}

        def merge(rows, key_name: str):
            for row in rows:
                key = (row.study_id, row.currency)
                bucket = result.setdefault(key, {})
                bucket[key_name] = _money(row.amount)

        budget_rows = await session.execute(
            select(
                FinancialBudget.study_id,
                FinancialBudget.currency,
                func.sum(FinancialBudgetLine.planned_amount).label("amount"),
            )
            .join(FinancialBudgetVersion, FinancialBudgetVersion.budget_id == FinancialBudget.id)
            .join(FinancialBudgetLine, FinancialBudgetLine.version_id == FinancialBudgetVersion.id)
            .where(
                _scope_condition(FinancialBudget, scope, site_capable=False),
                FinancialBudgetVersion.status == "approved",
            )
            .group_by(FinancialBudget.study_id, FinancialBudget.currency)
        )
        merge(budget_rows, "approved_budget")

        current_contract_version = self._latest_contract_version()
        contract_rows = await session.execute(
            select(
                FinancialContract.study_id,
                FinancialContract.currency,
                func.sum(FinancialContractVersion.total_value).label("amount"),
            )
            .join(
                FinancialContractVersion,
                FinancialContractVersion.contract_id == FinancialContract.id,
            )
            .where(
                _scope_condition(FinancialContract, scope),
                FinancialContractVersion.id == current_contract_version,
                FinancialContractVersion.status == "executed",
            )
            .group_by(FinancialContract.study_id, FinancialContract.currency)
        )
        merge(contract_rows, "contracted")

        for statuses, name in (
            (("calculated",), "calculated_payables"),
            (("approved", "partially_invoiced", "invoiced", "paid"), "approved_payables"),
        ):
            payable_rows = await session.execute(
                select(
                    PayableItem.study_id,
                    PayableItem.currency,
                    func.sum(PayableItem.net_amount).label("amount"),
                )
                .join(FinancialContract, FinancialContract.id == PayableItem.contract_id)
                .where(
                    _scope_condition(FinancialContract, scope),
                    PayableItem.status.in_(statuses),
                )
                .group_by(PayableItem.study_id, PayableItem.currency)
            )
            merge(payable_rows, name)

        invoice_rows = await session.execute(
            select(
                FinancialInvoice.study_id,
                FinancialInvoice.currency,
                func.sum(FinancialInvoice.amount).label("amount"),
            )
            .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
            .where(_scope_condition(FinancialContract, scope))
            .group_by(FinancialInvoice.study_id, FinancialInvoice.currency)
        )
        merge(invoice_rows, "invoiced")

        payment_rows = await session.execute(
            select(
                FinancialPayment.study_id,
                FinancialPayment.currency,
                func.sum(FinancialPayment.amount).label("amount"),
            )
            .where(
                _scope_condition(FinancialPayment, scope, site_capable=False),
                FinancialPayment.status == "settled",
            )
            .group_by(FinancialPayment.study_id, FinancialPayment.currency)
        )
        merge(payment_rows, "paid")

        overdue_paid = (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .join(FinancialPayment, FinancialPayment.id == PaymentAllocation.payment_id)
            .where(
                PaymentAllocation.invoice_id == FinancialInvoice.id,
                FinancialPayment.status == "settled",
            )
            .correlate(FinancialInvoice)
            .scalar_subquery()
        )
        overdue_rows = await session.execute(
            select(
                FinancialInvoice.study_id,
                FinancialInvoice.currency,
                func.sum(
                    case(
                        (
                            FinancialInvoice.amount > overdue_paid,
                            FinancialInvoice.amount - overdue_paid,
                        ),
                        else_=0,
                    )
                ).label("amount"),
            )
            .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
            .where(
                _scope_condition(FinancialContract, scope),
                FinancialInvoice.due_date < date.today(),
                FinancialInvoice.status != "paid",
            )
            .group_by(FinancialInvoice.study_id, FinancialInvoice.currency)
        )
        merge(overdue_rows, "overdue")
        return result

    async def financial_summary(
        self, session: AsyncSession, scope: PortfolioScope
    ) -> list[dict[str, Any]]:
        groups = await self._financial_groups(session, scope)
        by_currency: dict[str, dict[str, Decimal]] = {}
        for (_, currency), amounts in groups.items():
            bucket = by_currency.setdefault(currency, {})
            for name, amount in amounts.items():
                bucket[name] = _money(bucket.get(name, Decimal("0")) + amount)
        return [
            self._financial_row(currency, amounts)
            for currency, amounts in sorted(by_currency.items())
        ]

    @staticmethod
    def _financial_row(currency: str, amounts: dict[str, Decimal]) -> dict[str, Any]:
        values = {
            name: _money(amounts.get(name))
            for name in (
                "approved_budget",
                "contracted",
                "calculated_payables",
                "approved_payables",
                "invoiced",
                "paid",
                "overdue",
            )
        }
        values["outstanding"] = _money(
            max(Decimal("0"), values["approved_payables"] - values["paid"])
        )
        values["budget_variance"] = _money(values["approved_budget"] - values["contracted"])
        return {"currency": currency, **values}

    async def _dimension_financial_groups(
        self, session: AsyncSession, scope: PortfolioScope, dimension: str
    ) -> dict[tuple[UUID, str, str, str], dict[str, Decimal]]:
        """Aggregate attributable ledger values by one reporting dimension.

        Payments are attributed through immutable invoice allocations. Values without
        a reliable relationship to the requested dimension are intentionally left at
        zero instead of being guessed or duplicated across groups.
        """
        result: dict[tuple[UUID, str, str, str], dict[str, Decimal]] = {}

        def merge(rows, value_name: str) -> None:
            for row in rows:
                raw_key = row.dimension_key
                key = str(raw_key) if raw_key is not None else "unassigned"
                label = row.dimension_label or (
                    "Study level" if dimension == "site" else "Unassigned"
                )
                bucket = result.setdefault((row.study_id, row.currency, key, str(label)), {})
                bucket[value_name] = _money(
                    bucket.get(value_name, Decimal("0")) + _money(row.amount)
                )

        if dimension == "cost_category":
            budget_rows = await session.execute(
                select(
                    FinancialBudget.study_id,
                    FinancialBudget.currency,
                    FinancialBudgetLine.category.label("dimension_key"),
                    FinancialBudgetLine.category.label("dimension_label"),
                    func.sum(FinancialBudgetLine.planned_amount).label("amount"),
                )
                .join(
                    FinancialBudgetVersion, FinancialBudgetVersion.budget_id == FinancialBudget.id
                )
                .join(
                    FinancialBudgetLine, FinancialBudgetLine.version_id == FinancialBudgetVersion.id
                )
                .where(
                    _scope_condition(FinancialBudget, scope, site_capable=False),
                    FinancialBudgetVersion.status == "approved",
                )
                .group_by(
                    FinancialBudget.study_id,
                    FinancialBudget.currency,
                    FinancialBudgetLine.category,
                )
            )
            merge(budget_rows, "approved_budget")
            dimension_key = ContractPaymentTerm.cost_category
            dimension_label = ContractPaymentTerm.cost_category
        else:
            if dimension == "organization":
                dimension_key = FinancialContract.organization_id
                dimension_label = func.max(FinancialContract.party_name)
            elif dimension == "site":
                dimension_key = FinancialContract.site_id
                dimension_label = func.max(Site.name)
            else:
                dimension_key = FinancialContract.direction
                dimension_label = FinancialContract.direction

            current_version = self._latest_contract_version()
            contract_query = (
                select(
                    FinancialContract.study_id,
                    FinancialContract.currency,
                    dimension_key.label("dimension_key"),
                    dimension_label.label("dimension_label"),
                    func.sum(FinancialContractVersion.total_value).label("amount"),
                )
                .join(
                    FinancialContractVersion,
                    FinancialContractVersion.contract_id == FinancialContract.id,
                )
                .outerjoin(Site, Site.id == FinancialContract.site_id)
                .where(
                    _scope_condition(FinancialContract, scope),
                    FinancialContractVersion.id == current_version,
                    FinancialContractVersion.status == "executed",
                )
                .group_by(
                    FinancialContract.study_id,
                    FinancialContract.currency,
                    dimension_key,
                )
            )
            merge(await session.execute(contract_query), "contracted")

        payable_base = (
            select(
                PayableItem.study_id,
                PayableItem.currency,
                dimension_key.label("dimension_key"),
                dimension_label.label("dimension_label"),
                func.sum(PayableItem.net_amount).label("amount"),
                PayableItem.status.label("payable_status"),
            )
            .join(FinancialContract, FinancialContract.id == PayableItem.contract_id)
            .outerjoin(Site, Site.id == FinancialContract.site_id)
        )
        if dimension == "cost_category":
            payable_base = payable_base.join(
                ContractPaymentTerm, ContractPaymentTerm.id == PayableItem.contract_term_id
            )
        payable_base = payable_base.where(_scope_condition(FinancialContract, scope)).group_by(
            PayableItem.study_id,
            PayableItem.currency,
            dimension_key,
            PayableItem.status,
        )
        for row in await session.execute(payable_base):
            name = (
                "calculated_payables"
                if row.payable_status == "calculated"
                else "approved_payables"
                if row.payable_status in ("approved", "partially_invoiced", "invoiced", "paid")
                else None
            )
            if name:
                merge([row], name)

        if dimension == "cost_category":
            invoice_query = (
                select(
                    FinancialInvoice.study_id,
                    FinancialInvoice.currency,
                    dimension_key.label("dimension_key"),
                    dimension_label.label("dimension_label"),
                    func.sum(FinancialInvoiceLine.amount).label("amount"),
                )
                .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
                .join(FinancialInvoiceLine, FinancialInvoiceLine.invoice_id == FinancialInvoice.id)
                .join(PayableItem, PayableItem.id == FinancialInvoiceLine.payable_item_id)
                .join(ContractPaymentTerm, ContractPaymentTerm.id == PayableItem.contract_term_id)
                .where(_scope_condition(FinancialContract, scope))
                .group_by(
                    FinancialInvoice.study_id,
                    FinancialInvoice.currency,
                    dimension_key,
                )
            )
        else:
            invoice_query = (
                select(
                    FinancialInvoice.study_id,
                    FinancialInvoice.currency,
                    dimension_key.label("dimension_key"),
                    dimension_label.label("dimension_label"),
                    func.sum(FinancialInvoice.amount).label("amount"),
                )
                .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
                .outerjoin(Site, Site.id == FinancialContract.site_id)
                .where(_scope_condition(FinancialContract, scope))
                .group_by(
                    FinancialInvoice.study_id,
                    FinancialInvoice.currency,
                    dimension_key,
                )
            )
        merge(await session.execute(invoice_query), "invoiced")

        payment_amount = PaymentAllocation.allocated_amount
        payment_query = (
            select(
                FinancialPayment.study_id,
                FinancialPayment.currency,
                dimension_key.label("dimension_key"),
                dimension_label.label("dimension_label"),
                func.sum(payment_amount).label("amount"),
            )
            .join(PaymentAllocation, PaymentAllocation.payment_id == FinancialPayment.id)
            .join(FinancialInvoice, FinancialInvoice.id == PaymentAllocation.invoice_id)
            .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
            .outerjoin(Site, Site.id == FinancialContract.site_id)
        )
        if dimension == "cost_category":
            payment_amount = (
                PaymentAllocation.allocated_amount
                * FinancialInvoiceLine.amount
                / FinancialInvoice.amount
            )
            payment_query = (
                select(
                    FinancialPayment.study_id,
                    FinancialPayment.currency,
                    dimension_key.label("dimension_key"),
                    dimension_label.label("dimension_label"),
                    func.sum(payment_amount).label("amount"),
                )
                .join(PaymentAllocation, PaymentAllocation.payment_id == FinancialPayment.id)
                .join(FinancialInvoice, FinancialInvoice.id == PaymentAllocation.invoice_id)
                .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
                .join(FinancialInvoiceLine, FinancialInvoiceLine.invoice_id == FinancialInvoice.id)
                .join(PayableItem, PayableItem.id == FinancialInvoiceLine.payable_item_id)
                .join(ContractPaymentTerm, ContractPaymentTerm.id == PayableItem.contract_term_id)
            )
        payment_query = payment_query.where(
            _scope_condition(FinancialContract, scope),
            FinancialPayment.status == "settled",
        ).group_by(
            FinancialPayment.study_id,
            FinancialPayment.currency,
            dimension_key,
        )
        merge(await session.execute(payment_query), "paid")
        return result

    async def financial_report(
        self, session: AsyncSession, scope: PortfolioScope, *, group_by: str = "study"
    ) -> list[dict[str, Any]]:
        groups = (
            await self._financial_groups(session, scope)
            if group_by == "study"
            else await self._dimension_financial_groups(session, scope, group_by)
        )
        if not groups:
            return []
        studies = {
            row.id: row
            for row in (
                await session.execute(select(Study).where(Study.id.in_({key[0] for key in groups})))
            ).scalars()
        }
        if group_by != "study":
            return [
                {
                    "study_id": study_id,
                    "study_code": studies[study_id].study_code,
                    "study_title": studies[study_id].title,
                    "group_by": group_by,
                    "group_key": group_key,
                    "group_label": group_label,
                    **self._financial_row(currency, amounts),
                }
                for (study_id, currency, group_key, group_label), amounts in sorted(
                    groups.items(),
                    key=lambda item: (
                        studies[item[0][0]].study_code,
                        item[0][1],
                        item[0][3],
                    ),
                )
            ]
        return [
            {
                "study_id": study_id,
                "study_code": studies[study_id].study_code,
                "study_title": studies[study_id].title,
                "group_by": "study",
                "group_key": str(study_id),
                "group_label": studies[study_id].study_code,
                **self._financial_row(currency, amounts),
            }
            for (study_id, currency), amounts in sorted(
                groups.items(), key=lambda item: (studies[item[0][0]].study_code, item[0][1])
            )
        ]

    async def payables(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        currency: str | None = None,
        study_id: UUID | None = None,
        sort: str | None = None,
    ):
        query = (
            select(
                PayableItem.id,
                PayableItem.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                PayableItem.contract_id,
                FinancialContract.contract_number,
                FinancialContract.party_name,
                PayableItem.gross_amount,
                PayableItem.holdback_amount,
                PayableItem.net_amount,
                PayableItem.currency,
                PayableItem.status,
                PayableItem.approved_at,
                PayableItem.created_at,
            )
            .join(Study, Study.id == PayableItem.study_id)
            .join(FinancialContract, FinancialContract.id == PayableItem.contract_id)
            .where(_scope_condition(FinancialContract, scope))
        )
        if status:
            query = query.where(PayableItem.status == status)
        if currency:
            query = query.where(PayableItem.currency == currency.upper())
        if study_id:
            query = query.where(PayableItem.study_id == study_id)
        query = self._sorted(
            query,
            sort,
            {
                "created_at": PayableItem.created_at,
                "amount": PayableItem.net_amount,
                "status": PayableItem.status,
                "study": Study.study_code,
            },
            PayableItem.created_at.desc(),
        )
        return await self._paged(session, query, page, page_size)

    async def invoices(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        currency: str | None = None,
        study_id: UUID | None = None,
        overdue: bool | None = None,
        due_within_days: int | None = None,
        sort: str | None = None,
    ):
        paid_amount = (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .join(FinancialPayment, FinancialPayment.id == PaymentAllocation.payment_id)
            .where(
                PaymentAllocation.invoice_id == FinancialInvoice.id,
                FinancialPayment.status == "settled",
            )
            .correlate(FinancialInvoice)
            .scalar_subquery()
        )
        overdue_expr = and_(
            FinancialInvoice.due_date < date.today(), paid_amount < FinancialInvoice.amount
        )
        query = (
            select(
                FinancialInvoice.id,
                FinancialInvoice.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                FinancialInvoice.contract_id,
                FinancialContract.contract_number,
                FinancialInvoice.party_name,
                FinancialInvoice.invoice_number,
                FinancialInvoice.direction,
                FinancialInvoice.invoice_date,
                FinancialInvoice.due_date,
                FinancialInvoice.amount,
                FinancialInvoice.currency,
                FinancialInvoice.status,
                paid_amount.label("paid_amount"),
                overdue_expr.label("is_overdue"),
            )
            .join(Study, Study.id == FinancialInvoice.study_id)
            .join(FinancialContract, FinancialContract.id == FinancialInvoice.contract_id)
            .where(_scope_condition(FinancialContract, scope))
        )
        if status:
            query = query.where(FinancialInvoice.status == status)
        if currency:
            query = query.where(FinancialInvoice.currency == currency.upper())
        if study_id:
            query = query.where(FinancialInvoice.study_id == study_id)
        if overdue is True:
            query = query.where(overdue_expr)
        if overdue is False:
            query = query.where(~overdue_expr)
        if due_within_days is not None:
            query = query.where(
                FinancialInvoice.due_date >= date.today(),
                FinancialInvoice.due_date <= date.today() + timedelta(days=due_within_days),
                paid_amount < FinancialInvoice.amount,
            )
        query = self._sorted(
            query,
            sort,
            {
                "due_date": FinancialInvoice.due_date,
                "amount": FinancialInvoice.amount,
                "status": FinancialInvoice.status,
                "study": Study.study_code,
            },
            FinancialInvoice.due_date.asc(),
        )
        rows, total = await self._paged(session, query, page, page_size)
        for row in rows:
            row["paid_amount"] = _money(row["paid_amount"])
            row["outstanding_amount"] = _money(
                max(Decimal("0"), row["amount"] - row["paid_amount"])
            )
            row["days_overdue"] = (
                max(0, (date.today() - row["due_date"]).days) if row["is_overdue"] else 0
            )
        return rows, total

    async def payments(
        self,
        session: AsyncSession,
        scope: PortfolioScope,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        currency: str | None = None,
        study_id: UUID | None = None,
        sort: str | None = None,
    ):
        allocated = (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .where(PaymentAllocation.payment_id == FinancialPayment.id)
            .correlate(FinancialPayment)
            .scalar_subquery()
        )
        query = (
            select(
                FinancialPayment.id,
                FinancialPayment.study_id,
                Study.study_code,
                Study.title.label("study_title"),
                FinancialPayment.party_name,
                FinancialPayment.direction,
                FinancialPayment.payment_date,
                FinancialPayment.amount,
                allocated.label("allocated_amount"),
                FinancialPayment.currency,
                FinancialPayment.reference,
                FinancialPayment.status,
                FinancialPayment.reversal_of_id,
            )
            .join(Study, Study.id == FinancialPayment.study_id)
            .where(_scope_condition(FinancialPayment, scope, site_capable=False))
        )
        if status:
            query = query.where(FinancialPayment.status == status)
        if currency:
            query = query.where(FinancialPayment.currency == currency.upper())
        if study_id:
            query = query.where(FinancialPayment.study_id == study_id)
        query = self._sorted(
            query,
            sort,
            {
                "payment_date": FinancialPayment.payment_date,
                "amount": FinancialPayment.amount,
                "status": FinancialPayment.status,
                "study": Study.study_code,
            },
            FinancialPayment.payment_date.desc(),
        )
        rows, total = await self._paged(session, query, page, page_size)
        for row in rows:
            row["allocated_amount"] = _money(row["allocated_amount"])
        return rows, total


portfolio_repository = PortfolioRepository()

__all__ = ["PortfolioRepository", "PortfolioScope", "portfolio_repository"]
