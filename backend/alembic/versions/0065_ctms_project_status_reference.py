"""Add configurable CTMS project workflow statuses.

Revision ID: 0065
Revises: 0064
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | Sequence[str] | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PROJECT_STATUSES = (
    ("DRAFT", "Draft"),
    ("ACTIVE", "Active"),
    ("BLOCKED", "Blocked"),
    ("COMPLETED", "Complete"),
)


def upgrade() -> None:
    op.drop_constraint("ck_ctms_reference_values_category", "ctms_reference_values", type_="check")
    op.create_check_constraint(
        "ck_ctms_reference_values_category",
        "ctms_reference_values",
        "category IN ('country','participating_organization_type','therapeutic_area','indication','milestone_type','project_status')",
    )
    reference_table = sa.table(
        "ctms_reference_values",
        sa.column("id", sa.Uuid()),
        sa.column("category", sa.String()),
        sa.column("code", sa.String()),
        sa.column("label", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("active", sa.Boolean()),
    )
    op.bulk_insert(
        reference_table,
        [
            {
                "id": uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"aurinara:ctms-reference:project_status:{code}",
                ),
                "category": "project_status",
                "code": code,
                "label": label,
                "sort_order": index * 10,
                "active": True,
            }
            for index, (code, label) in enumerate(PROJECT_STATUSES, start=1)
        ],
    )
    op.alter_column(
        "ctms_study_plans",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
    op.drop_constraint("ck_ctms_study_plans_status", "ctms_study_plans", type_="check")
    op.execute(
        """
        UPDATE ctms_study_plans
        SET status = CASE status
            WHEN 'Draft' THEN 'DRAFT'
            WHEN 'Active' THEN 'ACTIVE'
            WHEN 'Blocked' THEN 'BLOCKED'
            WHEN 'Completed' THEN 'COMPLETED'
            ELSE status
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ctms_study_plans
        SET status = CASE status
            WHEN 'ACTIVE' THEN 'Active'
            WHEN 'BLOCKED' THEN 'Blocked'
            WHEN 'COMPLETED' THEN 'Completed'
            WHEN 'ARCHIVED' THEN 'Archived'
            ELSE 'Draft'
        END
        """
    )
    op.alter_column(
        "ctms_study_plans",
        "status",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_ctms_study_plans_status",
        "ctms_study_plans",
        "status IN ('Draft','Active','Completed','Archived')",
    )
    op.execute("DELETE FROM ctms_reference_values WHERE category = 'project_status'")
    op.drop_constraint("ck_ctms_reference_values_category", "ctms_reference_values", type_="check")
    op.create_check_constraint(
        "ck_ctms_reference_values_category",
        "ctms_reference_values",
        "category IN ('country','participating_organization_type','therapeutic_area','indication','milestone_type')",
    )
