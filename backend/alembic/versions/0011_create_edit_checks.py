"""Create edit_checks and validation_results tables.

Revision ID: 0011
Revises: 0010
Create Date: 2024-01-11 00:00:00.000000

Declarative edit check rules versioned with their owning Study_Version,
plus validation results produced when rules fire against form instances.

Requirements:
  - 12.1: Rule validated against operator/condition schema before persisting.
  - 12.6: Edit checks versioned with their owning Study_Version.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- edit_checks ---
    op.create_table(
        "edit_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "rule_json",
            sa.JSON(),
            nullable=False,
            comment="Declarative JSON DSL rule definition (boolean tree of conditions)",
        ),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            comment="One of: info, warning, error, query",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_edit_checks_study_version_id", "edit_checks", ["study_version_id"])
    op.create_index("ix_edit_checks_severity", "edit_checks", ["severity"])
    op.create_index("ix_edit_checks_is_active", "edit_checks", ["is_active"])

    # --- validation_results ---
    op.create_table(
        "validation_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "edit_check_id",
            sa.Uuid(),
            sa.ForeignKey("edit_checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "form_instance_id",
            sa.Uuid(),
            sa.ForeignKey("form_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            comment="One of: info, warning, error, query",
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_validation_results_edit_check_id", "validation_results", ["edit_check_id"]
    )
    op.create_index(
        "ix_validation_results_form_instance_id",
        "validation_results",
        ["form_instance_id"],
    )
    op.create_index(
        "ix_validation_results_is_resolved", "validation_results", ["is_resolved"]
    )


def downgrade() -> None:
    op.drop_index("ix_validation_results_is_resolved", table_name="validation_results")
    op.drop_index(
        "ix_validation_results_form_instance_id", table_name="validation_results"
    )
    op.drop_index("ix_validation_results_edit_check_id", table_name="validation_results")
    op.drop_table("validation_results")

    op.drop_index("ix_edit_checks_is_active", table_name="edit_checks")
    op.drop_index("ix_edit_checks_severity", table_name="edit_checks")
    op.drop_index("ix_edit_checks_study_version_id", table_name="edit_checks")
    op.drop_table("edit_checks")
