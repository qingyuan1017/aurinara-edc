"""Contract-driven CTMS financial operations models.

The ledger deliberately stores calculation and allocation facts instead of
mutable roll-up totals.  Overview values are derived from these rows so the
contract, payable, invoice, and settlement views cannot drift apart.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JSONBType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContractType(enum.StrEnum):
    SPONSOR = "sponsor_agreement"
    SITE = "clinical_trial_agreement"
    VENDOR = "vendor_agreement"


class FinancialDirection(enum.StrEnum):
    RECEIVABLE = "receivable"
    PAYABLE = "payable"


class ContractStatus(enum.StrEnum):
    DRAFT = "draft"
    INTERNAL_REVIEW = "internal_review"
    NEGOTIATION = "negotiation"
    APPROVED = "approved"
    EXECUTED = "executed"
    ACTIVE = "active"
    CLOSED = "closed"


class ContractVersionStatus(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTED = "executed"
    SUPERSEDED = "superseded"


class BudgetStatus(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    CLOSED = "closed"


class PaymentMethod(enum.StrEnum):
    FIXED = "fixed"
    VISIT = "visit_based"
    CRF = "crf_based"
    INVOICE = "invoice_based"
    LAB = "lab_based"
    QUANTITY = "quantity_based"
    PROCEDURE = "procedure_based"
    MILESTONE = "milestone_based"
    RECURRING = "recurring"
    PASS_THROUGH = "pass_through"
    MANUAL_ADJUSTMENT = "manual_adjustment"


class FinancialContract(Base):
    __tablename__ = "ctms_financial_contracts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT"), nullable=True
    )
    contract_number: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    party_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        UniqueConstraint("study_id", "contract_number", name="uq_ctms_fin_contract_number"),
        Index("ix_ctms_fin_contract_study_status", "study_id", "status"),
        Index("ix_ctms_fin_contract_organization", "organization_id"),
    )


class FinancialContractVersion(Base):
    __tablename__ = "ctms_financial_contract_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_contracts.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amendment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    holdback_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    payment_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    invoice_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tax_treatment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    terms_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("contract_id", "version_number", name="uq_ctms_fin_contract_version"),
        CheckConstraint(
            "holdback_percent >= 0 AND holdback_percent <= 100",
            name="ck_ctms_fin_version_holdback",
        ),
        CheckConstraint("total_value >= 0", name="ck_ctms_fin_version_value"),
    )


class ContractPaymentTerm(Base):
    __tablename__ = "ctms_contract_payment_terms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_contract_versions.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_code: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visit_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("visit_definitions.id", ondelete="RESTRICT"), nullable=True
    )
    form_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("form_definitions.id", ondelete="RESTRICT"), nullable=True
    )
    lab_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quantity_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    amount_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    holdback_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("version_id", "code", name="uq_ctms_fin_term_code"),
        CheckConstraint("unit_rate >= 0", name="ck_ctms_fin_term_rate"),
        CheckConstraint(
            "holdback_percent IS NULL OR (holdback_percent >= 0 AND holdback_percent <= 100)",
            name="ck_ctms_fin_term_holdback",
        ),
        Index("ix_ctms_fin_term_method_category", "payment_method", "cost_category"),
        Index("ix_ctms_fin_term_visit_definition", "visit_definition_id"),
        Index("ix_ctms_fin_term_form_definition", "form_definition_id"),
    )


class FinancialBudget(Base):
    __tablename__ = "ctms_financial_budgets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="study")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("study_id", "name", name="uq_ctms_fin_budget_name"),
        Index("ix_ctms_fin_budget_study_status", "study_id", "status"),
    )


class FinancialBudgetVersion(Base):
    __tablename__ = "ctms_financial_budget_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("budget_id", "version_number", name="uq_ctms_fin_budget_version"),
        Index("ix_ctms_fin_budget_version_status", "budget_id", "status"),
        Index(
            "uq_ctms_fin_budget_one_approved",
            "budget_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
            sqlite_where=text("status = 'approved'"),
        ),
        Index(
            "uq_ctms_fin_budget_one_draft",
            "budget_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
            sqlite_where=text("status = 'draft'"),
        ),
    )


class FinancialBudgetLine(Base):
    __tablename__ = "ctms_financial_budget_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_budget_versions.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_ctms_fin_budget_line_quantity"),
        CheckConstraint("unit_cost >= 0", name="ck_ctms_fin_budget_line_unit_cost"),
        CheckConstraint("planned_amount >= 0", name="ck_ctms_fin_budget_line_amount"),
        Index("ix_ctms_fin_budget_line_version_category", "version_id", "category"),
    )


class FinancialEvent(Base):
    __tablename__ = "ctms_financial_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="RESTRICT"), nullable=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    visit_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("visit_instances.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    trigger_code: Mapped[str] = mapped_column(String(100), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("study_id", "idempotency_key", name="uq_ctms_fin_event_idempotency"),
        CheckConstraint("quantity > 0", name="ck_ctms_fin_event_quantity"),
        Index("ix_ctms_fin_event_study_trigger", "study_id", "trigger_code", "event_date"),
    )


class PayableItem(Base):
    __tablename__ = "ctms_payable_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_contracts.id", ondelete="RESTRICT"), nullable=False
    )
    contract_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_contract_versions.id", ondelete="RESTRICT"), nullable=False
    )
    contract_term_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_contract_payment_terms.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_events.id", ondelete="RESTRICT"), nullable=False
    )
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    holdback_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="calculated")
    calculation_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("event_id", "contract_term_id", name="uq_ctms_fin_payable_event_term"),
        CheckConstraint("gross_amount >= 0", name="ck_ctms_fin_payable_gross"),
        CheckConstraint("holdback_amount >= 0", name="ck_ctms_fin_payable_holdback"),
        CheckConstraint("net_amount >= 0", name="ck_ctms_fin_payable_net"),
        Index("ix_ctms_fin_payable_study_status", "study_id", "status"),
    )


class FinancialInvoice(Base):
    __tablename__ = "ctms_financial_invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_contracts.id", ondelete="RESTRICT"), nullable=False
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="matched")
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("study_id", "party_name", "invoice_number", name="uq_ctms_fin_invoice"),
        CheckConstraint("amount > 0", name="ck_ctms_fin_invoice_amount"),
        Index("ix_ctms_fin_invoice_study_status", "study_id", "status", "due_date"),
    )


class FinancialInvoiceLine(Base):
    __tablename__ = "ctms_financial_invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    payable_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_payable_items.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("invoice_id", "payable_item_id", name="uq_ctms_fin_invoice_payable"),
        CheckConstraint("amount > 0", name="ck_ctms_fin_invoice_line_amount"),
    )


class FinancialPayment(Base):
    __tablename__ = "ctms_financial_payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    party_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="settled")
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ctms_financial_payments.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("study_id", "reference", name="uq_ctms_fin_payment_reference"),
        CheckConstraint("amount > 0", name="ck_ctms_fin_payment_amount"),
    )


class PaymentAllocation(Base):
    __tablename__ = "ctms_payment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_payments.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ctms_financial_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id", name="uq_ctms_fin_payment_invoice"),
        CheckConstraint("allocated_amount > 0", name="ck_ctms_fin_allocation_amount"),
    )


__all__ = [
    "BudgetStatus",
    "ContractPaymentTerm",
    "ContractStatus",
    "ContractType",
    "ContractVersionStatus",
    "FinancialBudget",
    "FinancialBudgetLine",
    "FinancialBudgetVersion",
    "FinancialContract",
    "FinancialContractVersion",
    "FinancialDirection",
    "FinancialEvent",
    "FinancialInvoice",
    "FinancialInvoiceLine",
    "FinancialPayment",
    "PayableItem",
    "PaymentAllocation",
    "PaymentMethod",
]
