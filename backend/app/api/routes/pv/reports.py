"""PV regulatory reporting, clock, report state machine, and ICSR/E2B routes.

Thin, authenticated handlers under ``/api/v1/pv`` that delegate to the
``Regulatory_Reporting_Service``. Reportability evaluation, report transitions,
and submission own their validation and the atomic Safety_Data + PV safety
Audit_Event transaction boundary in the service. The ICSR produce/import
endpoints wrap the pure ``produce_e2b``/``parse_e2b`` functions (no external
gateway) and record one PV safety Audit_Event per action; neither creates or
mutates a Safety_Case. No route mutates an EDC clinical or CTMS operational
record.
"""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.core.exceptions import NotFoundError
from app.models.identity import User
from app.repositories.pv.regulatory_reporting_repository import (
    RegulatoryReportingRepository,
)
from app.schemas.pv.contracts import PVPaginatedResponse, PVPaginationParams
from app.schemas.pv.icsr import (
    ICSRImportRequest,
    ICSRImportResponse,
    ICSRProduceRequest,
    ICSRProduceResponse,
)
from app.schemas.pv.resources import (
    RegulatoryReportResponse,
    ReportabilityRequest,
    ReportSubmitRequest,
    ReportTransitionRequest,
)
from app.services.pv_atomicity_service import pv_atomicity_service
from app.services.regulatory_reporting_service import regulatory_reporting_service

router = APIRouter(tags=["pv-reports"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]
# ICSR produce/import and report lifecycle are reporting operations.
ReportGuard = Annotated[User, Depends(require_pv_permission("safety_report.manage"))]


# ---------------------------------------------------------------------------
# Reportability, report state machine, and reads
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/reportability",
    response_model=list[RegulatoryReportResponse],
    status_code=201,
)
async def evaluate_reportability(
    case_id: UUID,
    body: ReportabilityRequest,
    session: DbSession,
    current_user: ReportGuard,
) -> list[RegulatoryReportResponse]:
    """Create one Pending Regulatory_Report per matched configured rule."""

    reports = await regulatory_reporting_service.evaluate_reportability(
        session,
        case_id=case_id,
        awareness_date=body.awareness_date,
        actor=build_actor(current_user),
    )
    return [RegulatoryReportResponse.model_validate(report) for report in reports]


@router.get(
    "/cases/{case_id}/reports",
    response_model=PVPaginatedResponse[RegulatoryReportResponse],
)
async def list_case_reports(
    case_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PVPaginationParams, Depends()],
) -> PVPaginatedResponse[RegulatoryReportResponse]:
    """List the Regulatory_Reports for a Safety_Case."""

    repository = RegulatoryReportingRepository(session)
    reports = await repository.reports_for_case(case_id)
    start = pagination.offset
    window = reports[start : start + pagination.page_size]
    return PVPaginatedResponse[RegulatoryReportResponse](
        items=[RegulatoryReportResponse.model_validate(report) for report in window],
        page=pagination.page,
        page_size=pagination.page_size,
        total=len(reports),
    )


@router.get("/reports/{report_id}", response_model=RegulatoryReportResponse)
async def get_report(
    report_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
) -> RegulatoryReportResponse:
    """Return one Regulatory_Report by identifier."""

    repository = RegulatoryReportingRepository(session)
    report = await repository.get_report(report_id)
    if report is None:
        raise NotFoundError(
            message="Regulatory_Report was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "regulatory_report"},
        )
    return RegulatoryReportResponse.model_validate(report)


@router.post("/reports/{report_id}/transition", response_model=RegulatoryReportResponse)
async def transition_report(
    report_id: UUID,
    body: ReportTransitionRequest,
    session: DbSession,
    current_user: ReportGuard,
) -> RegulatoryReportResponse:
    """Apply a permitted non-submit Regulatory_Report status transition."""

    report = await regulatory_reporting_service.transition(
        session,
        report_id=report_id,
        target=body.target,
        actor=build_actor(current_user),
    )
    return RegulatoryReportResponse.model_validate(report)


@router.post("/reports/{report_id}/submit", response_model=RegulatoryReportResponse)
async def submit_report(
    report_id: UUID,
    body: ReportSubmitRequest,
    session: DbSession,
    current_user: ReportGuard,
) -> RegulatoryReportResponse:
    """Mark a Pending Regulatory_Report Submitted with an E2B_Message reference."""

    report = await regulatory_reporting_service.submit(
        session,
        report_id=report_id,
        e2b_message_ref=body.e2b_message_ref,
        actor=build_actor(current_user),
    )
    return RegulatoryReportResponse.model_validate(report)


# ---------------------------------------------------------------------------
# ICSR / E2B(R3)
# ---------------------------------------------------------------------------


@router.post("/icsr/produce", response_model=ICSRProduceResponse)
async def produce_icsr(
    body: ICSRProduceRequest,
    session: DbSession,
    current_user: ReportGuard,
) -> ICSRProduceResponse:
    """Produce an E2B(R3) message from a reportable Safety_Case representation.

    Delegates to the pure ``produce_e2b`` serializer. A case missing any
    mandatory E2B(R3) field yields a validation error naming each missing field
    and produces no message and no state change (Requirements 9.1, 9.2). One PV
    safety Audit_Event records the produce action.
    """

    message = regulatory_reporting_service.produce_e2b(body.case)

    entity_id = body.case_id or uuid4()
    await pv_atomicity_service.record_mutation(
        session,
        entity_type="icsr_message",
        entity_id=entity_id,
        action="produce",
        actor=build_actor(current_user),
        study_id=body.study_id,
        site_id=body.site_id,
    )
    return ICSRProduceResponse(message=message)


@router.post("/icsr/import", response_model=ICSRImportResponse)
async def import_icsr(
    body: ICSRImportRequest,
    session: DbSession,
    current_user: ReportGuard,
) -> ICSRImportResponse:
    """Parse a structurally valid E2B(R3) message into a case representation.

    Delegates to the pure ``parse_e2b`` parser. A structurally invalid message
    is rejected with a descriptive error and creates no Safety_Case
    (Requirements 9.3, 9.4). One PV safety Audit_Event records the import action.
    """

    parsed = regulatory_reporting_service.parse_e2b(body.message)

    dictionary_versions = dict(parsed.get("dictionary_versions", {}))
    case_identifier = str(parsed["case_identifier"])
    mandatory_fields = {
        key: value
        for key, value in parsed.items()
        if key not in {"case_identifier", "dictionary_versions"}
    }

    await pv_atomicity_service.record_mutation(
        session,
        entity_type="icsr_message",
        entity_id=uuid4(),
        action="import",
        actor=build_actor(current_user),
        study_id=body.study_id,
        site_id=body.site_id,
    )
    return ICSRImportResponse(
        case_identifier=case_identifier,
        mandatory_fields=mandatory_fields,
        dictionary_versions=dictionary_versions,
    )
