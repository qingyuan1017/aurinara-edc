"""Add CTMS study configuration and entity management.

Revision ID: 0060
Revises: 0059
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column("study_type", sa.String(100)),
        sa.Column("main_purpose", sa.String(100)),
        sa.Column("program", sa.String(255)),
        sa.Column("study_description", sa.Text()),
        sa.Column("investigational_product", sa.String(500)),
        sa.Column("blind_method", sa.String(100)),
        sa.Column("randomized", sa.Boolean()),
        sa.Column("expected_subject_count", sa.Integer()),
        sa.Column("language", sa.String(50)),
        sa.Column("expected_site_count", sa.Integer()),
        sa.Column("construction_period", sa.String(100)),
        sa.Column("planned_start_date", sa.Date()),
        sa.Column("planned_end_date", sa.Date()),
        sa.Column("actual_start_date", sa.Date()),
        sa.Column("actual_end_date", sa.Date()),
        sa.Column("study_currency", sa.String(3)),
        sa.Column("exchange_date", sa.Date()),
        sa.Column("query_expected_days", sa.Integer()),
    )
    for column in columns:
        op.add_column("ctms_operational_studies", column)
    op.create_check_constraint(
        "ck_ctms_operational_studies_expected_subject_count",
        "ctms_operational_studies",
        "expected_subject_count IS NULL OR expected_subject_count >= 0",
    )
    op.create_check_constraint(
        "ck_ctms_operational_studies_expected_site_count",
        "ctms_operational_studies",
        "expected_site_count IS NULL OR expected_site_count >= 0",
    )
    op.create_check_constraint(
        "ck_ctms_operational_studies_query_expected_days",
        "ctms_operational_studies",
        "query_expected_days IS NULL OR query_expected_days >= 0",
    )
    op.create_check_constraint(
        "ck_ctms_operational_studies_planned_dates",
        "ctms_operational_studies",
        "planned_start_date IS NULL OR planned_end_date IS NULL OR planned_end_date >= planned_start_date",
    )
    op.create_check_constraint(
        "ck_ctms_operational_studies_actual_dates",
        "ctms_operational_studies",
        "actual_start_date IS NULL OR actual_end_date IS NULL OR actual_end_date >= actual_start_date",
    )

    op.create_table(
        "ctms_managed_entities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("canonical_site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("entity_type", "code", name="uq_ctms_managed_entities_type_code"),
        sa.UniqueConstraint("canonical_site_id", name="uq_ctms_managed_entities_canonical_site"),
        sa.CheckConstraint(
            "entity_type IN ('country','site','depot','staff','participating_organization','investigational_product')",
            name="ck_ctms_managed_entities_type",
        ),
    )
    op.create_index(
        "ix_ctms_managed_entities_type_active",
        "ctms_managed_entities",
        ["entity_type", "active"],
    )
    op.create_table(
        "ctms_study_entity_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity_id", sa.Uuid(), sa.ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("study_id", "entity_id", name="uq_ctms_study_entity_assignment"),
    )
    op.create_index(
        "ix_ctms_study_entity_assignments_study",
        "ctms_study_entity_assignments",
        ["study_id", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ctms_study_entity_assignments_study", table_name="ctms_study_entity_assignments")
    op.drop_table("ctms_study_entity_assignments")
    op.drop_index("ix_ctms_managed_entities_type_active", table_name="ctms_managed_entities")
    op.drop_table("ctms_managed_entities")
    for constraint in (
        "ck_ctms_operational_studies_actual_dates",
        "ck_ctms_operational_studies_planned_dates",
        "ck_ctms_operational_studies_query_expected_days",
        "ck_ctms_operational_studies_expected_site_count",
        "ck_ctms_operational_studies_expected_subject_count",
    ):
        op.drop_constraint(constraint, "ctms_operational_studies", type_="check")
    for column in (
        "query_expected_days", "exchange_date", "study_currency", "actual_end_date",
        "actual_start_date", "planned_end_date", "planned_start_date", "construction_period",
        "expected_site_count", "language", "expected_subject_count", "randomized",
        "blind_method", "investigational_product", "study_description", "program",
        "main_purpose", "study_type",
    ):
        op.drop_column("ctms_operational_studies", column)
