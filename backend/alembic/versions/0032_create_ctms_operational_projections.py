"""Create minimized CTMS operational projection read models."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_operational_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("projection_type", sa.String(60), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("visit_instance_id", sa.Uuid(), nullable=True),
        sa.Column("query_id", sa.Uuid(), nullable=True),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("rejected_fields_fingerprint", sa.String(64), nullable=True),
        sa.Column("rejection_reason", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="current"),
        sa.Column("rebuild_generation", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "projection_type",
            "source_module",
            "source_record_id",
            name="uq_ctms_operational_projections_source",
        ),
        sa.CheckConstraint(
            "source_module IN ('EDC', 'CTMS')",
            name="ck_ctms_operational_projections_source_module",
        ),
        sa.CheckConstraint(
            "status IN ('current', 'stale', 'rejected', 'archived')",
            name="ck_ctms_operational_projections_status",
        ),
    )
    op.create_index(
        "ix_ctms_operational_projections_scope_status",
        "ctms_operational_projections",
        ["study_id", "site_id", "status"],
    )
    op.create_index(
        "ix_ctms_operational_projections_source_version",
        "ctms_operational_projections",
        ["source_module", "source_record_id", "source_version"],
    )
    op.create_index(
        "ix_ctms_operational_projections_projected_at",
        "ctms_operational_projections",
        ["projected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ctms_operational_projections_projected_at",
        table_name="ctms_operational_projections",
    )
    op.drop_index(
        "ix_ctms_operational_projections_source_version",
        table_name="ctms_operational_projections",
    )
    op.drop_index(
        "ix_ctms_operational_projections_scope_status",
        table_name="ctms_operational_projections",
    )
    op.drop_table("ctms_operational_projections")
