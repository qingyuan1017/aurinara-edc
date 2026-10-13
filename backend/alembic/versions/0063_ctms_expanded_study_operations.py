"""Add expanded CTMS Study Operations records.

Revision ID: 0063
Revises: 0062
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_study_operation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("record_subtype", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="Draft"),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "details_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("retention_state", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("retention_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "resource_type IN ('contract','pricing_template','payment','ract','kri','monitoring_issue','protocol_deviation','icf','tracking_log')",
            name="ck_ctms_study_operation_resource_type",
        ),
        sa.ForeignKeyConstraint(["archived_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ctms_study_operation_resource_status",
        "ctms_study_operation_records",
        ["study_id", "resource_type", "status"],
    )
    op.create_index(
        "ix_ctms_study_operation_site_resource",
        "ctms_study_operation_records",
        ["site_id", "resource_type"],
    )
    op.create_index(
        "ix_ctms_study_operation_owner_due",
        "ctms_study_operation_records",
        ["owner_id", "end_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ctms_study_operation_owner_due", table_name="ctms_study_operation_records")
    op.drop_index(
        "ix_ctms_study_operation_site_resource", table_name="ctms_study_operation_records"
    )
    op.drop_index(
        "ix_ctms_study_operation_resource_status", table_name="ctms_study_operation_records"
    )
    op.drop_table("ctms_study_operation_records")
