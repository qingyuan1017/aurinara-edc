"""Contract-to-payment orchestration for CTMS financial operations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.request_context import get_correlation_id
from app.models.ctms.entity_management import (
    ManagedEntity,
    ManagedEntityType,
    StudyEntityAssignment,
)
from app.models.ctms.financial import (
    ContractPaymentTerm,
    FinancialBudget,
    FinancialBudgetLine,
    FinancialBudgetVersion,
    FinancialContract,
    FinancialContractVersion,
    FinancialEvent,
    FinancialInvoice,
    FinancialInvoiceLine,
    FinancialPayment,
    PayableItem,
    PaymentAllocation,
)
from app.models.ctms.operational_study import StudyOperationalMilestone
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.form_data import FormInstance, FormInstanceStatus
from app.models.edc.site import Site
from app.models.edc.subject import Subject
from app.models.edc.visit import VisitInstance, VisitInstanceStatus
from app.schemas.ctms.financial import (
    BudgetCreate,
    BudgetLineCreate,
    BudgetVersionCreate,
    ContractVersionCreate,
    FinancialContractCreate,
    FinancialEventCalculate,
    InvoiceCreate,
    PaymentCreate,
    PaymentReversalCreate,
    PaymentTermCreate,
)
from app.services.ctms.ctms_atomicity_service import ctms_atomicity_service

CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _correlation_uuid(value: UUID | str | None) -> UUID:
    if value is None:
        return uuid4()
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return uuid5(NAMESPACE_URL, str(value))


class FinancialService:
    async def _contract(
        self, session: AsyncSession, study_id: UUID, contract_id: UUID
    ) -> FinancialContract:
        contract = await session.scalar(
            select(FinancialContract).where(
                FinancialContract.id == contract_id,
                FinancialContract.study_id == study_id,
            )
        )
        if contract is None:
            raise NotFoundError("Financial contract was not found")
        return contract

    async def _validate_site(self, session: AsyncSession, study_id: UUID, site_id: UUID) -> None:
        exists = await session.scalar(
            select(Site.id).where(Site.id == site_id, Site.study_id == study_id)
        )
        if exists is None:
            raise ValidationError("site_id is not part of the requested study")

    async def _validate_organization(
        self, session: AsyncSession, study_id: UUID, organization_id: UUID
    ) -> ManagedEntity:
        organization = await session.scalar(
            select(ManagedEntity)
            .join(StudyEntityAssignment, StudyEntityAssignment.entity_id == ManagedEntity.id)
            .where(
                ManagedEntity.id == organization_id,
                ManagedEntity.entity_type == ManagedEntityType.PARTICIPATING_ORGANIZATION.value,
                ManagedEntity.active.is_(True),
                ManagedEntity.deleted_at.is_(None),
                StudyEntityAssignment.study_id == study_id,
                StudyEntityAssignment.deleted_at.is_(None),
            )
        )
        if organization is None:
            raise ValidationError(
                "organization_id must reference an active participating organization assigned to the study"
            )
        return organization

    async def _validate_definition(
        self,
        session: AsyncSession,
        study_id: UUID,
        definition_id: UUID,
        definition_model,
        label: str,
    ) -> None:
        exists = await session.scalar(
            select(definition_model.id)
            .join(StudyVersion, StudyVersion.id == definition_model.study_version_id)
            .where(
                definition_model.id == definition_id,
                StudyVersion.study_id == study_id,
                StudyVersion.status == StudyVersionStatus.published,
            )
        )
        if exists is None:
            raise ValidationError(
                f"{label} must reference a published EDC definition for the requested study"
            )

    async def configuration_options(
        self, session: AsyncSession, study_id: UUID, *, as_of: date | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        visits = (
            await session.execute(
                select(VisitDefinition, StudyVersion.version_number)
                .join(StudyVersion, StudyVersion.id == VisitDefinition.study_version_id)
                .where(
                    StudyVersion.study_id == study_id,
                    StudyVersion.status == StudyVersionStatus.published,
                )
                .order_by(StudyVersion.version_number.desc(), VisitDefinition.visit_number)
            )
        ).all()
        forms = (
            await session.execute(
                select(FormDefinition, StudyVersion.version_number)
                .join(StudyVersion, StudyVersion.id == FormDefinition.study_version_id)
                .where(
                    StudyVersion.study_id == study_id,
                    StudyVersion.status == StudyVersionStatus.published,
                )
                .order_by(StudyVersion.version_number.desc(), FormDefinition.form_code)
            )
        ).all()
        rule_conditions = [
            FinancialContract.study_id == study_id,
            FinancialContract.status.in_(("executed", "active")),
            FinancialContractVersion.status.in_(("executed", "superseded")),
            ContractPaymentTerm.active.is_(True),
        ]
        if as_of is not None:
            rule_conditions.extend(
                [
                    FinancialContractVersion.effective_from <= as_of,
                    (FinancialContractVersion.effective_to.is_(None))
                    | (FinancialContractVersion.effective_to >= as_of),
                ]
            )
        rule_rows = (
            await session.execute(
                select(
                    ContractPaymentTerm.trigger_code,
                    ContractPaymentTerm.description,
                    ContractPaymentTerm.payment_method,
                )
                .join(
                    FinancialContractVersion,
                    FinancialContractVersion.id == ContractPaymentTerm.version_id,
                )
                .join(
                    FinancialContract,
                    FinancialContract.id == FinancialContractVersion.contract_id,
                )
                .where(*rule_conditions)
                .order_by(ContractPaymentTerm.trigger_code, ContractPaymentTerm.code)
            )
        ).all()
        payment_rules: dict[str, dict[str, Any]] = {}
        for trigger_code, description, payment_method in rule_rows:
            rule = payment_rules.setdefault(
                trigger_code,
                {
                    "code": trigger_code,
                    "descriptions": [],
                    "methods": [],
                    "charge_item_count": 0,
                },
            )
            rule["charge_item_count"] += 1
            if description not in rule["descriptions"]:
                rule["descriptions"].append(description)
            if payment_method not in rule["methods"]:
                rule["methods"].append(payment_method)
        return {
            "visits": [
                {
                    "id": visit.id,
                    "code": str(visit.visit_number),
                    "label": visit.name,
                    "version": version_number,
                }
                for visit, version_number in visits
            ],
            "forms": [
                {
                    "id": form.id,
                    "code": form.form_code,
                    "label": form.name,
                    "version": version_number,
                }
                for form, version_number in forms
            ],
            "payment_rules": [
                {
                    "code": rule["code"],
                    "label": " · ".join(rule["descriptions"][:2]),
                    "charge_item_count": rule["charge_item_count"],
                    "methods": rule["methods"],
                }
                for rule in payment_rules.values()
            ],
        }

    async def create_contract(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: FinancialContractCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialContract:
        if payload.site_id:
            await self._validate_site(session, study_id, payload.site_id)
        if payload.organization_id:
            await self._validate_organization(session, study_id, payload.organization_id)
        correlation = _correlation_uuid(correlation_id or get_correlation_id())
        contract = FinancialContract(
            study_id=study_id,
            **payload.model_dump(),
            status="draft",
            created_by=actor_id,
            updated_by=actor_id,
            correlation_id=correlation,
        )
        session.add(contract)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_contract",
            entity_id=contract.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=correlation,
            action="create",
            changed_fields=(
                "contract_number",
                "contract_type",
                "direction",
                "party_name",
                "organization_id",
                "currency",
            ),
            status=contract.status,
            payload={"contract_id": contract.id, "direction": contract.direction},
        )
        return contract

    async def transition_contract(
        self,
        session: AsyncSession,
        study_id: UUID,
        contract_id: UUID,
        *,
        to_status: str,
        actor_id: UUID,
        reason: str,
        correlation_id: UUID | str | None = None,
    ) -> FinancialContract:
        contract = await self._contract(session, study_id, contract_id)
        allowed = {
            "draft": {"internal_review"},
            "internal_review": {"negotiation", "approved"},
            "negotiation": {"internal_review", "approved"},
            "approved": {"executed"},
            "executed": {"active", "closed"},
            "active": {"closed"},
            "closed": set(),
        }
        if to_status not in allowed.get(contract.status, set()):
            raise ConflictError(f"Contract cannot transition from {contract.status} to {to_status}")
        previous = contract.status
        if to_status == "executed":
            executed_version = await session.scalar(
                select(FinancialContractVersion.id).where(
                    FinancialContractVersion.contract_id == contract.id,
                    FinancialContractVersion.status == "executed",
                )
            )
            if executed_version is None:
                draft_version = await session.scalar(
                    select(FinancialContractVersion)
                    .where(
                        FinancialContractVersion.contract_id == contract.id,
                        FinancialContractVersion.status == "draft",
                    )
                    .order_by(FinancialContractVersion.version_number.desc())
                )
                if draft_version is None:
                    raise ConflictError("Create a contract version before executing the contract")
                await self.execute_version(
                    session,
                    study_id,
                    draft_version.id,
                    actor_id=actor_id,
                    reason=reason,
                    correlation_id=correlation_id,
                )
        contract.status = to_status
        contract.updated_by = actor_id
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_contract",
            entity_id=contract.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="transition",
            changed_fields=("status",),
            previous_status=previous,
            status=to_status,
            reason=reason,
            payload={"contract_id": contract.id},
        )
        return contract

    async def create_budget(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: BudgetCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialBudget:
        budget = FinancialBudget(
            study_id=study_id,
            name=payload.name.strip(),
            scope=payload.scope,
            currency=payload.currency,
            status="draft",
            created_by=actor_id,
        )
        session.add(budget)
        await session.flush()
        await self._add_budget_version(
            session,
            study_id,
            budget,
            effective_from=payload.effective_from,
            reason=payload.reason,
            lines=payload.lines,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_budget",
            entity_id=budget.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="create",
            changed_fields=("name", "scope", "currency", "status"),
            status=budget.status,
            payload={"budget_id": budget.id},
        )
        return budget

    async def add_budget_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        budget_id: UUID,
        payload: BudgetVersionCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialBudgetVersion:
        budget = await session.scalar(
            select(FinancialBudget).where(
                FinancialBudget.id == budget_id, FinancialBudget.study_id == study_id
            )
        )
        if budget is None:
            raise NotFoundError("Financial budget was not found")
        existing_draft = await session.scalar(
            select(FinancialBudgetVersion.id).where(
                FinancialBudgetVersion.budget_id == budget.id,
                FinancialBudgetVersion.status == "draft",
            )
        )
        if existing_draft is not None:
            raise ConflictError("Approve or replace the existing draft budget version first")
        return await self._add_budget_version(
            session,
            study_id,
            budget,
            effective_from=payload.effective_from,
            reason=payload.reason,
            lines=payload.lines,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    async def _add_budget_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        budget: FinancialBudget,
        *,
        effective_from: date,
        reason: str | None,
        lines: list[BudgetLineCreate],
        actor_id: UUID,
        correlation_id: UUID | str | None,
    ) -> FinancialBudgetVersion:
        latest = int(
            await session.scalar(
                select(func.max(FinancialBudgetVersion.version_number)).where(
                    FinancialBudgetVersion.budget_id == budget.id
                )
            )
            or 0
        )
        version = FinancialBudgetVersion(
            budget_id=budget.id,
            version_number=latest + 1,
            status="draft",
            effective_from=effective_from,
            reason=reason,
            created_by=actor_id,
        )
        session.add(version)
        await session.flush()
        for line in lines:
            planned = _money(line.quantity * line.unit_cost)
            session.add(
                FinancialBudgetLine(
                    version_id=version.id,
                    category=line.category.strip(),
                    description=line.description.strip(),
                    quantity=line.quantity,
                    unit_cost=line.unit_cost,
                    planned_amount=planned,
                )
            )
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_budget_version",
            entity_id=version.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="create_version",
            changed_fields=("effective_from", "reason", "lines"),
            status=version.status,
            reason=reason,
            payload={"budget_id": budget.id, "version_number": version.version_number},
        )
        return version

    async def approve_budget_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        version_id: UUID,
        *,
        actor_id: UUID,
        reason: str,
        correlation_id: UUID | str | None = None,
    ) -> FinancialBudgetVersion:
        row = await session.execute(
            select(FinancialBudgetVersion, FinancialBudget)
            .join(FinancialBudget, FinancialBudget.id == FinancialBudgetVersion.budget_id)
            .where(
                FinancialBudgetVersion.id == version_id,
                FinancialBudget.study_id == study_id,
            )
        )
        result = row.first()
        if result is None:
            raise NotFoundError("Financial budget version was not found")
        version, budget = result
        if version.status != "draft":
            raise ConflictError("Only a draft budget version can be approved")
        prior = list(
            await session.scalars(
                select(FinancialBudgetVersion).where(
                    FinancialBudgetVersion.budget_id == budget.id,
                    FinancialBudgetVersion.status == "approved",
                )
            )
        )
        for item in prior:
            item.status = "superseded"
        if prior:
            await session.flush()
        version.status = "approved"
        version.approved_at = datetime.now(UTC)
        version.approved_by = actor_id
        budget.status = "approved"
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_budget_version",
            entity_id=version.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="approve",
            changed_fields=("status", "approved_at", "approved_by"),
            previous_status="draft",
            status="approved",
            reason=reason,
            payload={"budget_id": budget.id, "version_number": version.version_number},
        )
        return version

    async def add_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        contract_id: UUID,
        payload: ContractVersionCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialContractVersion:
        contract = await self._contract(session, study_id, contract_id)
        latest = int(
            await session.scalar(
                select(func.max(FinancialContractVersion.version_number)).where(
                    FinancialContractVersion.contract_id == contract_id
                )
            )
            or 0
        )
        if latest and not payload.amendment_reason:
            raise ValidationError("amendment_reason is required after the first contract version")
        version = FinancialContractVersion(
            contract_id=contract_id,
            version_number=latest + 1,
            **payload.model_dump(),
            status="draft",
            terms_snapshot_json={},
            created_by=actor_id,
        )
        session.add(version)
        contract.updated_by = actor_id
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_contract_version",
            entity_id=version.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="create_version",
            changed_fields=("effective_from", "total_value", "holdback_percent"),
            status=version.status,
            reason=payload.amendment_reason,
            payload={"contract_id": contract_id, "version_number": version.version_number},
        )
        return version

    async def add_term(
        self,
        session: AsyncSession,
        study_id: UUID,
        version_id: UUID,
        payload: PaymentTermCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> ContractPaymentTerm:
        row = await session.execute(
            select(FinancialContractVersion, FinancialContract)
            .join(FinancialContract, FinancialContract.id == FinancialContractVersion.contract_id)
            .where(
                FinancialContractVersion.id == version_id,
                FinancialContract.study_id == study_id,
            )
        )
        result = row.first()
        if result is None:
            raise NotFoundError("Contract version was not found")
        version, contract = result
        if version.status != "draft":
            raise ConflictError(
                "Executed or approved contract terms are immutable; create an amendment"
            )
        if payload.visit_definition_id:
            await self._validate_definition(
                session,
                study_id,
                payload.visit_definition_id,
                VisitDefinition,
                "visit_definition_id",
            )
        if payload.form_definition_id:
            await self._validate_definition(
                session,
                study_id,
                payload.form_definition_id,
                FormDefinition,
                "form_definition_id",
            )
        term = ContractPaymentTerm(
            version_id=version_id,
            **payload.model_dump(),
            created_by=actor_id,
        )
        session.add(term)
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_contract_payment_term",
            entity_id=term.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="create",
            changed_fields=(
                "payment_method",
                "trigger_code",
                "unit_rate",
                "cost_category",
                "billing_unit",
                "visit_definition_id",
                "form_definition_id",
                "holdback_percent",
            ),
            payload={"contract_id": contract.id, "version_id": version.id, "term_code": term.code},
        )
        return term

    async def execute_version(
        self,
        session: AsyncSession,
        study_id: UUID,
        version_id: UUID,
        *,
        actor_id: UUID,
        reason: str,
        correlation_id: UUID | str | None = None,
    ) -> FinancialContractVersion:
        row = await session.execute(
            select(FinancialContractVersion, FinancialContract)
            .join(FinancialContract, FinancialContract.id == FinancialContractVersion.contract_id)
            .where(
                FinancialContractVersion.id == version_id,
                FinancialContract.study_id == study_id,
            )
        )
        result = row.first()
        if result is None:
            raise NotFoundError("Contract version was not found")
        version, contract = result
        if version.status != "draft":
            raise ConflictError("Only a draft contract version can be executed")
        terms = list(
            await session.scalars(
                select(ContractPaymentTerm)
                .where(
                    ContractPaymentTerm.version_id == version.id,
                    ContractPaymentTerm.active.is_(True),
                )
                .order_by(ContractPaymentTerm.code)
            )
        )
        if not terms:
            raise ValidationError("At least one active payment term is required before execution")
        existing = list(
            await session.scalars(
                select(FinancialContractVersion).where(
                    FinancialContractVersion.contract_id == contract.id,
                    FinancialContractVersion.status == "executed",
                )
            )
        )
        if existing and version.effective_from <= max(item.effective_from for item in existing):
            raise ValidationError(
                "An amendment must become effective after the current executed version"
            )
        for prior in existing:
            prior.status = "superseded"
            if prior.effective_to is None or prior.effective_to >= version.effective_from:
                prior.effective_to = version.effective_from - timedelta(days=1)
        version.status = "executed"
        version.executed_at = datetime.now(UTC)
        version.executed_by = actor_id
        version.terms_snapshot_json = {
            "contract_id": str(contract.id),
            "version_number": version.version_number,
            "currency": contract.currency,
            "holdback_percent": str(version.holdback_percent),
            "terms": [
                {
                    "id": str(term.id),
                    "code": term.code,
                    "payment_method": term.payment_method,
                    "trigger_code": term.trigger_code,
                    "unit_rate": str(term.unit_rate),
                    "cost_category": term.cost_category,
                    "billing_unit": term.billing_unit,
                    "visit_definition_id": (
                        str(term.visit_definition_id) if term.visit_definition_id else None
                    ),
                    "form_definition_id": (
                        str(term.form_definition_id) if term.form_definition_id else None
                    ),
                    "lab_code": term.lab_code,
                    "invoice_category": term.invoice_category,
                    "dimensions": term.dimensions_json,
                    "holdback_percent": (
                        str(term.holdback_percent) if term.holdback_percent is not None else None
                    ),
                }
                for term in terms
            ],
        }
        contract.status = "executed"
        contract.updated_by = actor_id
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_contract_version",
            entity_id=version.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="execute",
            changed_fields=("status", "terms_snapshot", "executed_at"),
            previous_status="draft",
            status="executed",
            reason=reason,
            payload={"contract_id": contract.id, "version_number": version.version_number},
        )
        return version

    async def calculate_event(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: FinancialEventCalculate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> tuple[FinancialEvent, list[PayableItem], bool]:
        replay = await session.scalar(
            select(FinancialEvent).where(
                FinancialEvent.study_id == study_id,
                FinancialEvent.idempotency_key == payload.idempotency_key,
            )
        )
        if replay is not None:
            payables = list(
                await session.scalars(select(PayableItem).where(PayableItem.event_id == replay.id))
            )
            return replay, payables, True
        if payload.site_id:
            await self._validate_site(session, study_id, payload.site_id)
        if payload.subject_id:
            subject = await session.scalar(
                select(Subject).where(
                    Subject.id == payload.subject_id,
                    Subject.study_id == study_id,
                )
            )
            if subject is None:
                raise ValidationError("subject_id is not part of the requested study")
            if payload.site_id and subject.site_id != payload.site_id:
                raise ValidationError("subject_id is not part of the requested site")
        visit = None
        form_instance = None
        if payload.visit_instance_id:
            visit = await session.scalar(
                select(VisitInstance)
                .join(Subject, Subject.id == VisitInstance.subject_id)
                .where(
                    VisitInstance.id == payload.visit_instance_id,
                    Subject.study_id == study_id,
                )
            )
            if visit is None or (payload.subject_id and visit.subject_id != payload.subject_id):
                raise ValidationError(
                    "visit_instance_id is not valid for the requested study/subject"
                )
            if (
                payload.source_type == "edc_visit_instance"
                and visit.status != VisitInstanceStatus.completed
            ):
                raise ValidationError(
                    "An EDC visit financial event must reference a completed visit"
                )
        elif payload.source_type == "edc_visit_instance":
            raise ValidationError("visit_instance_id is required for an EDC visit financial event")
        if payload.source_type == "edc_form_instance":
            if payload.source_id is None:
                raise ValidationError("source_id is required for an EDC form financial event")
            form_instance = await session.scalar(
                select(FormInstance)
                .join(Subject, Subject.id == FormInstance.subject_id)
                .where(
                    FormInstance.id == payload.source_id,
                    Subject.study_id == study_id,
                )
            )
            eligible_form_statuses = {
                FormInstanceStatus.submitted,
                FormInstanceStatus.reviewed,
                FormInstanceStatus.frozen,
                FormInstanceStatus.locked,
                FormInstanceStatus.signed,
            }
            if form_instance is None or form_instance.status not in eligible_form_statuses:
                raise ValidationError(
                    "An EDC form financial event must reference a submitted or reviewed form"
                )
            if payload.subject_id and form_instance.subject_id != payload.subject_id:
                raise ValidationError("The EDC form does not belong to the requested subject")
            if (
                payload.visit_instance_id
                and form_instance.visit_instance_id != payload.visit_instance_id
            ):
                raise ValidationError("The EDC form does not belong to the requested visit")
        if payload.source_type == "ctms_project_milestone":
            if payload.source_id is None:
                raise ValidationError(
                    "source_id is required for a CTMS project milestone financial event"
                )
            milestone = await session.scalar(
                select(StudyOperationalMilestone).where(
                    StudyOperationalMilestone.id == payload.source_id,
                    StudyOperationalMilestone.study_id == study_id,
                    StudyOperationalMilestone.status == "Completed",
                )
            )
            if milestone is None:
                raise ValidationError(
                    "A CTMS milestone financial event must reference a completed study milestone"
                )

        event = FinancialEvent(
            study_id=study_id,
            **payload.model_dump(exclude={"evidence"}),
            evidence_json=payload.evidence,
            created_by=actor_id,
        )
        session.add(event)
        await session.flush()
        rows = (
            await session.execute(
                select(ContractPaymentTerm, FinancialContractVersion, FinancialContract)
                .join(
                    FinancialContractVersion,
                    FinancialContractVersion.id == ContractPaymentTerm.version_id,
                )
                .join(
                    FinancialContract, FinancialContract.id == FinancialContractVersion.contract_id
                )
                .where(
                    FinancialContract.study_id == study_id,
                    FinancialContractVersion.status.in_(("executed", "superseded")),
                    FinancialContractVersion.effective_from <= payload.event_date,
                    (FinancialContractVersion.effective_to.is_(None))
                    | (FinancialContractVersion.effective_to >= payload.event_date),
                    ContractPaymentTerm.active.is_(True),
                    ContractPaymentTerm.trigger_code == payload.trigger_code,
                    (FinancialContract.site_id.is_(None))
                    | (FinancialContract.site_id == payload.site_id),
                )
            )
        ).all()
        event_dimensions = payload.evidence.get("dimensions", {})
        if not isinstance(event_dimensions, dict):
            event_dimensions = {}
        event_dimensions = {**payload.evidence, **event_dimensions}
        matched_rows = []
        for term, version, contract in rows:
            if term.visit_definition_id and (
                visit is None or visit.visit_definition_id != term.visit_definition_id
            ):
                continue
            if term.form_definition_id and (
                form_instance is None or form_instance.form_definition_id != term.form_definition_id
            ):
                continue
            if (
                term.lab_code
                and str(event_dimensions.get("lab_code", "")).upper() != term.lab_code.upper()
            ):
                continue
            if (
                term.invoice_category
                and str(event_dimensions.get("invoice_category", "")).upper()
                != term.invoice_category.upper()
            ):
                continue
            if any(
                str(event_dimensions.get(key, "")) != str(value)
                for key, value in term.dimensions_json.items()
            ):
                continue
            matched_rows.append((term, version, contract))
        if not matched_rows:
            raise ValidationError("No executed contract term matches this verified financial event")

        payables: list[PayableItem] = []
        correlation = _correlation_uuid(correlation_id or get_correlation_id())
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_event",
            entity_id=event.id,
            study_id=study_id,
            site_id=payload.site_id,
            actor_id=actor_id,
            correlation_id=correlation,
            action="verify",
            changed_fields=("source_type", "trigger_code", "event_date", "quantity"),
            status=event.verification_status,
            idempotency_key=payload.idempotency_key,
            payload={"event_id": event.id, "source_id": event.source_id},
        )
        for term, version, contract in matched_rows:
            base_quantity = (
                Decimal("1")
                if term.payment_method in {"fixed", "milestone_based", "invoice_based"}
                else payload.quantity
            )
            quantity = min(base_quantity, term.quantity_cap) if term.quantity_cap else base_quantity
            gross = _money(quantity * term.unit_rate)
            prior_gross = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PayableItem.gross_amount), 0)).where(
                            PayableItem.contract_term_id == term.id
                        )
                    )
                )
            )
            if term.amount_cap is not None:
                gross = max(Decimal("0"), min(gross, term.amount_cap - prior_gross))
            contract_gross = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PayableItem.gross_amount), 0)).where(
                            PayableItem.contract_id == contract.id
                        )
                    )
                )
            )
            gross = max(Decimal("0"), min(gross, version.total_value - contract_gross))
            if gross == 0:
                continue
            holdback_percent = (
                term.holdback_percent
                if term.holdback_percent is not None
                else version.holdback_percent
            )
            holdback = _money(gross * holdback_percent / Decimal("100"))
            payable = PayableItem(
                study_id=study_id,
                contract_id=contract.id,
                contract_version_id=version.id,
                contract_term_id=term.id,
                event_id=event.id,
                gross_amount=gross,
                holdback_amount=holdback,
                net_amount=gross - holdback,
                currency=contract.currency,
                status="calculated",
                calculation_snapshot_json={
                    "formula": "min(quantity x unit_rate, term cap, contract cap) - holdback",
                    "quantity": str(quantity),
                    "unit_rate": str(term.unit_rate),
                    "billing_unit": term.billing_unit,
                    "cost_category": term.cost_category,
                    "gross_amount": str(gross),
                    "holdback_percent": str(holdback_percent),
                    "holdback_amount": str(holdback),
                    "net_amount": str(gross - holdback),
                    "contract_version": version.version_number,
                    "term_code": term.code,
                    "payment_method": term.payment_method,
                    "trigger_code": payload.trigger_code,
                    "source_type": payload.source_type,
                    "source_id": str(payload.source_id) if payload.source_id else None,
                    "organization_id": (
                        str(contract.organization_id) if contract.organization_id else None
                    ),
                    "visit_definition_id": (
                        str(term.visit_definition_id) if term.visit_definition_id else None
                    ),
                    "form_definition_id": (
                        str(term.form_definition_id) if term.form_definition_id else None
                    ),
                    "lab_code": term.lab_code,
                    "invoice_category": term.invoice_category,
                    "dimensions": term.dimensions_json,
                },
            )
            session.add(payable)
            await session.flush()
            payables.append(payable)
            await ctms_atomicity_service.record_mutation(
                session,
                entity_type="ctms_payable_item",
                entity_id=payable.id,
                study_id=study_id,
                site_id=payload.site_id,
                actor_id=actor_id,
                correlation_id=correlation,
                action="calculate",
                changed_fields=("gross_amount", "holdback_amount", "net_amount", "status"),
                status=payable.status,
                idempotency_key=f"payable:{payload.idempotency_key}:{term.id}",
                payload={"event_id": event.id, "contract_id": contract.id, "term_id": term.id},
            )
        if not payables:
            raise ValidationError("The matching contract terms have reached their configured caps")
        return event, payables, False

    async def approve_payable(
        self,
        session: AsyncSession,
        study_id: UUID,
        payable_id: UUID,
        *,
        actor_id: UUID,
        reason: str,
        correlation_id: UUID | str | None = None,
    ) -> PayableItem:
        payable = await session.scalar(
            select(PayableItem).where(
                PayableItem.id == payable_id, PayableItem.study_id == study_id
            )
        )
        if payable is None:
            raise NotFoundError("Payable item was not found")
        if payable.status != "calculated":
            raise ConflictError("Only a calculated payable item can be approved")
        from app.core.ctms import utc_now

        payable.status = "approved"
        payable.approved_at = utc_now()
        payable.approved_by = actor_id
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_payable_item",
            entity_id=payable.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="approve",
            changed_fields=("status", "approved_at", "approved_by"),
            previous_status="calculated",
            status="approved",
            reason=reason,
            payload={"contract_id": payable.contract_id, "event_id": payable.event_id},
        )
        return payable

    async def create_invoice(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: InvoiceCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialInvoice:
        contract = await self._contract(session, study_id, payload.contract_id)
        if payload.currency != contract.currency or payload.direction != contract.direction:
            raise ValidationError("Invoice currency and direction must match the contract")
        if payload.party_name != contract.party_name or (
            contract.party_id is not None and payload.party_id != contract.party_id
        ):
            raise ValidationError("Invoice party must match the contract party")
        payable_ids = [line.payable_item_id for line in payload.lines]
        if len(set(payable_ids)) != len(payable_ids):
            raise ValidationError("An invoice cannot contain duplicate payable items")
        payables = {
            item.id: item
            for item in await session.scalars(
                select(PayableItem).where(
                    PayableItem.id.in_(payable_ids),
                    PayableItem.study_id == study_id,
                    PayableItem.contract_id == contract.id,
                )
            )
        }
        if len(payables) != len(payable_ids):
            raise ValidationError("Every invoice line must reference a payable from this contract")
        for line in payload.lines:
            payable = payables[line.payable_item_id]
            if payable.status not in {"approved", "partially_invoiced"}:
                raise ConflictError("Only approved payable items can be matched to an invoice")
            matched = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(FinancialInvoiceLine.amount), 0)).where(
                            FinancialInvoiceLine.payable_item_id == payable.id
                        )
                    )
                )
            )
            if matched + line.amount > payable.net_amount:
                raise ValidationError("Invoice line exceeds the payable item's unmatched amount")
        invoice = FinancialInvoice(
            study_id=study_id,
            **payload.model_dump(exclude={"lines"}),
            status="matched",
            created_by=actor_id,
        )
        session.add(invoice)
        await session.flush()
        for line in payload.lines:
            session.add(
                FinancialInvoiceLine(
                    invoice_id=invoice.id,
                    payable_item_id=line.payable_item_id,
                    amount=line.amount,
                )
            )
            payable = payables[line.payable_item_id]
            matched = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(FinancialInvoiceLine.amount), 0)).where(
                            FinancialInvoiceLine.payable_item_id == payable.id
                        )
                    )
                )
            )
            payable.status = "invoiced" if matched == payable.net_amount else "partially_invoiced"
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_invoice",
            entity_id=invoice.id,
            study_id=study_id,
            site_id=contract.site_id,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="match",
            changed_fields=("amount", "status", "invoice_lines"),
            status=invoice.status,
            payload={"contract_id": contract.id, "invoice_number": invoice.invoice_number},
        )
        return invoice

    async def reconcile_payment(
        self,
        session: AsyncSession,
        study_id: UUID,
        payload: PaymentCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialPayment:
        invoice_ids = [item.invoice_id for item in payload.allocations]
        if len(set(invoice_ids)) != len(invoice_ids):
            raise ValidationError("A payment cannot allocate to the same invoice twice")
        invoices = {
            item.id: item
            for item in await session.scalars(
                select(FinancialInvoice).where(
                    FinancialInvoice.id.in_(invoice_ids),
                    FinancialInvoice.study_id == study_id,
                )
            )
        }
        if len(invoices) != len(invoice_ids):
            raise ValidationError("Every allocation must reference an invoice in this study")
        for allocation in payload.allocations:
            invoice = invoices[allocation.invoice_id]
            if invoice.currency != payload.currency or invoice.direction != payload.direction:
                raise ValidationError("Payment currency and direction must match every invoice")
            if invoice.party_name != payload.party_name or (
                invoice.party_id is not None and invoice.party_id != payload.party_id
            ):
                raise ValidationError("Payment party must match every allocated invoice")
            allocated = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                        .join(
                            FinancialPayment,
                            FinancialPayment.id == PaymentAllocation.payment_id,
                        )
                        .where(
                            PaymentAllocation.invoice_id == invoice.id,
                            FinancialPayment.status == "settled",
                        )
                    )
                )
            )
            if allocated + allocation.allocated_amount > invoice.amount:
                raise ValidationError("Allocation exceeds the invoice's outstanding amount")
        payment = FinancialPayment(
            study_id=study_id,
            **payload.model_dump(exclude={"allocations"}),
            status="settled",
            created_by=actor_id,
        )
        session.add(payment)
        await session.flush()
        for allocation in payload.allocations:
            session.add(
                PaymentAllocation(
                    payment_id=payment.id,
                    invoice_id=allocation.invoice_id,
                    allocated_amount=allocation.allocated_amount,
                )
            )
            invoice = invoices[allocation.invoice_id]
            allocated = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                        .join(
                            FinancialPayment,
                            FinancialPayment.id == PaymentAllocation.payment_id,
                        )
                        .where(
                            PaymentAllocation.invoice_id == invoice.id,
                            FinancialPayment.status == "settled",
                        )
                    )
                )
            )
            invoice.status = "paid" if allocated == invoice.amount else "partially_paid"
        await session.flush()
        for invoice in invoices.values():
            if invoice.status != "paid":
                continue
            lines = list(
                await session.scalars(
                    select(FinancialInvoiceLine).where(
                        FinancialInvoiceLine.invoice_id == invoice.id
                    )
                )
            )
            for line in lines:
                payable = await session.get(PayableItem, line.payable_item_id)
                if payable is None:
                    continue
                matched = Decimal(
                    str(
                        await session.scalar(
                            select(func.coalesce(func.sum(FinancialInvoiceLine.amount), 0)).where(
                                FinancialInvoiceLine.payable_item_id == payable.id
                            )
                        )
                    )
                )
                unpaid_invoice_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(FinancialInvoiceLine)
                        .join(
                            FinancialInvoice,
                            FinancialInvoice.id == FinancialInvoiceLine.invoice_id,
                        )
                        .where(
                            FinancialInvoiceLine.payable_item_id == payable.id,
                            FinancialInvoice.status != "paid",
                        )
                    )
                    or 0
                )
                if matched == payable.net_amount and unpaid_invoice_count == 0:
                    payable.status = "paid"
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_payment",
            entity_id=payment.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="reconcile",
            changed_fields=("amount", "status", "allocations"),
            status=payment.status,
            payload={"payment_reference": payment.reference},
        )
        return payment

    async def reverse_payment(
        self,
        session: AsyncSession,
        study_id: UUID,
        payment_id: UUID,
        payload: PaymentReversalCreate,
        *,
        actor_id: UUID,
        correlation_id: UUID | str | None = None,
    ) -> FinancialPayment:
        payment = await session.scalar(
            select(FinancialPayment).where(
                FinancialPayment.id == payment_id,
                FinancialPayment.study_id == study_id,
            )
        )
        if payment is None:
            raise NotFoundError("Financial payment was not found")
        if payment.status != "settled":
            raise ConflictError("Only a settled payment can be reversed")
        existing = await session.scalar(
            select(FinancialPayment.id).where(FinancialPayment.reversal_of_id == payment.id)
        )
        if existing is not None:
            raise ConflictError("This payment has already been reversed")
        reversal = FinancialPayment(
            study_id=study_id,
            party_id=payment.party_id,
            party_name=payment.party_name,
            direction=payment.direction,
            payment_date=payload.payment_date,
            amount=payment.amount,
            currency=payment.currency,
            reference=payload.reference,
            status="reversal",
            reversal_of_id=payment.id,
            created_by=actor_id,
        )
        session.add(reversal)
        payment.status = "reversed"
        await session.flush()

        invoice_ids = list(
            await session.scalars(
                select(PaymentAllocation.invoice_id).where(
                    PaymentAllocation.payment_id == payment.id
                )
            )
        )
        for invoice_id in invoice_ids:
            invoice = await session.get(FinancialInvoice, invoice_id)
            if invoice is None:
                continue
            settled = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                        .join(
                            FinancialPayment,
                            FinancialPayment.id == PaymentAllocation.payment_id,
                        )
                        .where(
                            PaymentAllocation.invoice_id == invoice.id,
                            FinancialPayment.status == "settled",
                        )
                    )
                )
            )
            invoice.status = (
                "paid"
                if settled == invoice.amount
                else "partially_paid"
                if settled > 0
                else "matched"
            )
            lines = list(
                await session.scalars(
                    select(FinancialInvoiceLine).where(
                        FinancialInvoiceLine.invoice_id == invoice.id
                    )
                )
            )
            for line in lines:
                payable = await session.get(PayableItem, line.payable_item_id)
                if payable is None:
                    continue
                matched = Decimal(
                    str(
                        await session.scalar(
                            select(func.coalesce(func.sum(FinancialInvoiceLine.amount), 0)).where(
                                FinancialInvoiceLine.payable_item_id == payable.id
                            )
                        )
                    )
                )
                payable.status = (
                    "invoiced" if matched == payable.net_amount else "partially_invoiced"
                )
        await session.flush()
        await ctms_atomicity_service.record_mutation(
            session,
            entity_type="ctms_financial_payment",
            entity_id=reversal.id,
            study_id=study_id,
            site_id=None,
            actor_id=actor_id,
            correlation_id=_correlation_uuid(correlation_id or get_correlation_id()),
            action="reverse",
            changed_fields=("status", "reversal_of_id"),
            previous_status="settled",
            status="reversal",
            reason=payload.reason,
            payload={"reversal_of_id": payment.id, "payment_reference": reversal.reference},
        )
        return reversal

    async def budget_version_payload(
        self, session: AsyncSession, version: FinancialBudgetVersion
    ) -> dict[str, Any]:
        lines = list(
            await session.scalars(
                select(FinancialBudgetLine)
                .where(FinancialBudgetLine.version_id == version.id)
                .order_by(FinancialBudgetLine.category, FinancialBudgetLine.description)
            )
        )
        return {
            "id": version.id,
            "budget_id": version.budget_id,
            "version_number": version.version_number,
            "status": version.status,
            "effective_from": version.effective_from,
            "reason": version.reason,
            "approved_at": version.approved_at,
            "approved_by": version.approved_by,
            "created_by": version.created_by,
            "created_at": version.created_at,
            "total": _money(sum((line.planned_amount for line in lines), Decimal("0"))),
            "lines": lines,
        }

    async def list_budget_payloads(
        self, session: AsyncSession, study_id: UUID
    ) -> list[dict[str, Any]]:
        budgets = list(
            await session.scalars(
                select(FinancialBudget)
                .where(FinancialBudget.study_id == study_id)
                .order_by(FinancialBudget.created_at.desc())
            )
        )
        result: list[dict[str, Any]] = []
        for budget in budgets:
            versions = list(
                await session.scalars(
                    select(FinancialBudgetVersion)
                    .where(FinancialBudgetVersion.budget_id == budget.id)
                    .order_by(FinancialBudgetVersion.version_number.desc())
                )
            )
            current = versions[0] if versions else None
            result.append(
                {
                    "id": budget.id,
                    "study_id": budget.study_id,
                    "name": budget.name,
                    "scope": budget.scope,
                    "currency": budget.currency,
                    "status": budget.status,
                    "created_by": budget.created_by,
                    "created_at": budget.created_at,
                    "current_version": (
                        await self.budget_version_payload(session, current) if current else None
                    ),
                }
            )
        return result

    async def financial_report(self, session: AsyncSession, study_id: UUID) -> dict[str, Any]:
        overview = await self.overview(session, study_id)
        now = datetime.now(UTC).date()
        aging = {
            "current": Decimal("0"),
            "1_30_days": Decimal("0"),
            "31_60_days": Decimal("0"),
            "61_90_days": Decimal("0"),
            "over_90_days": Decimal("0"),
        }
        cash_flow: dict[str, Decimal] = {}
        invoices = list(
            await session.scalars(
                select(FinancialInvoice).where(
                    FinancialInvoice.study_id == study_id,
                    FinancialInvoice.status != "paid",
                )
            )
        )
        for invoice in invoices:
            allocated = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                        .join(FinancialPayment, FinancialPayment.id == PaymentAllocation.payment_id)
                        .where(
                            PaymentAllocation.invoice_id == invoice.id,
                            FinancialPayment.status == "settled",
                        )
                    )
                )
            )
            balance = max(Decimal("0"), invoice.amount - allocated)
            days = (now - invoice.due_date).days
            bucket = (
                "current"
                if days <= 0
                else "1_30_days"
                if days <= 30
                else "31_60_days"
                if days <= 60
                else "61_90_days"
                if days <= 90
                else "over_90_days"
            )
            aging[bucket] += balance
            period = invoice.due_date.strftime("%Y-%m")
            cash_flow[period] = cash_flow.get(period, Decimal("0")) + balance
        contracted = overview["contracted"]
        approved = overview["approved"]
        return {
            **overview,
            "budget_variance": _money(overview["approved_budget"] - contracted),
            "contract_utilization_percent": _money(
                (overview["earned"] / contracted * 100) if contracted else Decimal("0")
            ),
            "invoice_coverage_percent": _money(
                (overview["invoiced"] / approved * 100) if approved else Decimal("0")
            ),
            "aging": {key: _money(value) for key, value in aging.items()},
            "cash_flow_forecast": [
                {"period": period, "amount": _money(amount)}
                for period, amount in sorted(cash_flow.items())
            ],
        }

    async def overview(self, session: AsyncSession, study_id: UUID) -> dict[str, Any]:
        currencies = list(
            await session.scalars(
                select(FinancialContract.currency)
                .where(FinancialContract.study_id == study_id)
                .distinct()
            )
        )
        budget_currencies = list(
            await session.scalars(
                select(FinancialBudget.currency)
                .where(FinancialBudget.study_id == study_id)
                .distinct()
            )
        )
        currencies = sorted(set(currencies + budget_currencies))
        if len(currencies) > 1:
            raise ValidationError(
                "Study financial overview requires a single reporting currency",
                {"currencies": sorted(currencies)},
            )
        contracted = Decimal(
            str(
                await session.scalar(
                    select(func.coalesce(func.sum(FinancialContractVersion.total_value), 0))
                    .join(
                        FinancialContract,
                        FinancialContract.id == FinancialContractVersion.contract_id,
                    )
                    .where(
                        FinancialContract.study_id == study_id,
                        FinancialContractVersion.status == "executed",
                    )
                )
            )
        )
        approved_budget = Decimal(
            str(
                await session.scalar(
                    select(func.coalesce(func.sum(FinancialBudgetLine.planned_amount), 0))
                    .join(
                        FinancialBudgetVersion,
                        FinancialBudgetVersion.id == FinancialBudgetLine.version_id,
                    )
                    .join(FinancialBudget, FinancialBudget.id == FinancialBudgetVersion.budget_id)
                    .where(
                        FinancialBudget.study_id == study_id,
                        FinancialBudgetVersion.status == "approved",
                    )
                )
            )
        )

        async def payable_sum(column, statuses: tuple[str, ...] | None = None) -> Decimal:
            query = select(func.coalesce(func.sum(column), 0)).where(
                PayableItem.study_id == study_id
            )
            if statuses:
                query = query.where(PayableItem.status.in_(statuses))
            return Decimal(str(await session.scalar(query)))

        earned = await payable_sum(PayableItem.gross_amount)
        holdback = await payable_sum(PayableItem.holdback_amount)
        approved = await payable_sum(
            PayableItem.net_amount,
            ("approved", "partially_invoiced", "invoiced", "paid"),
        )
        invoiced = Decimal(
            str(
                await session.scalar(
                    select(func.coalesce(func.sum(FinancialInvoice.amount), 0)).where(
                        FinancialInvoice.study_id == study_id
                    )
                )
            )
        )
        paid = Decimal(
            str(
                await session.scalar(
                    select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                    .join(FinancialPayment, FinancialPayment.id == PaymentAllocation.payment_id)
                    .where(
                        FinancialPayment.study_id == study_id,
                        FinancialPayment.status == "settled",
                    )
                )
            )
        )
        overdue = Decimal("0")
        overdue_invoices = list(
            await session.scalars(
                select(FinancialInvoice).where(
                    FinancialInvoice.study_id == study_id,
                    FinancialInvoice.due_date < datetime.now(UTC).date(),
                    FinancialInvoice.status != "paid",
                )
            )
        )
        for invoice in overdue_invoices:
            allocated = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
                        .join(
                            FinancialPayment,
                            FinancialPayment.id == PaymentAllocation.payment_id,
                        )
                        .where(
                            PaymentAllocation.invoice_id == invoice.id,
                            FinancialPayment.status == "settled",
                        )
                    )
                )
            )
            overdue += invoice.amount - allocated
        return {
            "study_id": study_id,
            "currency": currencies[0] if currencies else None,
            "approved_budget": _money(approved_budget),
            "contracted": _money(contracted),
            "earned": _money(earned),
            "holdback": _money(holdback),
            "approved": _money(approved),
            "invoiced": _money(invoiced),
            "paid": _money(paid),
            "outstanding": _money(max(Decimal("0"), approved - paid)),
            "overdue": _money(overdue),
        }


financial_service = FinancialService()

__all__ = ["FinancialService", "financial_service"]
