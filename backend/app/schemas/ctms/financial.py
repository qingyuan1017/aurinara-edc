"""Pydantic contracts for CTMS contract-to-payment operations."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models.ctms.financial import (
    ContractStatus,
    ContractType,
    FinancialDirection,
    PaymentMethod,
)
from app.schemas.shared.base import BaseCreateSchema, BaseSchema, UtcDatetime

Money = Decimal


class FinancialContractCreate(BaseCreateSchema):
    contract_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    contract_type: ContractType
    direction: FinancialDirection
    party_id: UUID | None = None
    organization_id: UUID | None = None
    party_name: str = Field(min_length=1, max_length=255)
    site_id: UUID | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=3)
    currency: str = Field(min_length=3, max_length=3)
    owner_id: UUID | None = None

    @field_validator("contract_number", "title", "party_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("currency", "country_code")
    @classmethod
    def uppercase(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class FinancialContractResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None = None
    contract_number: str
    title: str
    contract_type: ContractType
    direction: FinancialDirection
    party_id: UUID | None = None
    organization_id: UUID | None = None
    party_name: str
    country_code: str | None = None
    status: ContractStatus
    currency: str
    owner_id: UUID | None = None
    created_by: UUID
    updated_by: UUID | None = None
    correlation_id: UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ContractTransitionRequest(BaseCreateSchema):
    to_status: ContractStatus
    reason: str = Field(min_length=1, max_length=500)


class ContractVersionCreate(BaseCreateSchema):
    effective_from: date
    effective_to: date | None = None
    total_value: Money = Field(ge=0, max_digits=18, decimal_places=2)
    holdback_percent: Decimal = Field(
        default=Decimal("0"), ge=0, le=100, max_digits=5, decimal_places=2
    )
    payment_window_days: int = Field(default=30, ge=0, le=365)
    invoice_required: bool = True
    tax_treatment: str | None = Field(default=None, max_length=100)
    amendment_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_period(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ContractVersionResponse(BaseSchema):
    id: UUID
    contract_id: UUID
    version_number: int
    amendment_reason: str | None = None
    effective_from: date
    effective_to: date | None = None
    status: str
    total_value: Money
    holdback_percent: Decimal
    payment_window_days: int
    invoice_required: bool
    tax_treatment: str | None = None
    terms_snapshot_json: dict[str, Any]
    executed_at: UtcDatetime | None = None
    executed_by: UUID | None = None
    created_by: UUID
    created_at: UtcDatetime


class PaymentTermCreate(BaseCreateSchema):
    code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=255)
    payment_method: PaymentMethod
    trigger_code: str = Field(min_length=1, max_length=100)
    unit_rate: Money = Field(ge=0, max_digits=18, decimal_places=2)
    cost_category: str | None = Field(default=None, max_length=100)
    billing_unit: str | None = Field(default=None, max_length=50)
    visit_definition_id: UUID | None = None
    form_definition_id: UUID | None = None
    lab_code: str | None = Field(default=None, max_length=100)
    invoice_category: str | None = Field(default=None, max_length=100)
    dimensions_json: dict[str, str] = Field(default_factory=dict)
    frequency: str | None = Field(default=None, max_length=30)
    quantity_cap: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    amount_cap: Money | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    holdback_percent: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )

    @field_validator("code", "trigger_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("cost_category", "billing_unit", "lab_code", "invoice_category")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @model_validator(mode="after")
    def validate_calculation_basis(self):
        if self.payment_method == PaymentMethod.CRF and self.form_definition_id is None:
            raise ValueError("form_definition_id is required for a CRF-based charge item")
        if (
            self.payment_method == PaymentMethod.LAB
            and self.form_definition_id is None
            and not self.lab_code
        ):
            raise ValueError(
                "lab_code or form_definition_id is required for a lab-based charge item"
            )
        if self.payment_method == PaymentMethod.QUANTITY and not self.billing_unit:
            raise ValueError("billing_unit is required for a quantity-based charge item")
        return self


class PaymentTermResponse(BaseSchema):
    id: UUID
    version_id: UUID
    code: str
    description: str
    payment_method: PaymentMethod
    trigger_code: str
    unit_rate: Money
    cost_category: str | None = None
    billing_unit: str | None = None
    visit_definition_id: UUID | None = None
    form_definition_id: UUID | None = None
    lab_code: str | None = None
    invoice_category: str | None = None
    dimensions_json: dict[str, str] = Field(default_factory=dict)
    frequency: str | None = None
    quantity_cap: Decimal | None = None
    amount_cap: Money | None = None
    holdback_percent: Decimal | None = None
    active: bool
    created_by: UUID
    created_at: UtcDatetime


class FinancialDefinitionOption(BaseSchema):
    id: UUID
    code: str
    label: str
    version: str


class FinancialPaymentRuleOption(BaseSchema):
    code: str
    label: str
    charge_item_count: int
    methods: list[PaymentMethod]


class FinancialConfigurationOptions(BaseSchema):
    visits: list[FinancialDefinitionOption]
    forms: list[FinancialDefinitionOption]
    payment_rules: list[FinancialPaymentRuleOption]


class BudgetLineCreate(BaseCreateSchema):
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit_cost: Money = Field(ge=0, max_digits=18, decimal_places=2)


class BudgetLineResponse(BaseSchema):
    id: UUID
    version_id: UUID
    category: str
    description: str
    quantity: Decimal
    unit_cost: Money
    planned_amount: Money


class BudgetCreate(BaseCreateSchema):
    name: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="study", pattern="^(study|site|vendor)$")
    currency: str = Field(min_length=3, max_length=3)
    effective_from: date
    reason: str | None = Field(default=None, max_length=500)
    lines: list[BudgetLineCreate] = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class BudgetVersionCreate(BaseCreateSchema):
    effective_from: date
    reason: str = Field(min_length=1, max_length=500)
    lines: list[BudgetLineCreate] = Field(min_length=1)


class BudgetVersionResponse(BaseSchema):
    id: UUID
    budget_id: UUID
    version_number: int
    status: str
    effective_from: date
    reason: str | None = None
    approved_at: UtcDatetime | None = None
    approved_by: UUID | None = None
    created_by: UUID
    created_at: UtcDatetime
    total: Money
    lines: list[BudgetLineResponse]


class BudgetResponse(BaseSchema):
    id: UUID
    study_id: UUID
    name: str
    scope: str
    currency: str
    status: str
    created_by: UUID
    created_at: UtcDatetime
    current_version: BudgetVersionResponse | None = None


class FinancialAuditEntry(BaseSchema):
    id: UUID
    entity_type: str
    entity_id: UUID
    action: str
    actor_id: UUID | None = None
    timestamp: UtcDatetime
    reason: str | None = None
    changed_fields: list[str] | None = None


class CashFlowBucket(BaseSchema):
    period: str
    amount: Money


class FinancialReportResponse(BaseSchema):
    study_id: UUID
    currency: str | None = None
    approved_budget: Money
    contracted: Money
    earned: Money
    approved: Money
    invoiced: Money
    paid: Money
    outstanding: Money
    overdue: Money
    budget_variance: Money
    contract_utilization_percent: Decimal
    invoice_coverage_percent: Decimal
    aging: dict[str, Money]
    cash_flow_forecast: list[CashFlowBucket]


class FinancialEventCalculate(BaseCreateSchema):
    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_instance_id: UUID | None = None
    source_type: str = Field(min_length=1, max_length=50)
    source_id: UUID | None = None
    trigger_code: str = Field(min_length=1, max_length=100)
    event_date: date
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=18, decimal_places=4)
    verification_status: str = Field(default="verified", pattern="^(verified|approved)$")
    idempotency_key: str = Field(min_length=1, max_length=255)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trigger_code")
    @classmethod
    def normalize_trigger(cls, value: str) -> str:
        return value.strip().upper()


class FinancialEventResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None = None
    subject_id: UUID | None = None
    visit_instance_id: UUID | None = None
    source_type: str
    source_id: UUID | None = None
    trigger_code: str
    event_date: date
    quantity: Decimal
    verification_status: str
    idempotency_key: str
    evidence: dict[str, Any] = Field(validation_alias="evidence_json")
    created_by: UUID
    created_at: UtcDatetime


class PayableItemResponse(BaseSchema):
    id: UUID
    study_id: UUID
    contract_id: UUID
    contract_version_id: UUID
    contract_term_id: UUID
    event_id: UUID
    gross_amount: Money
    holdback_amount: Money
    net_amount: Money
    currency: str
    status: str
    calculation_snapshot: dict[str, Any] = Field(validation_alias="calculation_snapshot_json")
    approved_at: UtcDatetime | None = None
    approved_by: UUID | None = None
    created_at: UtcDatetime


class FinancialCalculationResponse(BaseSchema):
    event: FinancialEventResponse
    payable_items: list[PayableItemResponse]
    replayed: bool = False


class ApprovalRequest(BaseCreateSchema):
    reason: str = Field(min_length=1, max_length=500)


class InvoiceLineCreate(BaseCreateSchema):
    payable_item_id: UUID
    amount: Money = Field(gt=0, max_digits=18, decimal_places=2)


class InvoiceCreate(BaseCreateSchema):
    contract_id: UUID
    party_id: UUID | None = None
    party_name: str = Field(min_length=1, max_length=255)
    invoice_number: str = Field(min_length=1, max_length=100)
    direction: FinancialDirection
    invoice_date: date
    due_date: date
    amount: Money = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    lines: list[InvoiceLineCreate] = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_invoice(self):
        if self.due_date < self.invoice_date:
            raise ValueError("due_date must be on or after invoice_date")
        if sum((line.amount for line in self.lines), Decimal("0")) != self.amount:
            raise ValueError("invoice line amounts must equal invoice amount")
        return self


class InvoiceResponse(BaseSchema):
    id: UUID
    study_id: UUID
    contract_id: UUID
    party_id: UUID | None = None
    party_name: str
    invoice_number: str
    direction: FinancialDirection
    invoice_date: date
    due_date: date
    amount: Money
    currency: str
    status: str
    created_by: UUID
    created_at: UtcDatetime


class PaymentAllocationCreate(BaseCreateSchema):
    invoice_id: UUID
    allocated_amount: Money = Field(gt=0, max_digits=18, decimal_places=2)


class PaymentCreate(BaseCreateSchema):
    party_id: UUID | None = None
    party_name: str = Field(min_length=1, max_length=255)
    direction: FinancialDirection
    payment_date: date
    amount: Money = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=150)
    allocations: list[PaymentAllocationCreate] = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_allocations(self):
        if sum((item.allocated_amount for item in self.allocations), Decimal("0")) != self.amount:
            raise ValueError("payment allocations must equal payment amount")
        return self


class PaymentReversalCreate(BaseCreateSchema):
    payment_date: date
    reference: str = Field(min_length=1, max_length=150)
    reason: str = Field(min_length=1, max_length=500)


class PaymentResponse(BaseSchema):
    id: UUID
    study_id: UUID
    party_id: UUID | None = None
    party_name: str
    direction: FinancialDirection
    payment_date: date
    amount: Money
    currency: str
    reference: str
    status: str
    reversal_of_id: UUID | None = None
    created_by: UUID
    created_at: UtcDatetime


class FinancialOverviewResponse(BaseSchema):
    study_id: UUID
    currency: str | None = None
    approved_budget: Money
    contracted: Money
    earned: Money
    holdback: Money
    approved: Money
    invoiced: Money
    paid: Money
    outstanding: Money
    overdue: Money


__all__ = [
    "ApprovalRequest",
    "BudgetCreate",
    "BudgetLineCreate",
    "BudgetLineResponse",
    "BudgetResponse",
    "BudgetVersionCreate",
    "BudgetVersionResponse",
    "CashFlowBucket",
    "ContractTransitionRequest",
    "ContractVersionCreate",
    "ContractVersionResponse",
    "FinancialAuditEntry",
    "FinancialCalculationResponse",
    "FinancialContractCreate",
    "FinancialContractResponse",
    "FinancialEventCalculate",
    "FinancialEventResponse",
    "FinancialOverviewResponse",
    "FinancialReportResponse",
    "InvoiceCreate",
    "InvoiceResponse",
    "PayableItemResponse",
    "PaymentCreate",
    "PaymentResponse",
    "PaymentReversalCreate",
    "PaymentTermCreate",
    "PaymentTermResponse",
]
