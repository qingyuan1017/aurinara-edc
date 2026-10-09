"""Report_Area routes — read-only, server-side scope-filtered reporting.

All endpoints are GET and read-only. Each is guarded by ``require_permission``
so an unauthorized user is rejected with a not-authorized error before any read
runs (R9.10). Inside the service, every report restricts its rows to the
studies within the requesting user's Authorization_Scope via the shared
``permission_service`` (R9.8), returning an empty result when nothing is in
scope (R9.9).

The routers mount with no added prefix (consistent with the rest of the EDC
aggregate), so paths are stable for backward compatibility:

Report groups (Requirement 9):
  - Data Summary (R9.1)
  - CRF Status (R9.2)
  - Query Report (R9.3)
  - Enrollment Status (R9.4) — also exposes a cross-study collection endpoint
  - eCOA / eDiary Report (R9.5)
  - On-Demand / KRI / SDV-SDR Workload / Data Analysis / Comment /
    Source Document Tracker (R9.6)
  - End of Study (R9.7)

Endpoints (study-scoped unless noted):
  - GET /reports/enrollment-status                       cross-study enrollment (study.read)
  - GET /studies/{study_id}/reports/data-summary         (study.read)
  - GET /studies/{study_id}/reports/crf-status           (study.read)
  - GET /studies/{study_id}/reports/query-report         (study.read)
  - GET /studies/{study_id}/reports/enrollment-status    (study.read)
  - GET /studies/{study_id}/reports/ecoa-ediary          (study.read)
  - GET /studies/{study_id}/reports/operational          (study.read)
  - GET /studies/{study_id}/reports/end-of-study         (study.read)

Downloadable report output is produced through the shared export service via
the existing export routes (``data.export``); these endpoints return the
scope-filtered report payload directly.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.shared.identity import User
from app.schemas.edc.report import EnrollmentStatusReport, ReportResponse
from app.services.edc.report_service import report_service

logger = logging.getLogger(__name__)

# Reusable annotated dependency for DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Cross-study report collection (mounted at /reports)
# ---------------------------------------------------------------------------

reports_router = APIRouter(prefix="/reports", tags=["reports"])


@reports_router.get(
    "/enrollment-status",
    response_model=EnrollmentStatusReport,
)
async def get_enrollment_status_all(
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> EnrollmentStatusReport:
    """Enrollment Status across every study within the user's scope.

    Permission: study.read
    Requirement 9.4: Enrollment Status reports.
    Requirement 9.8/9.9: Only in-scope records; empty when nothing is in scope.
    """
    return await report_service.enrollment_status(session, current_user)


# ---------------------------------------------------------------------------
# Study-scoped reports (mounted at /studies)
# ---------------------------------------------------------------------------

study_reports_router = APIRouter(prefix="/studies", tags=["reports"])


@study_reports_router.get(
    "/{study_id}/reports/data-summary",
    response_model=ReportResponse,
)
async def get_data_summary(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="Data Summary section")] = "summary",
) -> ReportResponse:
    """Data Summary report for a study (R9.1), scope-filtered server-side."""
    return await report_service.data_summary(
        session, current_user, section=section, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/crf-status",
    response_model=ReportResponse,
)
async def get_crf_status(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="CRF Status section")] = "status_summary",
) -> ReportResponse:
    """CRF Status report for a study (R9.2), scope-filtered server-side."""
    return await report_service.crf_status(
        session, current_user, section=section, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/query-report",
    response_model=ReportResponse,
)
async def get_query_report(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="Query Report section")] = "all",
) -> ReportResponse:
    """Query Report for a study (R9.3), scope-filtered server-side."""
    return await report_service.query_report(
        session, current_user, section=section, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/enrollment-status",
    response_model=EnrollmentStatusReport,
)
async def get_enrollment_status(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
) -> EnrollmentStatusReport:
    """Enrollment Status report for a single study (R9.4).

    Permission: study.read
    Requirement 9.8/9.9: Only in-scope records; empty when nothing is in scope.
    An out-of-scope study yields an empty report rather than disclosing it.
    """
    return await report_service.enrollment_status(
        session, current_user, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/ecoa-ediary",
    response_model=ReportResponse,
)
async def get_ecoa_ediary_report(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="eCOA/eDiary section")] = "completion_rate",
) -> ReportResponse:
    """eCOA/eDiary Report for a study (R9.5), scope-filtered server-side."""
    return await report_service.ecoa_ediary_report(
        session, current_user, section=section, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/operational",
    response_model=ReportResponse,
)
async def get_operational_report(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="Operational report section")] = "on_demand",
) -> ReportResponse:
    """On-Demand/KRI/SDV-SDR Workload/Data Analysis/Comment/Source Doc Tracker (R9.6)."""
    return await report_service.operational_report(
        session, current_user, section=section, study_id=study_id
    )


@study_reports_router.get(
    "/{study_id}/reports/end-of-study",
    response_model=ReportResponse,
)
async def get_end_of_study_report(
    study_id: UUID,
    session: DbSession,
    current_user: Annotated[User, Depends(require_permission("study.read"))],
    section: Annotated[str, Query(description="End of Study section")] = "overview",
) -> ReportResponse:
    """End of Study report for a study (R9.7), scope-filtered server-side."""
    return await report_service.end_of_study(
        session, current_user, section=section, study_id=study_id
    )
