"""Add versioned CTMS financial budgets.

Revision ID: 0068
Revises: 0067
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | Sequence[str] | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_financial_budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(30), nullable=False, server_default="study"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "name", name="uq_ctms_fin_budget_name"),
    )
    op.create_index(
        "ix_ctms_fin_budget_study_status", "ctms_financial_budgets", ["study_id", "status"]
    )
    op.create_table(
        "ctms_financial_budget_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["budget_id"], ["ctms_financial_budgets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("budget_id", "version_number", name="uq_ctms_fin_budget_version"),
    )
    op.create_index(
        "ix_ctms_fin_budget_version_status",
        "ctms_financial_budget_versions",
        ["budget_id", "status"],
    )
    op.create_index(
        "uq_ctms_fin_budget_one_approved",
        "ctms_financial_budget_versions",
        ["budget_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_index(
        "uq_ctms_fin_budget_one_draft",
        "ctms_financial_budget_versions",
        ["budget_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_table(
        "ctms_financial_budget_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("planned_amount", sa.Numeric(18, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_ctms_fin_budget_line_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_ctms_fin_budget_line_unit_cost"),
        sa.CheckConstraint("planned_amount >= 0", name="ck_ctms_fin_budget_line_amount"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["ctms_financial_budget_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ctms_fin_budget_line_version_category",
        "ctms_financial_budget_lines",
        ["version_id", "category"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ctms_fin_budget_line_version_category", table_name="ctms_financial_budget_lines"
    )
    op.drop_table("ctms_financial_budget_lines")
    op.execute("DROP INDEX IF EXISTS uq_ctms_fin_budget_one_draft")
    op.execute("DROP INDEX IF EXISTS uq_ctms_fin_budget_one_approved")
    op.drop_index("ix_ctms_fin_budget_version_status", table_name="ctms_financial_budget_versions")
    op.drop_table("ctms_financial_budget_versions")
    op.drop_index("ix_ctms_fin_budget_study_status", table_name="ctms_financial_budgets")
    op.drop_table("ctms_financial_budgets")
