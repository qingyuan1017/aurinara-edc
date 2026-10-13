"""Add configurable CTMS contract charge items and canonical links.

Revision ID: 0069
Revises: 0068
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ctms_financial_contracts", sa.Column("organization_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_ctms_fin_contract_organization",
        "ctms_financial_contracts",
        "ctms_managed_entities",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ctms_fin_contract_organization",
        "ctms_financial_contracts",
        ["organization_id"],
    )

    op.add_column(
        "ctms_contract_payment_terms", sa.Column("cost_category", sa.String(100), nullable=True)
    )
    op.add_column(
        "ctms_contract_payment_terms", sa.Column("billing_unit", sa.String(50), nullable=True)
    )
    op.add_column(
        "ctms_contract_payment_terms", sa.Column("visit_definition_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "ctms_contract_payment_terms", sa.Column("form_definition_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "ctms_contract_payment_terms", sa.Column("lab_code", sa.String(100), nullable=True)
    )
    op.add_column(
        "ctms_contract_payment_terms",
        sa.Column("invoice_category", sa.String(100), nullable=True),
    )
    op.add_column(
        "ctms_contract_payment_terms",
        sa.Column(
            "dimensions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_ctms_fin_term_visit_definition",
        "ctms_contract_payment_terms",
        "visit_definitions",
        ["visit_definition_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ctms_fin_term_form_definition",
        "ctms_contract_payment_terms",
        "form_definitions",
        ["form_definition_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ctms_fin_term_method_category",
        "ctms_contract_payment_terms",
        ["payment_method", "cost_category"],
    )
    op.create_index(
        "ix_ctms_fin_term_visit_definition",
        "ctms_contract_payment_terms",
        ["visit_definition_id"],
    )
    op.create_index(
        "ix_ctms_fin_term_form_definition",
        "ctms_contract_payment_terms",
        ["form_definition_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ctms_fin_term_form_definition", table_name="ctms_contract_payment_terms")
    op.drop_index("ix_ctms_fin_term_visit_definition", table_name="ctms_contract_payment_terms")
    op.drop_index("ix_ctms_fin_term_method_category", table_name="ctms_contract_payment_terms")
    op.drop_constraint(
        "fk_ctms_fin_term_form_definition", "ctms_contract_payment_terms", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_ctms_fin_term_visit_definition", "ctms_contract_payment_terms", type_="foreignkey"
    )
    op.drop_column("ctms_contract_payment_terms", "dimensions_json")
    op.drop_column("ctms_contract_payment_terms", "invoice_category")
    op.drop_column("ctms_contract_payment_terms", "lab_code")
    op.drop_column("ctms_contract_payment_terms", "form_definition_id")
    op.drop_column("ctms_contract_payment_terms", "visit_definition_id")
    op.drop_column("ctms_contract_payment_terms", "billing_unit")
    op.drop_column("ctms_contract_payment_terms", "cost_category")

    op.drop_index("ix_ctms_fin_contract_organization", table_name="ctms_financial_contracts")
    op.drop_constraint(
        "fk_ctms_fin_contract_organization", "ctms_financial_contracts", type_="foreignkey"
    )
    op.drop_column("ctms_financial_contracts", "organization_id")
