"""Authenticated CTMS operational report routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_ctms_permission
from app.models.shared.identity import User
from app.schemas.ctms.report import CTMSReportCatalogResponse, CTMSReportResponse
from app.services.ctms.ctms_report_service import ctms_report_service
from app.services.ctms.report_catalog import REPORT_CATALOG

router = APIRouter(tags=["ctms-reports"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational_data_read"))]


@router.get("/reports/catalog", response_model=CTMSReportCatalogResponse)
async def report_catalog(current_user: ReadGuard):
    """Return the reports supported by the CTMS backend."""
    return CTMSReportCatalogResponse(items=list(REPORT_CATALOG))


@router.get(
    "/studies/{study_id}/reports/{category}/{report_type}",
    response_model=CTMSReportResponse,
)
async def catalog_report(
    study_id: UUID,
    category: str,
    report_type: str,
    session: DbSession,
    current_user: ReadGuard,
    site_id: UUID | None = None,
):
    """Return one catalog report, scoped to the requesting user."""
    return await ctms_report_service.catalog_report(
        session,
        study_id,
        category,
        report_type,
        current_user,
        site_id=site_id,
    )


@router.get("/studies/{study_id}/reports/{report_type}", response_model=CTMSReportResponse)
async def operational_report(
    study_id: UUID,
    report_type: str,
    session: DbSession,
    current_user: ReadGuard,
    site_id: UUID | None = None,
    status: str | None = None,
    owner_id: UUID | None = None,
    priority: str | None = None,
    due_date: str | None = None,
    trend: str | None = None,
):
    """Return a filtered, scope-limited CTMS operational report."""
    return await ctms_report_service.report(
        session,
        study_id,
        report_type,
        current_user,
        site_id=site_id,
        status=status,
        owner_id=owner_id,
        priority=priority,
        due_date=due_date,
        trend=trend,
    )
