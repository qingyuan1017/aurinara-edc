"""Complete CTMS operational study planning persistence.

This additive revision adds only CTMS-owned planning/query tables and the
operational planning metadata column. Canonical EDC study and Study_Version
tables remain unchanged and authoritative.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
    ]


def upgrade() -> None:
    op.add_column(
        "ctms_operational_studies",
        sa.Column("planning_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.create_table(
        "ctms_enrollment_plans",
        *_common_columns(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("target_quantity", sa.Integer()),
        sa.Column("planning_period_start", sa.DateTime(timezone=True)),
        sa.Column("planning_period_end", sa.DateTime(timezone=True)),
        sa.Column("planning_scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
    )
    op.create_index("ix_ctms_enrollment_plans_study_status", "ctms_enrollment_plans", ["study_id", "status"])

    op.create_table(
        "ctms_readiness_criteria",
        *_common_columns(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="Open"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("evidence_reference", sa.String(500)),
    )
    op.create_index("ix_ctms_readiness_criteria_study_status", "ctms_readiness_criteria", ["study_id", "status"])

    op.create_table(
        "ctms_study_milestones",
        *_common_columns(),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("milestone_type", sa.String(100), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Planned"),
    )
    op.create_index("ix_ctms_study_milestones_study_status", "ctms_study_milestones", ["study_id", "status"])

    for table in ("ctms_dashboard_queries", "ctms_report_queries"):
        op.create_table(
            table,
            *_common_columns(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("query_definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("status", sa.String(20), nullable=False, server_default="Active"),
        )
        op.create_index(f"ix_{table}_study_status", table, ["study_id", "status"])


def downgrade() -> None:
    for table in ("ctms_report_queries", "ctms_dashboard_queries", "ctms_study_milestones", "ctms_readiness_criteria", "ctms_enrollment_plans"):
        op.drop_index(f"ix_{table}_study_status", table_name=table)
        op.drop_table(table)
    op.drop_column("ctms_operational_studies", "planning_metadata")
