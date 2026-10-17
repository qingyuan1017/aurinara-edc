"""Completed CTMS portfolio workspaces and focused operational mutations."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.shared.identity import User
from app.schemas.ctms.portfolio_management import (
    AvailabilityExceptionCreate,
    CapacityPlanCreate,
    CapacityUtilizationRow,
    CAPACreate,
    CAPAPortfolioRow,
    CAPAResponse,
    CAPAUpdate,
    CRAAssignmentCreate,
    CRAAssignmentResponse,
    EscalationRow,
    FeasibilityCreate,
    FeasibilityPortfolioRow,
    FeasibilityResponse,
    FeasibilityUpdate,
    IssueRow,
    LifecycleTransition,
    OperationalTemplateCreate,
    PortfolioStudyRow,
    PortfolioSummary,
    PortfolioWorkRow,
    ScorecardCreate,
    ScorecardResponse,
    SitePerformanceRow,
    TemplateApplicationResponse,
    TemplateApplyRequest,
    TemplateResponse,
    TemplateVersionCreate,
    WorkflowDryRunRequest,
    WorkflowRuleCreate,
    WorkflowRuleResponse,
    WorkflowRuleVersionCreate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.portfolio_management_service import portfolio_management_service
from app.services.shared.permission_service import PermissionService

router = APIRouter(prefix="/portfolio", tags=["ctms-portfolio-management"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
StudyWrite = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]
SiteWrite = Annotated[User, Depends(require_ctms_permission("ctms.operational-site-management"))]
CAPAWrite = Annotated[User, Depends(require_ctms_permission("ctms.capa_management"))]
TemplateRuleAdmin = Annotated[
    User, Depends(require_ctms_permission("ctms.template_rule_management"))
]


def _page(items, pagination: PaginationParams, total: int, model):
    return PaginatedResponse(
        items=[model.model_validate(item) for item in items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/summary", response_model=PortfolioSummary)
async def summary(session: DbSession, current_user: CurrentUser):
    return PortfolioSummary.model_validate(
        await portfolio_management_service.summary(session, current_user)
    )


@router.get("/studies", response_model=PaginatedResponse[PortfolioStudyRow])
async def studies(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    search: Annotated[str | None, Query(max_length=200)] = None,
):
    rows, total = await portfolio_management_service.studies(
        session, current_user, page=pagination.page, page_size=pagination.page_size, search=search
    )
    return _page(rows, pagination, total, PortfolioStudyRow)


@router.get("/work", response_model=PaginatedResponse[PortfolioWorkRow])
async def work(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.work(
        session, current_user, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, PortfolioWorkRow)


@router.get("/tasks", response_model=PaginatedResponse[PortfolioWorkRow])
async def tasks(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    owner_id: UUID | None = None,
    status: str | None = None,
    mine: bool = False,
):
    rows, total = await portfolio_management_service.tasks(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        owner_id=owner_id,
        status=status,
        mine=mine,
    )
    return _page(rows, pagination, total, PortfolioWorkRow)


@router.get("/sites/feasibility", response_model=PaginatedResponse[FeasibilityPortfolioRow])
async def feasibility(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
):
    rows, total = await portfolio_management_service.feasibility(
        session, current_user, page=pagination.page, page_size=pagination.page_size, status=status
    )
    return _page(rows, pagination, total, FeasibilityPortfolioRow)


@router.post("/sites/feasibility", response_model=FeasibilityResponse, status_code=201)
async def create_feasibility(body: FeasibilityCreate, session: DbSession, current_user: SiteWrite):
    return FeasibilityResponse.model_validate(
        await portfolio_management_service.create_feasibility(
            session, current_user, body, get_correlation_id()
        )
    )


@router.patch("/sites/feasibility/{assessment_id}", response_model=FeasibilityResponse)
async def update_feasibility(
    assessment_id: UUID, body: FeasibilityUpdate, session: DbSession, current_user: SiteWrite
):
    return FeasibilityResponse.model_validate(
        await portfolio_management_service.update_feasibility(
            session, current_user, assessment_id, body, get_correlation_id()
        )
    )


@router.post("/sites/feasibility/{assessment_id}/transition", response_model=FeasibilityResponse)
async def transition_feasibility(
    assessment_id: UUID, body: LifecycleTransition, session: DbSession, current_user: SiteWrite
):
    return FeasibilityResponse.model_validate(
        await portfolio_management_service.transition_feasibility(
            session, current_user, assessment_id, body, get_correlation_id()
        )
    )


@router.get("/sites/performance", response_model=PaginatedResponse[SitePerformanceRow])
async def performance(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
):
    rows, total = await portfolio_management_service.performance(
        session, current_user, page=pagination.page, page_size=pagination.page_size, site_id=site_id
    )
    return _page(rows, pagination, total, SitePerformanceRow)


@router.get("/sites/{site_id}/performance-trend", response_model=list[dict[str, Any]])
async def performance_trend(site_id: UUID, session: DbSession, current_user: CurrentUser):
    return await portfolio_management_service.performance_trend(session, current_user, site_id)


@router.get("/sites/performance-scorecards", response_model=PaginatedResponse[ScorecardResponse])
async def performance_scorecards(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.list_scorecards(
        session, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, ScorecardResponse)


@router.post("/sites/performance-scorecards", response_model=ScorecardResponse, status_code=201)
async def create_performance_scorecard(
    body: ScorecardCreate, session: DbSession, current_user: TemplateRuleAdmin
):
    return ScorecardResponse.model_validate(
        await portfolio_management_service.create_scorecard(session, current_user, body)
    )


@router.post(
    "/sites/performance-scorecards/{scorecard_id}/publish",
    response_model=ScorecardResponse,
)
async def publish_performance_scorecard(
    scorecard_id: UUID,
    body: LifecycleTransition,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    return ScorecardResponse.model_validate(
        await portfolio_management_service.publish_scorecard(
            session, current_user, scorecard_id, body.reason
        )
    )


@router.get("/issues", response_model=PaginatedResponse[IssueRow])
async def issues(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.issues(
        session, current_user, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, IssueRow)


@router.get("/escalations", response_model=PaginatedResponse[EscalationRow])
async def escalations(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.escalations(
        session, current_user, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, EscalationRow)


@router.get("/capas", response_model=PaginatedResponse[CAPAPortfolioRow])
async def capas(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
):
    rows, total = await portfolio_management_service.capas(
        session, current_user, page=pagination.page, page_size=pagination.page_size, status=status
    )
    return _page(rows, pagination, total, CAPAPortfolioRow)


@router.post("/capas", response_model=CAPAResponse, status_code=201)
async def create_capa(body: CAPACreate, session: DbSession, current_user: CAPAWrite):
    return CAPAResponse.model_validate(
        await portfolio_management_service.create_capa(
            session, current_user, body, get_correlation_id()
        )
    )


@router.patch("/capas/{capa_id}", response_model=CAPAResponse)
async def update_capa(capa_id: UUID, body: CAPAUpdate, session: DbSession, current_user: CAPAWrite):
    return CAPAResponse.model_validate(
        await portfolio_management_service.update_capa(
            session, current_user, capa_id, body, get_correlation_id()
        )
    )


@router.post("/capas/{capa_id}/transition", response_model=CAPAResponse)
async def transition_capa(
    capa_id: UUID, body: LifecycleTransition, session: DbSession, current_user: CAPAWrite
):
    return CAPAResponse.model_validate(
        await portfolio_management_service.transition_capa(
            session, current_user, capa_id, body, get_correlation_id()
        )
    )


@router.get("/templates", response_model=PaginatedResponse[TemplateResponse])
async def templates(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    published_only: bool = False,
):
    rows, total = await portfolio_management_service.list_templates(
        session, page=pagination.page, page_size=pagination.page_size, published_only=published_only
    )
    return _page(rows, pagination, total, TemplateResponse)


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: OperationalTemplateCreate, session: DbSession, current_user: TemplateRuleAdmin
):
    template, version = await portfolio_management_service.create_template(
        session, current_user, body
    )
    return TemplateResponse.model_validate(
        {
            "id": template.id,
            "name": template.name,
            "template_type": template.template_type,
            "description": template.description,
            "retired_at": template.retired_at,
            "version_id": version.id,
            "version_number": version.version_number,
            "version_status": version.status,
            "content": version.content_json,
            "created_at": template.created_at,
        }
    )


@router.post("/templates/{template_id}/versions", response_model=TemplateResponse, status_code=201)
async def create_template_version(
    template_id: UUID,
    body: TemplateVersionCreate,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    template, version = await portfolio_management_service.create_template_version(
        session, current_user, template_id, body
    )
    return TemplateResponse.model_validate(
        {
            "id": template.id,
            "name": template.name,
            "template_type": template.template_type,
            "description": template.description,
            "retired_at": template.retired_at,
            "version_id": version.id,
            "version_number": version.version_number,
            "version_status": version.status,
            "content": version.content_json,
            "created_at": template.created_at,
        }
    )


@router.post("/template-versions/{version_id}/publish", response_model=dict[str, Any])
async def publish_template(
    version_id: UUID,
    body: LifecycleTransition,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    version = await portfolio_management_service.publish_template(
        session, current_user, version_id, body.reason
    )
    return {"id": version.id, "status": version.status, "published_at": version.published_at}


@router.post("/templates/{template_id}/retire", response_model=dict[str, Any])
async def retire_template(
    template_id: UUID,
    body: LifecycleTransition,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    template = await portfolio_management_service.retire_template(
        session, current_user, template_id, body.reason
    )
    return {"id": template.id, "status": "Retired", "retired_at": template.retired_at}


@router.post("/template-versions/{version_id}/apply", response_model=TemplateApplicationResponse)
async def apply_template(
    version_id: UUID, body: TemplateApplyRequest, session: DbSession, current_user: StudyWrite
):
    application, result = await portfolio_management_service.apply_template(
        session, current_user, version_id, body, get_correlation_id()
    )
    return TemplateApplicationResponse(
        application_id=application.id if application else None,
        template_version_id=version_id,
        study_id=body.study_id,
        preview=body.preview_only,
        result=result,
    )


@router.get("/workflows", response_model=PaginatedResponse[WorkflowRuleResponse])
async def workflows(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.list_workflows(
        session, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, WorkflowRuleResponse)


@router.post("/workflows", response_model=WorkflowRuleResponse, status_code=201)
async def create_workflow(
    body: WorkflowRuleCreate, session: DbSession, current_user: TemplateRuleAdmin
):
    rule, version = await portfolio_management_service.create_workflow(session, current_user, body)
    return WorkflowRuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        version_id=version.id,
        version_number=version.version_number,
        status=version.status,
        trigger_type=version.trigger_type,
        conditions=version.conditions_json,
        actions=version.actions_json,
        created_at=rule.created_at,
    )


@router.post("/workflows/{rule_id}/versions", response_model=WorkflowRuleResponse, status_code=201)
async def create_workflow_version(
    rule_id: UUID,
    body: WorkflowRuleVersionCreate,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    rule, version = await portfolio_management_service.create_workflow_version(
        session, current_user, rule_id, body
    )
    return WorkflowRuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        version_id=version.id,
        version_number=version.version_number,
        status=version.status,
        trigger_type=version.trigger_type,
        conditions=version.conditions_json,
        actions=version.actions_json,
        created_at=rule.created_at,
    )


@router.post("/workflow-versions/{version_id}/transition", response_model=dict[str, Any])
async def transition_workflow(
    version_id: UUID,
    body: LifecycleTransition,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    version = await portfolio_management_service.set_workflow_status(
        session, current_user, version_id, body.status, body.reason
    )
    return {"id": version.id, "status": version.status}


@router.post("/workflow-versions/{version_id}/dry-run", response_model=dict[str, Any])
async def dry_run_workflow(
    version_id: UUID,
    body: WorkflowDryRunRequest,
    session: DbSession,
    current_user: TemplateRuleAdmin,
):
    # Dry-run deliberately performs no writes; it exposes the typed sample and
    # proposed actions for human confirmation.
    from app.models.ctms.portfolio_management import WorkflowRuleVersion

    version = await session.get(WorkflowRuleVersion, version_id)
    if version is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Workflow version not found")
    return {
        "matched": all(body.sample.get(k) == v for k, v in version.conditions_json.items()),
        "trigger_type": version.trigger_type,
        "proposed_actions": version.actions_json,
        "mutated": False,
    }


@router.get("/resources/cra-assignments", response_model=PaginatedResponse[CRAAssignmentResponse])
async def cra_assignments(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.cra_assignments(
        session, current_user, page=pagination.page, page_size=pagination.page_size
    )
    return _page(rows, pagination, total, CRAAssignmentResponse)


@router.post("/resources/cra-assignments", response_model=CRAAssignmentResponse, status_code=201)
async def create_assignment(
    body: CRAAssignmentCreate, session: DbSession, current_user: StudyWrite
):
    permission = PermissionService().resolve_scope(current_user)
    can_override = permission.has_permission(
        "ctms.capacity_override", study_id=body.study_id, site_id=body.site_id
    )
    item = await portfolio_management_service.create_assignment(
        session, current_user, body, get_correlation_id(), can_override=can_override
    )
    return CRAAssignmentResponse.model_validate(
        {**item.__dict__, "user_name": None, "study_code": None, "site_label": None}
    )


@router.get("/resources/capacity", response_model=PaginatedResponse[dict[str, Any]])
async def capacity(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.capacity(
        session, current_user, page=pagination.page, page_size=pagination.page_size
    )
    return PaginatedResponse(
        items=rows, page=pagination.page, page_size=pagination.page_size, total=total
    )


@router.post("/resources/capacity", response_model=dict[str, Any], status_code=201)
async def create_capacity(body: CapacityPlanCreate, session: DbSession, current_user: StudyWrite):
    item = await portfolio_management_service.create_capacity(session, current_user, body)
    return {
        "id": item.id,
        "user_id": item.user_id,
        "week_start": item.week_start,
        "capacity_hours": item.capacity_hours,
        "timezone": item.timezone,
    }


@router.post("/resources/availability-exceptions", response_model=dict[str, Any], status_code=201)
async def create_availability_exception(
    body: AvailabilityExceptionCreate, session: DbSession, current_user: StudyWrite
):
    item = await portfolio_management_service.create_exception(session, current_user, body)
    return {
        "id": item.id,
        "user_id": item.user_id,
        "exception_date": item.exception_date,
        "exception_type": item.exception_type,
        "unavailable_hours": item.unavailable_hours,
        "reason": item.reason,
    }


@router.get("/resources/utilization", response_model=PaginatedResponse[CapacityUtilizationRow])
async def utilization(
    session: DbSession,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends()],
    week_start: date | None = None,
):
    rows, total = await portfolio_management_service.utilization(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        week_start=week_start,
    )
    return _page(rows, pagination, total, CapacityUtilizationRow)


__all__ = ["router"]
