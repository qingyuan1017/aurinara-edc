"""Create versioned CTMS status ownership rules.

The table stores policy and typed field declarations only.  It does not copy
EDC clinical records or source payloads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_status_ownership_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("field_path", sa.String(255), nullable=False),
        sa.Column("authoritative_module", sa.String(20), nullable=False),
        sa.Column("writable_module", sa.String(20), nullable=False),
        sa.Column("projection_target", sa.String(20), nullable=True),
        sa.Column("projection_type", sa.String(60), nullable=True),
        sa.Column("allowed_transitions", sa.JSON(), nullable=False),
        sa.Column("allowlist_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_by", sa.Uuid(), nullable=True),
        sa.Column("retirement_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type",
            "field_path",
            "version",
            name="uq_ctms_status_ownership_rules_version",
        ),
        sa.CheckConstraint(
            "authoritative_module IN ('EDC', 'CTMS')",
            name="ck_ctms_status_ownership_authoritative_module",
        ),
        sa.CheckConstraint(
            "writable_module IN ('EDC', 'CTMS')",
            name="ck_ctms_status_ownership_writable_module",
        ),
        sa.CheckConstraint(
            "writable_module = authoritative_module",
            name="ck_ctms_status_ownership_single_writer",
        ),
        sa.CheckConstraint(
            "projection_target IS NULL OR projection_target <> authoritative_module",
            name="ck_ctms_status_ownership_projection_target",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_ctms_status_ownership_status",
        ),
    )
    op.create_index(
        "ix_ctms_status_ownership_rules_lookup",
        "ctms_status_ownership_rules",
        ["entity_type", "field_path", "status", "effective_from"],
    )
    op.create_index(
        "ix_ctms_status_ownership_rules_correlation",
        "ctms_status_ownership_rules",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ctms_status_ownership_rules_correlation",
        table_name="ctms_status_ownership_rules",
    )
    op.drop_index(
        "ix_ctms_status_ownership_rules_lookup",
        table_name="ctms_status_ownership_rules",
    )
    op.drop_table("ctms_status_ownership_rules")
