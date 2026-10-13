"""Add contract-driven CTMS financial operations.

Revision ID: 0066
Revises: 0065
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "ctms_financial_contracts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("contract_number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("contract_type", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("party_name", sa.String(255), nullable=False),
        sa.Column("country_code", sa.String(3), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "contract_number", name="uq_ctms_fin_contract_number"),
    )
    op.create_index(
        "ix_ctms_fin_contract_study_status", "ctms_financial_contracts", ["study_id", "status"]
    )

    op.create_table(
        "ctms_financial_contract_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("amendment_reason", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("total_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("holdback_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("payment_window_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("invoice_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tax_treatment", sa.String(100), nullable=True),
        sa.Column(
            "terms_snapshot_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "holdback_percent >= 0 AND holdback_percent <= 100", name="ck_ctms_fin_version_holdback"
        ),
        sa.CheckConstraint("total_value >= 0", name="ck_ctms_fin_version_value"),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["ctms_financial_contracts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["executed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "version_number", name="uq_ctms_fin_contract_version"),
    )
    op.create_table(
        "ctms_contract_payment_terms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("trigger_code", sa.String(100), nullable=False),
        sa.Column("unit_rate", sa.Numeric(18, 2), nullable=False),
        sa.Column("frequency", sa.String(30), nullable=True),
        sa.Column("quantity_cap", sa.Numeric(18, 4), nullable=True),
        sa.Column("amount_cap", sa.Numeric(18, 2), nullable=True),
        sa.Column("holdback_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_audit_columns(),
        sa.CheckConstraint("unit_rate >= 0", name="ck_ctms_fin_term_rate"),
        sa.CheckConstraint(
            "holdback_percent IS NULL OR (holdback_percent >= 0 AND holdback_percent <= 100)",
            name="ck_ctms_fin_term_holdback",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["ctms_financial_contract_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "code", name="uq_ctms_fin_term_code"),
    )
    op.create_table(
        "ctms_financial_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("visit_instance_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_code", sa.String(100), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *_audit_columns(),
        sa.CheckConstraint("quantity > 0", name="ck_ctms_fin_event_quantity"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["visit_instance_id"], ["visit_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "idempotency_key", name="uq_ctms_fin_event_idempotency"),
    )
    op.create_index(
        "ix_ctms_fin_event_study_trigger",
        "ctms_financial_events",
        ["study_id", "trigger_code", "event_date"],
    )
    op.create_table(
        "ctms_payable_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("contract_version_id", sa.Uuid(), nullable=False),
        sa.Column("contract_term_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("holdback_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="calculated"),
        sa.Column("calculation_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("gross_amount >= 0", name="ck_ctms_fin_payable_gross"),
        sa.CheckConstraint("holdback_amount >= 0", name="ck_ctms_fin_payable_holdback"),
        sa.CheckConstraint("net_amount >= 0", name="ck_ctms_fin_payable_net"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["ctms_financial_contracts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contract_version_id"], ["ctms_financial_contract_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["contract_term_id"], ["ctms_contract_payment_terms.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["ctms_financial_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "contract_term_id", name="uq_ctms_fin_payable_event_term"),
    )
    op.create_index(
        "ix_ctms_fin_payable_study_status", "ctms_payable_items", ["study_id", "status"]
    )
    op.create_table(
        "ctms_financial_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("party_name", sa.String(255), nullable=False),
        sa.Column("invoice_number", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="matched"),
        *_audit_columns(),
        sa.CheckConstraint("amount > 0", name="ck_ctms_fin_invoice_amount"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["contract_id"], ["ctms_financial_contracts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "party_name", "invoice_number", name="uq_ctms_fin_invoice"),
    )
    op.create_index(
        "ix_ctms_fin_invoice_study_status",
        "ctms_financial_invoices",
        ["study_id", "status", "due_date"],
    )
    op.create_table(
        "ctms_financial_invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("payable_item_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_ctms_fin_invoice_line_amount"),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["ctms_financial_invoices.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payable_item_id"], ["ctms_payable_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_id", "payable_item_id", name="uq_ctms_fin_invoice_payable"),
    )
    op.create_table(
        "ctms_financial_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("party_id", sa.Uuid(), nullable=True),
        sa.Column("party_name", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference", sa.String(150), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="settled"),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("amount > 0", name="ck_ctms_fin_payment_amount"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"], ["ctms_financial_payments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "reference", name="uq_ctms_fin_payment_reference"),
    )
    op.create_table(
        "ctms_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("allocated_amount > 0", name="ck_ctms_fin_allocation_amount"),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["ctms_financial_payments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["ctms_financial_invoices.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "invoice_id", name="uq_ctms_fin_payment_invoice"),
    )


def downgrade() -> None:
    op.drop_table("ctms_payment_allocations")
    op.drop_table("ctms_financial_payments")
    op.drop_table("ctms_financial_invoice_lines")
    op.drop_index("ix_ctms_fin_invoice_study_status", table_name="ctms_financial_invoices")
    op.drop_table("ctms_financial_invoices")
    op.drop_index("ix_ctms_fin_payable_study_status", table_name="ctms_payable_items")
    op.drop_table("ctms_payable_items")
    op.drop_index("ix_ctms_fin_event_study_trigger", table_name="ctms_financial_events")
    op.drop_table("ctms_financial_events")
    op.drop_table("ctms_contract_payment_terms")
    op.drop_table("ctms_financial_contract_versions")
    op.drop_index("ix_ctms_fin_contract_study_status", table_name="ctms_financial_contracts")
    op.drop_table("ctms_financial_contracts")
