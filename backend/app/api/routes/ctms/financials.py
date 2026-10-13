"""Authenticated CTMS contract-to-payment API."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_db, require_ctms_permission
from app.core.request_context import get_correlation_id
from app.models.ctms.financial import (
    ContractPaymentTerm,
    FinancialContract,
    FinancialContractVersion,
    FinancialInvoice,
    FinancialPayment,
    PayableItem,
    PaymentAllocation,
)
from app.models.shared.audit import AuditEvent
from app.models.shared.file_attachment import FileAttachment
from app.models.shared.identity import User
from app.schemas.ctms.financial import (
    ApprovalRequest,
    BudgetCreate,
    BudgetResponse,
    BudgetVersionCreate,
    BudgetVersionResponse,
    ContractTransitionRequest,
    ContractVersionCreate,
    ContractVersionResponse,
    FinancialAuditEntry,
    FinancialCalculationResponse,
    FinancialConfigurationOptions,
    FinancialContractCreate,
    FinancialContractResponse,
    FinancialEventCalculate,
    FinancialEventResponse,
    FinancialOverviewResponse,
    FinancialReportResponse,
    InvoiceCreate,
    InvoiceResponse,
    PayableItemResponse,
    PaymentCreate,
    PaymentResponse,
    PaymentReversalCreate,
    PaymentTermCreate,
    PaymentTermResponse,
)
from app.schemas.shared.base import PaginatedResponse
from app.schemas.shared.file_attachment import FileAttachmentResponse
from app.services.ctms.financial_service import financial_service
from app.services.shared.file_attachment_service import file_attachment_service

router = APIRouter(tags=["ctms-financials"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
ReadGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-data-read"))]
WriteGuard = Annotated[User, Depends(require_ctms_permission("ctms.operational-study-management"))]


async def _page(session: AsyncSession, model, conditions, pagination: PaginationParams, response):
    total = int(
        await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )
    rows = list(
        await session.scalars(
            select(model)
            .where(*conditions)
            .order_by(model.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
    )
    return PaginatedResponse(
        items=[response.model_validate(row) for row in rows],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/studies/{study_id}/financials/overview", response_model=FinancialOverviewResponse)
async def get_financial_overview(study_id: UUID, session: DbSession, current_user: ReadGuard):
    return FinancialOverviewResponse.model_validate(
        await financial_service.overview(session, study_id)
    )


@router.get(
    "/studies/{study_id}/financials/configuration-options",
    response_model=FinancialConfigurationOptions,
)
async def get_financial_configuration_options(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    as_of: date | None = None,
):
    return FinancialConfigurationOptions.model_validate(
        await financial_service.configuration_options(session, study_id, as_of=as_of)
    )


@router.get(
    "/studies/{study_id}/financials/contracts",
    response_model=PaginatedResponse[FinancialContractResponse],
)
async def list_financial_contracts(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
    contract_type: str | None = None,
    direction: str | None = None,
    organization_id: Annotated[UUID | None, Query()] = None,
):
    conditions = [FinancialContract.study_id == study_id]
    if status:
        conditions.append(FinancialContract.status == status)
    if contract_type:
        conditions.append(FinancialContract.contract_type == contract_type)
    if direction:
        conditions.append(FinancialContract.direction == direction)
    if organization_id:
        conditions.append(FinancialContract.organization_id == organization_id)
    return await _page(
        session, FinancialContract, conditions, pagination, FinancialContractResponse
    )


@router.post(
    "/studies/{study_id}/financials/contracts",
    response_model=FinancialContractResponse,
    status_code=201,
)
async def create_financial_contract(
    study_id: UUID,
    body: FinancialContractCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    return FinancialContractResponse.model_validate(
        await financial_service.create_contract(
            session,
            study_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


@router.post(
    "/studies/{study_id}/financials/contracts/{contract_id}/transition",
    response_model=FinancialContractResponse,
)
async def transition_financial_contract(
    study_id: UUID,
    contract_id: UUID,
    body: ContractTransitionRequest,
    session: DbSession,
    current_user: WriteGuard,
):
    return FinancialContractResponse.model_validate(
        await financial_service.transition_contract(
            session,
            study_id,
            contract_id,
            to_status=body.to_status.value,
            actor_id=current_user.id,
            reason=body.reason,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/financials/contracts/{contract_id}/documents",
    response_model=list[FileAttachmentResponse],
)
async def list_contract_documents(
    study_id: UUID, contract_id: UUID, session: DbSession, current_user: ReadGuard
):
    await financial_service._contract(session, study_id, contract_id)
    rows = await session.scalars(
        select(FileAttachment)
        .where(
            FileAttachment.module == "CTMS",
            FileAttachment.object_type == "operational",
            FileAttachment.object_id == contract_id,
            FileAttachment.study_id == study_id,
            FileAttachment.deleted_at.is_(None),
            FileAttachment.archived_at.is_(None),
        )
        .order_by(FileAttachment.uploaded_at.desc())
    )
    return [FileAttachmentResponse.model_validate(row) for row in rows]


@router.post(
    "/studies/{study_id}/financials/contracts/{contract_id}/documents",
    response_model=FileAttachmentResponse,
    status_code=201,
)
async def upload_contract_document(
    study_id: UUID,
    contract_id: UUID,
    session: DbSession,
    current_user: WriteGuard,
    file: Annotated[UploadFile, File(description="Executed agreement or supporting document")],
):
    contract = await financial_service._contract(session, study_id, contract_id)
    attachment = await file_attachment_service.upload_operational(
        session,
        parent_type="financial_contract",
        parent_id=contract.id,
        study_id=study_id,
        site_id=contract.site_id,
        file=file,
        actor_id=current_user.id,
        user=current_user,
        correlation_id=get_correlation_id(),
    )
    return FileAttachmentResponse.model_validate(attachment)


@router.get(
    "/studies/{study_id}/financials/contracts/{contract_id}/audit",
    response_model=list[FinancialAuditEntry],
)
async def contract_audit_trail(
    study_id: UUID, contract_id: UUID, session: DbSession, current_user: ReadGuard
):
    await financial_service._contract(session, study_id, contract_id)
    version_ids = list(
        await session.scalars(
            select(FinancialContractVersion.id).where(
                FinancialContractVersion.contract_id == contract_id
            )
        )
    )
    term_ids = (
        list(
            await session.scalars(
                select(ContractPaymentTerm.id).where(
                    ContractPaymentTerm.version_id.in_(version_ids)
                )
            )
        )
        if version_ids
        else []
    )
    payables = list(
        await session.execute(
            select(PayableItem.id, PayableItem.event_id).where(
                PayableItem.contract_id == contract_id
            )
        )
    )
    payable_ids = [row.id for row in payables]
    event_ids = [row.event_id for row in payables]
    invoice_ids = list(
        await session.scalars(
            select(FinancialInvoice.id).where(FinancialInvoice.contract_id == contract_id)
        )
    )
    payment_ids = (
        list(
            await session.scalars(
                select(PaymentAllocation.payment_id).where(
                    PaymentAllocation.invoice_id.in_(invoice_ids)
                )
            )
        )
        if invoice_ids
        else []
    )
    attachment_ids = list(
        await session.scalars(
            select(FileAttachment.id).where(
                FileAttachment.module == "CTMS",
                FileAttachment.object_type == "operational",
                FileAttachment.object_id == contract_id,
            )
        )
    )
    entity_ids = [
        contract_id,
        *version_ids,
        *term_ids,
        *payable_ids,
        *event_ids,
        *invoice_ids,
        *payment_ids,
        *attachment_ids,
    ]
    rows = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.study_id == study_id,
            AuditEvent.module == "CTMS",
            AuditEvent.entity_id.in_(entity_ids),
        )
        .order_by(AuditEvent.timestamp.desc())
    )
    return [FinancialAuditEntry.model_validate(row) for row in rows]


@router.get(
    "/studies/{study_id}/financials/contracts/{contract_id}/versions",
    response_model=list[ContractVersionResponse],
)
async def list_contract_versions(
    study_id: UUID, contract_id: UUID, session: DbSession, current_user: ReadGuard
):
    await financial_service._contract(session, study_id, contract_id)
    rows = await session.scalars(
        select(FinancialContractVersion)
        .where(FinancialContractVersion.contract_id == contract_id)
        .order_by(FinancialContractVersion.version_number.desc())
    )
    return [ContractVersionResponse.model_validate(row) for row in rows]


@router.post(
    "/studies/{study_id}/financials/contracts/{contract_id}/versions",
    response_model=ContractVersionResponse,
    status_code=201,
)
async def create_contract_version(
    study_id: UUID,
    contract_id: UUID,
    body: ContractVersionCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    return ContractVersionResponse.model_validate(
        await financial_service.add_version(
            session,
            study_id,
            contract_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/financials/versions/{version_id}/terms",
    response_model=list[PaymentTermResponse],
)
async def list_payment_terms(
    study_id: UUID, version_id: UUID, session: DbSession, current_user: ReadGuard
):
    version = await session.scalar(
        select(FinancialContractVersion)
        .join(FinancialContract, FinancialContract.id == FinancialContractVersion.contract_id)
        .where(
            FinancialContractVersion.id == version_id,
            FinancialContract.study_id == study_id,
        )
    )
    if version is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Contract version was not found")
    rows = await session.scalars(
        select(ContractPaymentTerm)
        .where(ContractPaymentTerm.version_id == version_id)
        .order_by(ContractPaymentTerm.code)
    )
    return [PaymentTermResponse.model_validate(row) for row in rows]


@router.post(
    "/studies/{study_id}/financials/versions/{version_id}/terms",
    response_model=PaymentTermResponse,
    status_code=201,
)
async def create_payment_term(
    study_id: UUID,
    version_id: UUID,
    body: PaymentTermCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    return PaymentTermResponse.model_validate(
        await financial_service.add_term(
            session,
            study_id,
            version_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


@router.post(
    "/studies/{study_id}/financials/versions/{version_id}/execute",
    response_model=ContractVersionResponse,
)
async def execute_contract_version(
    study_id: UUID,
    version_id: UUID,
    body: ApprovalRequest,
    session: DbSession,
    current_user: WriteGuard,
):
    return ContractVersionResponse.model_validate(
        await financial_service.execute_version(
            session,
            study_id,
            version_id,
            actor_id=current_user.id,
            reason=body.reason,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/financials/budgets",
    response_model=list[BudgetResponse],
)
async def list_financial_budgets(study_id: UUID, session: DbSession, current_user: ReadGuard):
    return [
        BudgetResponse.model_validate(item)
        for item in await financial_service.list_budget_payloads(session, study_id)
    ]


@router.post(
    "/studies/{study_id}/financials/budgets",
    response_model=BudgetResponse,
    status_code=201,
)
async def create_financial_budget(
    study_id: UUID, body: BudgetCreate, session: DbSession, current_user: WriteGuard
):
    budget = await financial_service.create_budget(
        session,
        study_id,
        body,
        actor_id=current_user.id,
        correlation_id=get_correlation_id(),
    )
    payloads = await financial_service.list_budget_payloads(session, study_id)
    return BudgetResponse.model_validate(next(item for item in payloads if item["id"] == budget.id))


@router.post(
    "/studies/{study_id}/financials/budgets/{budget_id}/versions",
    response_model=BudgetVersionResponse,
    status_code=201,
)
async def create_financial_budget_version(
    study_id: UUID,
    budget_id: UUID,
    body: BudgetVersionCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    version = await financial_service.add_budget_version(
        session,
        study_id,
        budget_id,
        body,
        actor_id=current_user.id,
        correlation_id=get_correlation_id(),
    )
    return BudgetVersionResponse.model_validate(
        await financial_service.budget_version_payload(session, version)
    )


@router.post(
    "/studies/{study_id}/financials/budget-versions/{version_id}/approve",
    response_model=BudgetVersionResponse,
)
async def approve_financial_budget_version(
    study_id: UUID,
    version_id: UUID,
    body: ApprovalRequest,
    session: DbSession,
    current_user: WriteGuard,
):
    version = await financial_service.approve_budget_version(
        session,
        study_id,
        version_id,
        actor_id=current_user.id,
        reason=body.reason,
        correlation_id=get_correlation_id(),
    )
    return BudgetVersionResponse.model_validate(
        await financial_service.budget_version_payload(session, version)
    )


@router.get(
    "/studies/{study_id}/financials/reports",
    response_model=FinancialReportResponse,
)
async def get_financial_report(study_id: UUID, session: DbSession, current_user: ReadGuard):
    return FinancialReportResponse.model_validate(
        await financial_service.financial_report(session, study_id)
    )


@router.post(
    "/studies/{study_id}/financials/events/calculate",
    response_model=FinancialCalculationResponse,
    status_code=201,
)
async def calculate_financial_event(
    study_id: UUID,
    body: FinancialEventCalculate,
    session: DbSession,
    current_user: WriteGuard,
):
    event, payables, replayed = await financial_service.calculate_event(
        session,
        study_id,
        body,
        actor_id=current_user.id,
        correlation_id=get_correlation_id(),
    )
    return FinancialCalculationResponse(
        event=FinancialEventResponse.model_validate(event),
        payable_items=[PayableItemResponse.model_validate(item) for item in payables],
        replayed=replayed,
    )


@router.get(
    "/studies/{study_id}/financials/payables",
    response_model=PaginatedResponse[PayableItemResponse],
)
async def list_payables(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
    status: str | None = None,
):
    conditions = [PayableItem.study_id == study_id]
    if status:
        conditions.append(PayableItem.status == status)
    return await _page(session, PayableItem, conditions, pagination, PayableItemResponse)


@router.post(
    "/studies/{study_id}/financials/payables/{payable_id}/approve",
    response_model=PayableItemResponse,
)
async def approve_payable(
    study_id: UUID,
    payable_id: UUID,
    body: ApprovalRequest,
    session: DbSession,
    current_user: WriteGuard,
):
    return PayableItemResponse.model_validate(
        await financial_service.approve_payable(
            session,
            study_id,
            payable_id,
            actor_id=current_user.id,
            reason=body.reason,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/financials/invoices",
    response_model=PaginatedResponse[InvoiceResponse],
)
async def list_invoices(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    return await _page(
        session,
        FinancialInvoice,
        [FinancialInvoice.study_id == study_id],
        pagination,
        InvoiceResponse,
    )


@router.post(
    "/studies/{study_id}/financials/invoices",
    response_model=InvoiceResponse,
    status_code=201,
)
async def create_invoice(
    study_id: UUID, body: InvoiceCreate, session: DbSession, current_user: WriteGuard
):
    return InvoiceResponse.model_validate(
        await financial_service.create_invoice(
            session,
            study_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


@router.get(
    "/studies/{study_id}/financials/payments",
    response_model=PaginatedResponse[PaymentResponse],
)
async def list_payments(
    study_id: UUID,
    session: DbSession,
    current_user: ReadGuard,
    pagination: Annotated[PaginationParams, Depends()],
):
    return await _page(
        session,
        FinancialPayment,
        [FinancialPayment.study_id == study_id],
        pagination,
        PaymentResponse,
    )


@router.post(
    "/studies/{study_id}/financials/payments",
    response_model=PaymentResponse,
    status_code=201,
)
async def reconcile_payment(
    study_id: UUID, body: PaymentCreate, session: DbSession, current_user: WriteGuard
):
    return PaymentResponse.model_validate(
        await financial_service.reconcile_payment(
            session,
            study_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


@router.post(
    "/studies/{study_id}/financials/payments/{payment_id}/reverse",
    response_model=PaymentResponse,
)
async def reverse_payment(
    study_id: UUID,
    payment_id: UUID,
    body: PaymentReversalCreate,
    session: DbSession,
    current_user: WriteGuard,
):
    return PaymentResponse.model_validate(
        await financial_service.reverse_payment(
            session,
            study_id,
            payment_id,
            body,
            actor_id=current_user.id,
            correlation_id=get_correlation_id(),
        )
    )


__all__ = ["router"]
