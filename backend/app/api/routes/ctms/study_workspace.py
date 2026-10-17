"""Study-scoped CTMS workspace reads and focused lifecycle mutations."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.study_workspace import (
    ICFSiteRollout,
    ICFVersion,
    KRIDefinition,
    ProtocolDeviationFollowUp,
    RiskAssessment,
    SiteCloseoutItem,
    SiteCloseoutPlan,
    StudyAmendment,
    StudyTrackingLog,
    TrackingLogEntry,
)
from app.models.ctms.work import TaskEscalation
from app.models.shared.identity import User
from app.schemas.ctms.portfolio_management import (
    CAPAPortfolioRow,
    FeasibilityPortfolioRow,
    SitePerformanceRow,
)
from app.schemas.ctms.site import ActivationActionResponse
from app.schemas.ctms.study_workspace import (
    ActionIssueRow,
    ActivityRow,
    AmendmentCreate,
    AmendmentImpactCreate,
    AmendmentResponse,
    CloseoutCreate,
    CloseoutItemCreate,
    CloseoutItemUpdate,
    CloseoutResponse,
    HealthSignal,
    ICFEvidenceUpdate,
    ICFRolloutCreate,
    ICFRolloutResponse,
    ICFVersionCreate,
    KRICreate,
    KRIObservationCreate,
    KRIResponse,
    KRIVersionCreate,
    ProtocolDeviationCreate,
    ProtocolDeviationResponse,
    RiskAssessmentCreate,
    RiskAssessmentResponse,
    RiskAssessmentVersionCreate,
    RiskItemCreate,
    SiteStudyRow,
    StudySummary,
    TaskDependencyCreate,
    TaskEscalationCreate,
    TaskEscalationTransition,
    TeamAssignmentCreate,
    TeamAssignmentResponse,
    TeamAssignmentUpdate,
    TrackingDefinitionCreate,
    TrackingDefinitionVersionCreate,
    TrackingEntryCreate,
    TrackingEntryRevisionCreate,
    TrackingLogCreate,
    TrackingLogResponse,
    TransitionRequest,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.ctms.portfolio_management_service import portfolio_management_service
from app.services.ctms.study_workspace_service import study_workspace_service
from app.services.ctms.work_management_service import work_management_service

router = APIRouter(prefix="/studies/{study_id}", tags=["ctms-study-workspace"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
StudyWrite = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]
SiteWrite = Annotated[User, Depends(require_ctms_permission("ctms.operational-site-management"))]
MonitorWrite = Annotated[
    User, Depends(require_ctms_permission("ctms.monitoring-activity-management"))
]
AdminWrite = Annotated[User, Depends(require_ctms_permission("ctms.template_rule_management"))]


def _page(items: list[Any], pagination: PaginationParams, total: int, model):
    return PaginatedResponse(
        items=[model.model_validate(item) for item in items],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


def _record(item: Any) -> dict[str, Any]:
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


@router.get("/summary", response_model=StudySummary)
async def summary(study_id: UUID, session: DbSession, current_user: Read):
    return StudySummary.model_validate(await study_workspace_service.summary(session, study_id))


@router.get("/operational-health", response_model=list[HealthSignal])
async def operational_health(study_id: UUID, session: DbSession, current_user: Read):
    return await study_workspace_service.health(session, study_id)


@router.get("/activity", response_model=PaginatedResponse[ActivityRow])
async def activity(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.activity(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ActivityRow)


@router.get("/team", response_model=PaginatedResponse[TeamAssignmentResponse])
async def team(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.team(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, TeamAssignmentResponse)


@router.post("/team", response_model=dict[str, Any], status_code=201)
async def create_team(
    study_id: UUID, body: TeamAssignmentCreate, session: DbSession, current_user: StudyWrite
):
    return _record(
        await study_workspace_service.create_team(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.patch("/team/{assignment_id}", response_model=dict[str, Any])
async def update_team(
    study_id: UUID,
    assignment_id: UUID,
    body: TeamAssignmentUpdate,
    session: DbSession,
    current_user: StudyWrite,
):
    return _record(
        await study_workspace_service.update_team(
            session,
            study_id,
            assignment_id,
            current_user,
            body,
            get_correlation_id(),
        )
    )


@router.get("/amendments", response_model=PaginatedResponse[AmendmentResponse])
async def amendments(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.amendments(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, AmendmentResponse)


@router.post("/amendments", response_model=dict[str, Any], status_code=201)
async def create_amendment(
    study_id: UUID, body: AmendmentCreate, session: DbSession, current_user: StudyWrite
):
    return _record(
        await study_workspace_service.create_amendment(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/amendments/{amendment_id}/impacts", response_model=dict[str, Any], status_code=201)
async def add_amendment_impact(
    study_id: UUID,
    amendment_id: UUID,
    body: AmendmentImpactCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, StudyAmendment, amendment_id, study_id)
    item = await study_workspace_service.add_amendment_impact(
        session, amendment_id, current_user, body, get_correlation_id()
    )
    if item.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Study amendment not found")
    return _record(item)


@router.post("/amendments/{amendment_id}/transition", response_model=dict[str, Any])
async def transition_amendment(
    study_id: UUID,
    amendment_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, StudyAmendment, amendment_id, study_id)
    item = await study_workspace_service.transition_amendment(
        session, amendment_id, current_user, body, get_correlation_id()
    )
    if item.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Study amendment not found")
    return _record(item)


@router.get("/sites", response_model=PaginatedResponse[SiteStudyRow])
async def sites(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.sites(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, SiteStudyRow)


@router.get("/sites/feasibility", response_model=PaginatedResponse[FeasibilityPortfolioRow])
async def feasibility(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.feasibility(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
    )
    return _page(rows, pagination, total, FeasibilityPortfolioRow)


@router.get("/sites/startup", response_model=PaginatedResponse[ActivationActionResponse])
async def startup(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.startup(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ActivationActionResponse)


@router.get("/sites/performance", response_model=PaginatedResponse[SitePerformanceRow])
async def performance(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.performance(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
    )
    return _page(rows, pagination, total, SitePerformanceRow)


@router.get("/sites/closeout", response_model=PaginatedResponse[CloseoutResponse])
async def closeout(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.closeouts(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, CloseoutResponse)


@router.post("/sites/closeout", response_model=dict[str, Any], status_code=201)
async def create_closeout(
    study_id: UUID, body: CloseoutCreate, session: DbSession, current_user: SiteWrite
):
    return _record(
        await study_workspace_service.create_closeout(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/sites/closeout/{plan_id}/items", response_model=dict[str, Any], status_code=201)
async def add_closeout_item(
    study_id: UUID,
    plan_id: UUID,
    body: CloseoutItemCreate,
    session: DbSession,
    current_user: SiteWrite,
):
    await study_workspace_service.record_in_study(session, SiteCloseoutPlan, plan_id, study_id)
    item = await study_workspace_service.add_closeout_item(
        session, plan_id, current_user, body, get_correlation_id()
    )
    return _record(item)


@router.patch("/sites/closeout/items/{item_id}", response_model=dict[str, Any])
async def update_closeout_item(
    study_id: UUID,
    item_id: UUID,
    body: CloseoutItemUpdate,
    session: DbSession,
    current_user: SiteWrite,
):
    await study_workspace_service.record_in_study(session, SiteCloseoutItem, item_id, study_id)
    return _record(
        await study_workspace_service.update_closeout_item(
            session, item_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/sites/closeout/{plan_id}/transition", response_model=dict[str, Any])
async def transition_closeout(
    study_id: UUID,
    plan_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: SiteWrite,
):
    await study_workspace_service.record_in_study(session, SiteCloseoutPlan, plan_id, study_id)
    return _record(
        await study_workspace_service.transition_closeout(
            session, plan_id, current_user, body, get_correlation_id()
        )
    )


@router.get("/action-items", response_model=PaginatedResponse[ActionIssueRow])
async def action_items(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.action_items(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ActionIssueRow)


@router.get("/issues", response_model=PaginatedResponse[ActionIssueRow])
async def issues(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.issues(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ActionIssueRow)


@router.get("/escalations", response_model=PaginatedResponse[dict[str, Any]])
async def escalations(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.escalations(
        session, study_id, pagination.page, pagination.page_size
    )
    return PaginatedResponse(
        items=rows, page=pagination.page, page_size=pagination.page_size, total=total
    )


@router.get("/capas", response_model=PaginatedResponse[CAPAPortfolioRow])
async def capas(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await portfolio_management_service.capas(
        session,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        study_id=study_id,
    )
    return _page(rows, pagination, total, CAPAPortfolioRow)


@router.get("/risk-assessments", response_model=PaginatedResponse[RiskAssessmentResponse])
async def racts(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.racts(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, RiskAssessmentResponse)


@router.post("/risk-assessments", response_model=dict[str, Any], status_code=201)
async def create_ract(
    study_id: UUID, body: RiskAssessmentCreate, session: DbSession, current_user: MonitorWrite
):
    return _record(
        await study_workspace_service.create_ract(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post(
    "/risk-assessments/{assessment_id}/items", response_model=dict[str, Any], status_code=201
)
async def add_risk_item(
    study_id: UUID,
    assessment_id: UUID,
    body: RiskItemCreate,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, RiskAssessment, assessment_id, study_id)
    return _record(
        await study_workspace_service.add_risk_item(
            session, assessment_id, current_user, body, get_correlation_id()
        )
    )


@router.post(
    "/risk-assessments/{assessment_id}/versions", response_model=dict[str, Any], status_code=201
)
async def create_ract_version(
    study_id: UUID,
    assessment_id: UUID,
    body: RiskAssessmentVersionCreate,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, RiskAssessment, assessment_id, study_id)
    return _record(
        await study_workspace_service.create_ract_version(
            session, assessment_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/risk-assessments/{assessment_id}/transition", response_model=dict[str, Any])
async def transition_ract(
    study_id: UUID,
    assessment_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, RiskAssessment, assessment_id, study_id)
    return _record(
        await study_workspace_service.transition_ract(
            session, assessment_id, current_user, body, get_correlation_id()
        )
    )


@router.get("/kris", response_model=PaginatedResponse[KRIResponse])
async def kris(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.kris(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, KRIResponse)


@router.post("/kris", response_model=dict[str, Any], status_code=201)
async def create_kri(
    study_id: UUID, body: KRICreate, session: DbSession, current_user: MonitorWrite
):
    return _record(
        await study_workspace_service.create_kri(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/kris/{kri_id}/observations", response_model=dict[str, Any], status_code=201)
async def observe_kri(
    study_id: UUID,
    kri_id: UUID,
    body: KRIObservationCreate,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, KRIDefinition, kri_id, study_id)
    return _record(
        await study_workspace_service.observe_kri(
            session,
            kri_id,
            current_user,
            body,
            get_correlation_id(),
        )
    )


@router.post("/kris/{kri_id}/versions", response_model=dict[str, Any], status_code=201)
async def create_kri_version(
    study_id: UUID,
    kri_id: UUID,
    body: KRIVersionCreate,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, KRIDefinition, kri_id, study_id)
    return _record(
        await study_workspace_service.create_kri_version(
            session, kri_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/kris/{kri_id}/transition", response_model=dict[str, Any])
async def transition_kri(
    study_id: UUID,
    kri_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(session, KRIDefinition, kri_id, study_id)
    return _record(
        await study_workspace_service.transition_kri(
            session, kri_id, current_user, body, get_correlation_id()
        )
    )


@router.get("/protocol-deviations", response_model=PaginatedResponse[ProtocolDeviationResponse])
async def protocol_deviations(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.protocol_deviations(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ProtocolDeviationResponse)


@router.post("/protocol-deviations", response_model=dict[str, Any], status_code=201)
async def create_protocol_deviation(
    study_id: UUID, body: ProtocolDeviationCreate, session: DbSession, current_user: MonitorWrite
):
    return _record(
        await study_workspace_service.create_pd(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/protocol-deviations/{followup_id}/transition", response_model=dict[str, Any])
async def transition_protocol_deviation(
    study_id: UUID,
    followup_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: MonitorWrite,
):
    await study_workspace_service.record_in_study(
        session, ProtocolDeviationFollowUp, followup_id, study_id
    )
    return _record(
        await study_workspace_service.transition_pd(
            session, followup_id, current_user, body, get_correlation_id()
        )
    )


@router.get("/icf-rollouts", response_model=PaginatedResponse[ICFRolloutResponse])
async def icf_rollouts(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.icf_rollouts(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, ICFRolloutResponse)


@router.post("/icf-versions", response_model=dict[str, Any], status_code=201)
async def create_icf_version(
    study_id: UUID, body: ICFVersionCreate, session: DbSession, current_user: StudyWrite
):
    return _record(
        await study_workspace_service.create_icf_version(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/icf-versions/{version_id}/rollouts", response_model=dict[str, Any], status_code=201)
async def create_icf_rollout(
    study_id: UUID,
    version_id: UUID,
    body: ICFRolloutCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, ICFVersion, version_id, study_id)
    return _record(
        await study_workspace_service.create_icf_rollout(
            session, version_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/icf-rollouts/{rollout_id}/transition", response_model=dict[str, Any])
async def transition_icf(
    study_id: UUID,
    rollout_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, ICFSiteRollout, rollout_id, study_id)
    return _record(
        await study_workspace_service.transition_icf(
            session, rollout_id, current_user, body, get_correlation_id()
        )
    )


@router.patch("/icf-rollouts/{rollout_id}/evidence", response_model=dict[str, Any])
async def update_icf_evidence(
    study_id: UUID,
    rollout_id: UUID,
    body: ICFEvidenceUpdate,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, ICFSiteRollout, rollout_id, study_id)
    return _record(
        await study_workspace_service.update_icf_evidence(
            session, rollout_id, current_user, body, get_correlation_id()
        )
    )


@router.get("/tracking-logs", response_model=PaginatedResponse[TrackingLogResponse])
async def tracking_logs(
    study_id: UUID,
    session: DbSession,
    current_user: Read,
    pagination: Annotated[PaginationParams, Depends()],
):
    rows, total = await study_workspace_service.tracking_logs(
        session, study_id, pagination.page, pagination.page_size
    )
    return _page(rows, pagination, total, TrackingLogResponse)


@router.post("/tracking-log-definitions", response_model=dict[str, Any], status_code=201)
async def create_tracking_definition(
    study_id: UUID, body: TrackingDefinitionCreate, session: DbSession, current_user: AdminWrite
):
    definition, version = await study_workspace_service.create_tracking_definition(
        session, current_user, body, get_correlation_id()
    )
    return {"definition": _record(definition), "version": _record(version)}


@router.post(
    "/tracking-log-definitions/{definition_id}/versions",
    response_model=dict[str, Any],
    status_code=201,
)
async def create_tracking_definition_version(
    study_id: UUID,
    definition_id: UUID,
    body: TrackingDefinitionVersionCreate,
    session: DbSession,
    current_user: AdminWrite,
):
    return _record(
        await study_workspace_service.create_tracking_definition_version(
            session,
            definition_id,
            current_user,
            body,
            get_correlation_id(),
        )
    )


@router.post(
    "/tracking-log-definition-versions/{version_id}/transition",
    response_model=dict[str, Any],
)
async def transition_tracking_definition(
    study_id: UUID,
    version_id: UUID,
    body: TransitionRequest,
    session: DbSession,
    current_user: AdminWrite,
):
    return _record(
        await study_workspace_service.transition_tracking_definition(
            session, version_id, current_user, body
        )
    )


@router.post("/tracking-logs", response_model=dict[str, Any], status_code=201)
async def create_tracking_log(
    study_id: UUID, body: TrackingLogCreate, session: DbSession, current_user: StudyWrite
):
    return _record(
        await study_workspace_service.create_tracking_log(
            session, study_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/tracking-logs/{log_id}/entries", response_model=dict[str, Any], status_code=201)
async def create_tracking_entry(
    study_id: UUID,
    log_id: UUID,
    body: TrackingEntryCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, StudyTrackingLog, log_id, study_id)
    return _record(
        await study_workspace_service.create_tracking_entry(
            session, log_id, current_user, body, get_correlation_id()
        )
    )


@router.post("/tracking-log-entries/{entry_id}/revisions", response_model=dict[str, Any])
async def revise_tracking_entry(
    study_id: UUID,
    entry_id: UUID,
    body: TrackingEntryRevisionCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    await study_workspace_service.record_in_study(session, TrackingLogEntry, entry_id, study_id)
    return _record(
        await study_workspace_service.revise_tracking_entry(
            session,
            entry_id,
            current_user,
            body,
            get_correlation_id(),
        )
    )


@router.get("/tasks/{task_id}/dependencies", response_model=list[dict[str, Any]])
async def task_dependencies(study_id: UUID, task_id: UUID, session: DbSession, current_user: Read):
    task = await work_management_service._resolve_task(session, task_id)
    if task.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Operational task was not found")
    return [_record(item) for item in await work_management_service._dependencies(session, task_id)]


@router.post("/tasks/{task_id}/dependencies", response_model=dict[str, Any], status_code=201)
async def add_task_dependency(
    study_id: UUID,
    task_id: UUID,
    body: TaskDependencyCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    task = await work_management_service._resolve_task(session, task_id)
    if task.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Operational task was not found")
    item = await work_management_service.add_dependency(
        session,
        task_id,
        body.depends_on_task_id,
        current_user.id,
        reason=body.reason,
        correlation_id=get_correlation_id(),
    )
    return _record(item)


@router.post("/tasks/{task_id}/escalations", response_model=dict[str, Any], status_code=201)
async def create_task_escalation(
    study_id: UUID,
    task_id: UUID,
    body: TaskEscalationCreate,
    session: DbSession,
    current_user: StudyWrite,
):
    task = await work_management_service._resolve_task(session, task_id)
    if task.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Operational task was not found")
    item = await work_management_service.create_escalation(
        session,
        {
            "task_id": task_id,
            "owner_id": body.owner_id,
            "reason": body.reason,
            "deadline": body.deadline,
        },
        current_user.id,
        correlation_id=get_correlation_id(),
    )
    return _record(item)


@router.post("/escalations/{escalation_id}/transition", response_model=dict[str, Any])
async def transition_task_escalation(
    study_id: UUID,
    escalation_id: UUID,
    body: TaskEscalationTransition,
    session: DbSession,
    current_user: StudyWrite,
):
    escalation = await session.get(TaskEscalation, escalation_id)
    if not escalation:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Task escalation was not found")
    task = await work_management_service._resolve_task(session, escalation.task_id)
    if task.study_id != study_id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Task escalation was not found")
    item = await work_management_service.transition_escalation_status(
        session,
        escalation,
        body.status,
        current_user.id,
        reason=body.reason,
        correlation_id=get_correlation_id(),
    )
    return _record(item)


__all__ = ["router"]
