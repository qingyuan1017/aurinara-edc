"""Expand CTMS project milestones and master activities.

Revision ID: 0064
Revises: 0063
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ctms_reference_values_category", "ctms_reference_values", type_="check")
    op.create_check_constraint(
        "ck_ctms_reference_values_category",
        "ctms_reference_values",
        "category IN ('country','participating_organization_type','therapeutic_area','indication','milestone_type')",
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
    labels = (
        "Study Start",
        "Regulatory",
        "Site Startup",
        "Enrollment",
        "Monitoring",
        "Database Lock",
        "Study Closeout",
    )
    op.bulk_insert(
        reference_table,
        [
            {
                "id": uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"aurinara:ctms-reference:milestone_type:{label.upper().replace(' ', '_')}",
                ),
                "category": "milestone_type",
                "code": label.upper().replace(" ", "_"),
                "label": label,
                "sort_order": index * 10,
                "active": True,
            }
            for index, label in enumerate(labels, start=1)
        ],
    )

    op.add_column("ctms_study_milestones", sa.Column("description", sa.Text()))
    op.add_column(
        "ctms_study_milestones",
        sa.Column("scope_level", sa.String(20), nullable=False, server_default="study"),
    )
    op.add_column("ctms_study_milestones", sa.Column("country_code", sa.String(100)))
    op.add_column(
        "ctms_study_milestones",
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
    )
    op.create_index(
        "ix_ctms_study_milestones_scope",
        "ctms_study_milestones",
        ["study_id", "scope_level", "country_code", "site_id"],
    )
    op.create_check_constraint(
        "ck_ctms_study_milestones_scope_level",
        "ctms_study_milestones",
        "scope_level IN ('study','country','site')",
    )
    op.create_check_constraint(
        "ck_ctms_study_milestones_scope_fields",
        "ctms_study_milestones",
        "(scope_level = 'study' AND country_code IS NULL AND site_id IS NULL) OR "
        "(scope_level = 'country' AND site_id IS NULL) OR "
        "(scope_level = 'site' AND country_code IS NULL)",
    )

    op.add_column(
        "ctms_study_plans",
        sa.Column(
            "milestone_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_study_milestones.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "ctms_study_plans",
        sa.Column("scope_level", sa.String(20), nullable=False, server_default="study"),
    )
    op.add_column("ctms_study_plans", sa.Column("country_code", sa.String(100)))
    op.add_column(
        "ctms_study_plans",
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
    )
    op.add_column(
        "ctms_study_plans",
        sa.Column("assignee_role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="SET NULL")),
    )
    op.add_column(
        "ctms_study_plans",
        sa.Column("assignee_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.add_column("ctms_study_plans", sa.Column("start_at", sa.DateTime(timezone=True)))
    op.add_column("ctms_study_plans", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.create_index("ix_ctms_study_plans_milestone", "ctms_study_plans", ["milestone_id"])
    op.create_index(
        "ix_ctms_study_plans_scope",
        "ctms_study_plans",
        ["study_id", "scope_level", "country_code", "site_id"],
    )
    op.create_check_constraint(
        "ck_ctms_study_plans_scope_level",
        "ctms_study_plans",
        "scope_level IN ('study','country','site')",
    )
    op.create_check_constraint(
        "ck_ctms_study_plans_scope_fields",
        "ctms_study_plans",
        "(scope_level = 'study' AND country_code IS NULL AND site_id IS NULL) OR "
        "(scope_level = 'country' AND site_id IS NULL) OR "
        "(scope_level = 'site' AND country_code IS NULL)",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ctms_study_plans DROP CONSTRAINT IF EXISTS ck_ctms_study_plans_scope_fields"
    )
    op.execute(
        "ALTER TABLE ctms_study_plans DROP CONSTRAINT IF EXISTS ck_ctms_study_plans_scope_level"
    )
    op.drop_index("ix_ctms_study_plans_scope", table_name="ctms_study_plans")
    op.drop_index("ix_ctms_study_plans_milestone", table_name="ctms_study_plans")
    for column in (
        "due_at",
        "start_at",
        "assignee_user_id",
        "assignee_role_id",
        "site_id",
        "country_code",
        "scope_level",
        "milestone_id",
    ):
        op.drop_column("ctms_study_plans", column)
    op.execute(
        "ALTER TABLE ctms_study_milestones DROP CONSTRAINT IF EXISTS "
        "ck_ctms_study_milestones_scope_fields"
    )
    op.execute(
        "ALTER TABLE ctms_study_milestones DROP CONSTRAINT IF EXISTS "
        "ck_ctms_study_milestones_scope_level"
    )
    op.drop_index("ix_ctms_study_milestones_scope", table_name="ctms_study_milestones")
    for column in ("site_id", "country_code", "scope_level", "description"):
        op.drop_column("ctms_study_milestones", column)
    op.execute("DELETE FROM ctms_reference_values WHERE category = 'milestone_type'")
    op.drop_constraint("ck_ctms_reference_values_category", "ctms_reference_values", type_="check")
    op.create_check_constraint(
        "ck_ctms_reference_values_category",
        "ctms_reference_values",
        "category IN ('country','participating_organization_type','therapeutic_area','indication')",
    )
