"""Core EDC operational worklists, listings, SDR, and controlled locks."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_user, get_db, get_permission_service
from app.core.exceptions import AuthorizationError
from app.models.shared.identity import User
from app.schemas.edc.operations import (
    ClinicalControlDecision,
    ClinicalControlRequestCreate,
    ClinicalControlRequestResponse,
    EDCCapabilities,
    FormWorklistItem,
    ListingCatalogItem,
    ListingRow,
    LockReadinessResponse,
    QualityWorklistItem,
    SDRResultResponse,
    SDRReviewUpdate,
)
from app.schemas.shared.base import PaginatedResponse
from app.services.edc.clinical_control_service import clinical_control_service
from app.services.edc.operational_service import edc_operational_service
from app.services.edc.scope_service import edc_scope_service
from app.services.edc.sdr_service import sdr_service
from app.services.shared.permission_service import PermissionService

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
PermissionSvc = Annotated[PermissionService, Depends(get_permission_service)]

router = APIRouter(tags=["edc-operations"])


def _permission_with_legacy(
    user: User,
    permissions: PermissionService,
    new_code: str,
    legacy_code: str | None,
    study_id: UUID,
) -> str:
    try:
        permissions.require(user, new_code, study_id=study_id)
        return new_code
    except AuthorizationError:
        if legacy_code is None:
            raise
        permissions.require(user, legacy_code, study_id=study_id)
        return legacy_code


def _authorized_sites_with_legacy(
    user: User,
    permissions: PermissionService,
    new_code: str,
    legacy_code: str,
    study_id: UUID,
) -> tuple[str, set[UUID] | None]:
    try:
        return new_code, edc_scope_service.authorized_site_ids(
            user, permissions, new_code, study_id
        )
    except AuthorizationError:
        return legacy_code, edc_scope_service.authorized_site_ids(
            user, permissions, legacy_code, study_id
        )


@router.get("/studies/{study_id}/edc-capabilities", response_model=EDCCapabilities)
async def capabilities(
    study_id: UUID,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> EDCCapabilities:
    _authorized_sites_with_legacy(
        current_user, permission_service, "study.read", "form.read", study_id
    )
    return edc_operational_service.capabilities()


@router.get(
    "/studies/{study_id}/form-worklist",
    response_model=PaginatedResponse[FormWorklistItem],
)
async def form_worklist(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    state: str | None = None,
) -> Any:
    site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, "form.read", study_id
    )
    return await edc_operational_service.form_worklist(
        session,
        study_id,
        pagination,
        authorized_site_ids=site_ids,
        site_id=site_id,
        subject_id=subject_id,
        state=state,
    )


@router.get(
    "/studies/{study_id}/quality-worklist",
    response_model=PaginatedResponse[QualityWorklistItem],
)
async def quality_worklist(
    study_id: UUID,
    workflow: Literal["review", "sdv", "sdr"],
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
    status: str | None = None,
) -> Any:
    permission = {
        "review": ("review.read", "review.manage"),
        "sdv": ("sdv.read", "sdv.manage"),
        "sdr": ("sdr.read", "sdr.manage"),
    }[workflow]
    selected_permission = _permission_with_legacy(
        current_user, permission_service, permission[0], permission[1], study_id
    )
    site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, selected_permission, study_id
    )
    if workflow == "sdr":
        await sdr_service.materialize(session, study_id)
    return await edc_operational_service.quality_worklist(
        session,
        study_id,
        pagination,
        workflow=workflow,
        authorized_site_ids=site_ids,
        site_id=site_id,
        subject_id=subject_id,
        status=status,
    )


@router.get("/studies/{study_id}/listings/catalog", response_model=list[ListingCatalogItem])
async def listing_catalog(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> list[ListingCatalogItem]:
    _authorized_sites_with_legacy(
        current_user, permission_service, "listing.read", "form.read", study_id
    )
    return await edc_operational_service.listing_catalog(
        session,
        study_id,
        role_names=_role_names(current_user, study_id),
    )


@router.get(
    "/studies/{study_id}/listings/{dataset}/rows",
    response_model=PaginatedResponse[ListingRow],
)
async def listing_rows(
    study_id: UUID,
    dataset: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    pagination: Annotated[PaginationParams, Depends()],
    site_id: UUID | None = None,
    subject_id: UUID | None = None,
) -> Any:
    permission = _permission_with_legacy(
        current_user, permission_service, "listing.read", "form.read", study_id
    )
    site_ids = edc_scope_service.authorized_site_ids(
        current_user, permission_service, permission, study_id
    )
    return await edc_operational_service.listing_rows(
        session,
        study_id,
        dataset,
        pagination,
        role_names=_role_names(current_user, study_id),
        authorized_site_ids=site_ids,
        site_id=site_id,
        subject_id=subject_id,
    )


def _role_names(current_user: User, study_id: UUID) -> set[str]:
    """Return role names assigned globally or within the requested study."""
    return {
        assignment.role.name
        for assignment in current_user.user_roles
        if assignment.study_id is None or assignment.study_id == study_id
    }


@router.post("/sdr-selections/{selection_id}/review", response_model=SDRResultResponse)
async def review_sdr(
    selection_id: UUID,
    body: SDRReviewUpdate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> SDRResultResponse:
    from app.models.edc.operations import SDRSelection

    selection = await session.get(SDRSelection, selection_id)
    if selection is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(message="SDR selection not found", details={})
    edc_scope_service.require_scope(
        current_user,
        permission_service,
        "sdr.manage",
        study_id=selection.study_id,
        site_id=selection.site_id,
    )
    return SDRResultResponse.model_validate(
        await sdr_service.review(session, selection_id, body, current_user.id)
    )


@router.get("/studies/{study_id}/lock-readiness", response_model=LockReadinessResponse)
async def lock_readiness(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> LockReadinessResponse:
    _permission_with_legacy(current_user, permission_service, "lock.read", "lock.manage", study_id)
    return await clinical_control_service.readiness(session, study_id)


@router.get(
    "/studies/{study_id}/clinical-control-requests",
    response_model=PaginatedResponse[ClinicalControlRequestResponse],
)
@router.get(
    "/studies/{study_id}/lock-history",
    response_model=PaginatedResponse[ClinicalControlRequestResponse],
)
async def list_control_requests(
    study_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
) -> Any:
    _permission_with_legacy(current_user, permission_service, "lock.read", "lock.manage", study_id)
    return await clinical_control_service.list_requests(
        session, study_id, pagination, status=status
    )


@router.post(
    "/studies/{study_id}/clinical-control-requests",
    response_model=ClinicalControlRequestResponse,
    status_code=201,
)
async def create_control_request(
    study_id: UUID,
    body: ClinicalControlRequestCreate,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> ClinicalControlRequestResponse:
    _permission_with_legacy(
        current_user, permission_service, "lock.request", "lock.manage", study_id
    )
    return ClinicalControlRequestResponse.model_validate(
        await clinical_control_service.create_request(session, study_id, body, current_user.id)
    )


async def _control_action(
    action: str,
    request_id: UUID,
    body: ClinicalControlDecision | None,
    session: AsyncSession,
    current_user: User,
    permission_service: PermissionService,
):
    request = await clinical_control_service._get(session, request_id)
    permission = "lock.execute" if action == "execute" else "lock.approve"
    if action == "cancel":
        permission = "lock.request"
    _permission_with_legacy(
        current_user, permission_service, permission, "lock.manage", request.study_id
    )
    if action == "approve":
        return await clinical_control_service.approve(session, request_id, current_user.id)
    if action == "reject":
        return await clinical_control_service.reject(
            session,
            request_id,
            current_user.id,
            (body.reason if body else None) or "Rejected",
        )
    if action == "cancel":
        return await clinical_control_service.cancel(session, request_id, current_user.id)
    return await clinical_control_service.execute(session, request_id, current_user.id)


async def _action_response(
    action: str,
    request_id: UUID,
    body: ClinicalControlDecision | None,
    session: AsyncSession,
    current_user: User,
    permission_service: PermissionService,
) -> ClinicalControlRequestResponse:
    return ClinicalControlRequestResponse.model_validate(
        await _control_action(action, request_id, body, session, current_user, permission_service)
    )


@router.post(
    "/clinical-control-requests/{request_id}/approve",
    response_model=ClinicalControlRequestResponse,
)
async def approve_control_request(
    request_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    body: ClinicalControlDecision | None = None,
) -> ClinicalControlRequestResponse:
    return await _action_response(
        "approve", request_id, body, session, current_user, permission_service
    )


@router.post(
    "/clinical-control-requests/{request_id}/reject",
    response_model=ClinicalControlRequestResponse,
)
async def reject_control_request(
    request_id: UUID,
    body: ClinicalControlDecision,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
) -> ClinicalControlRequestResponse:
    return await _action_response(
        "reject", request_id, body, session, current_user, permission_service
    )


@router.post(
    "/clinical-control-requests/{request_id}/cancel",
    response_model=ClinicalControlRequestResponse,
)
async def cancel_control_request(
    request_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    body: ClinicalControlDecision | None = None,
) -> ClinicalControlRequestResponse:
    return await _action_response(
        "cancel", request_id, body, session, current_user, permission_service
    )


@router.post(
    "/clinical-control-requests/{request_id}/execute",
    response_model=ClinicalControlRequestResponse,
)
async def execute_control_request(
    request_id: UUID,
    session: DbSession,
    current_user: CurrentUser,
    permission_service: PermissionSvc,
    body: ClinicalControlDecision | None = None,
) -> ClinicalControlRequestResponse:
    return await _action_response(
        "execute", request_id, body, session, current_user, permission_service
    )


__all__ = ["router"]
