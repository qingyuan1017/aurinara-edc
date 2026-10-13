"""Read-only contracts for CTMS portfolio operations."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.schemas.shared.base import BaseSchema, UtcDatetime


class PortfolioMonitoringSummary(BaseSchema):
    total: int = 0
    upcoming: int = 0
    overdue: int = 0
    in_progress: int = 0
    completed: int = 0
    unassigned: int = 0
    open_findings: int = 0


class PortfolioMonitoringActivity(BaseSchema):
    id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    site_number: str | None = None
    site_name: str | None = None
    activity_type: str
    modality: str
    planned_date: UtcDatetime
    assigned_cra_id: UUID | None = None
    assigned_cra_name: str | None = None
    status: str
    is_overdue: bool
    overdue_days: int = 0
    open_findings: int = 0
    report_status: str | None = None
    reschedule_count: int = 0
    escalation_reference: str | None = None


class PortfolioCraWorkload(BaseSchema):
    cra_id: UUID | None = None
    cra_name: str
    total: int = 0
    upcoming: int = 0
    overdue: int = 0
    in_progress: int = 0
    completed: int = 0


class PortfolioMonitoringFinding(BaseSchema):
    id: UUID
    finding_code: str
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    site_number: str | None = None
    site_name: str | None = None
    visit_id: UUID | None = None
    category: str
    severity: str
    description: str
    owner_id: UUID | None = None
    owner_name: str | None = None
    responsible_party: str | None = None
    due_date: UtcDatetime | None = None
    status: str
    capa_required: bool = False
    open_actions: int = 0
    is_overdue: bool = False


class PortfolioContractSummary(BaseSchema):
    total: int = 0
    internal_review: int = 0
    negotiation: int = 0
    approved_awaiting_execution: int = 0
    active: int = 0
    expiring_30_days: int = 0
    expired: int = 0


class PortfolioContract(BaseSchema):
    id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    site_id: UUID | None = None
    site_number: str | None = None
    site_name: str | None = None
    organization_id: UUID | None = None
    contract_number: str
    title: str
    contract_type: str
    direction: str
    party_name: str
    status: str
    currency: str
    owner_id: UUID | None = None
    owner_name: str | None = None
    current_version_id: UUID | None = None
    version_status: str | None = None
    total_value: Decimal | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    days_to_expiry: int | None = None


class PortfolioCurrencySummary(BaseSchema):
    currency: str
    approved_budget: Decimal = Decimal("0")
    contracted: Decimal = Decimal("0")
    calculated_payables: Decimal = Decimal("0")
    approved_payables: Decimal = Decimal("0")
    invoiced: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    outstanding: Decimal = Decimal("0")
    overdue: Decimal = Decimal("0")
    budget_variance: Decimal = Decimal("0")


class PortfolioPayable(BaseSchema):
    id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    contract_id: UUID
    contract_number: str
    party_name: str
    gross_amount: Decimal
    holdback_amount: Decimal
    net_amount: Decimal
    currency: str
    status: str
    approved_at: UtcDatetime | None = None
    created_at: UtcDatetime


class PortfolioInvoice(BaseSchema):
    id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    contract_id: UUID
    contract_number: str
    party_name: str
    invoice_number: str
    direction: str
    invoice_date: date
    due_date: date
    amount: Decimal
    currency: str
    status: str
    paid_amount: Decimal = Decimal("0")
    outstanding_amount: Decimal = Decimal("0")
    is_overdue: bool = False
    days_overdue: int = 0


class PortfolioPayment(BaseSchema):
    id: UUID
    study_id: UUID
    study_code: str
    study_title: str
    party_name: str
    direction: str
    payment_date: date
    amount: Decimal
    allocated_amount: Decimal = Decimal("0")
    currency: str
    reference: str
    status: str
    reversal_of_id: UUID | None = None


class PortfolioFinancialReportRow(PortfolioCurrencySummary):
    study_id: UUID
    study_code: str
    study_title: str
    group_by: str = "study"
    group_key: str
    group_label: str


class PortfolioFinancialSummary(BaseSchema):
    currencies: list[PortfolioCurrencySummary] = Field(default_factory=list)


__all__ = [
    "PortfolioContract",
    "PortfolioContractSummary",
    "PortfolioCraWorkload",
    "PortfolioCurrencySummary",
    "PortfolioFinancialReportRow",
    "PortfolioFinancialSummary",
    "PortfolioInvoice",
    "PortfolioMonitoringActivity",
    "PortfolioMonitoringFinding",
    "PortfolioMonitoringSummary",
    "PortfolioPayable",
    "PortfolioPayment",
]
