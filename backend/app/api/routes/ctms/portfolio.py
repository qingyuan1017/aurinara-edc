"""Permission-scoped portfolio monitoring, contract, and financial routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, PaginationParams, get_db
from app.schemas.ctms.portfolio import (
    PortfolioContract,
    PortfolioContractSummary,
    PortfolioCraWorkload,
    PortfolioFinancialReportRow,
    PortfolioFinancialSummary,
    PortfolioInvoice,
    PortfolioMonitoringActivity,
    PortfolioMonitoringFinding,
    PortfolioMonitoringSummary,
    PortfolioPayable,
    PortfolioPayment,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.portfolio_service import portfolio_service

router = APIRouter(prefix="/portfolio", tags=["ctms-portfolio-operations"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _page(items, pagination: PaginationParams, total: int, model):
    return PaginatedResponse(
        items=[model.model_validate(item) for item in items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/monitoring/summary", response_model=PortfolioMonitoringSummary)
async def monitoring_summary(session: DbSession, current_user: CurrentUser):
    return PortfolioMonitoringSummary.model_validate(
        await portfolio_service.monitoring_summary(session, current_user)
    )


@router.get(
    "/monitoring/activities",
    response_model=PaginatedResponse[PortfolioMonitoringActivity],
)
async def monitoring_activities(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
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
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.monitoring_activities(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
        site_id=site_id,
        cra_id=cra_id,
        status=status,
        activity_type=activity_type,
        modality=modality,
        date_from=date_from,
        date_to=date_to,
        unassigned=unassigned,
        overdue=overdue,
        search=search,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioMonitoringActivity)


@router.get(
    "/monitoring/workload",
    response_model=PaginatedResponse[PortfolioCraWorkload],
)
async def monitoring_workload(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    rows = await portfolio_service.monitoring_workload(
        session, current_user, date_from=date_from, date_to=date_to
    )
    items = rows[pagination.offset : pagination.offset + pagination.page_size]
    return _page(items, pagination, len(rows), PortfolioCraWorkload)


@router.get(
    "/monitoring/findings",
    response_model=PaginatedResponse[PortfolioMonitoringFinding],
)
async def monitoring_findings(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    study_id: UUID | None = None,
    site_id: UUID | None = None,
    owner_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    overdue: bool | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.monitoring_findings(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
        site_id=site_id,
        owner_id=owner_id,
        status=status,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
        overdue=overdue,
        search=search,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioMonitoringFinding)


@router.get("/contracts/summary", response_model=PortfolioContractSummary)
async def contract_summary(session: DbSession, current_user: CurrentUser):
    return PortfolioContractSummary.model_validate(
        await portfolio_service.contract_summary(session, current_user)
    )


@router.get("/contracts", response_model=PaginatedResponse[PortfolioContract])
async def contracts(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    study_id: UUID | None = None,
    site_id: UUID | None = None,
    organization_id: UUID | None = None,
    owner_id: UUID | None = None,
    status: str | None = None,
    contract_type: str | None = None,
    direction: str | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    expires_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
    expired: bool | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.contracts(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
        site_id=site_id,
        organization_id=organization_id,
        owner_id=owner_id,
        status=status,
        contract_type=contract_type,
        direction=direction,
        currency=currency,
        expires_within_days=expires_within_days,
        expired=expired,
        search=search,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioContract)


@router.get("/financials/summary", response_model=PortfolioFinancialSummary)
async def financial_summary(session: DbSession, current_user: CurrentUser):
    return PortfolioFinancialSummary(
        currencies=await portfolio_service.financial_summary(session, current_user)
    )


@router.get("/financials/payables", response_model=PaginatedResponse[PortfolioPayable])
async def financial_payables(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    study_id: UUID | None = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.payables(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        currency=currency,
        study_id=study_id,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioPayable)


@router.get("/financials/invoices", response_model=PaginatedResponse[PortfolioInvoice])
async def financial_invoices(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    study_id: UUID | None = None,
    overdue: bool | None = None,
    due_within_days: Annotated[int | None, Query(ge=0, le=365)] = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.invoices(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        currency=currency,
        study_id=study_id,
        overdue=overdue,
        due_within_days=due_within_days,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioInvoice)


@router.get("/financials/payments", response_model=PaginatedResponse[PortfolioPayment])
async def financial_payments(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    study_id: UUID | None = None,
    sort: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = await portfolio_service.payments(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        currency=currency,
        study_id=study_id,
        sort=sort,
    )
    return _page(items, pagination, total, PortfolioPayment)


@router.get(
    "/financials/report",
    response_model=PaginatedResponse[PortfolioFinancialReportRow],
)
async def financial_report(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    study_id: UUID | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    group_by: Literal["study", "organization", "site", "direction", "cost_category"] = "study",
    group_key: Annotated[str | None, Query(max_length=255)] = None,
):
    rows = await portfolio_service.financial_report(session, current_user, group_by=group_by)
    if study_id is not None:
        rows = [row for row in rows if row["study_id"] == study_id]
    if currency is not None:
        rows = [row for row in rows if row["currency"] == currency.upper()]
    if group_key is not None:
        rows = [row for row in rows if row["group_key"] == group_key]
    items = rows[pagination.offset : pagination.offset + pagination.page_size]
    return _page(items, pagination, len(rows), PortfolioFinancialReportRow)


__all__ = ["router"]
