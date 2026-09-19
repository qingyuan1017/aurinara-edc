"""Persist CTMS projection rebuild generations and source watermarks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_projection_rebuild_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column("projection_type", sa.String(60), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("scope_study_id", sa.Uuid(), nullable=False),
        sa.Column("scope_site_id", sa.Uuid(), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_stale", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watermark_version", sa.String(128), nullable=True),
        sa.Column("watermark_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark_record_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(120), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation", name="uq_ctms_projection_rebuild_generation"),
        sa.CheckConstraint(
            "source_module IN ('EDC', 'CTMS')",
            name="ck_ctms_projection_rebuild_source_module",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_ctms_projection_rebuild_status",
        ),
    )
    op.create_index(
        "ix_ctms_projection_rebuild_scope",
        "ctms_projection_rebuild_states",
        ["scope_study_id", "scope_site_id", "projection_type", "source_module", "started_at"],
    )
    op.create_index(
        "ix_ctms_projection_rebuild_watermark",
        "ctms_projection_rebuild_states",
        ["scope_study_id", "scope_site_id", "watermark_timestamp"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ctms_projection_rebuild_watermark",
        table_name="ctms_projection_rebuild_states",
    )
    op.drop_index(
        "ix_ctms_projection_rebuild_scope",
        table_name="ctms_projection_rebuild_states",
    )
    op.drop_table("ctms_projection_rebuild_states")
