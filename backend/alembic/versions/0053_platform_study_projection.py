"""Add canonical platform study projection metadata.

Revision ID: 0053
Revises: 0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | Sequence[str] | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("platform_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("platform_revision", sa.BigInteger()))
    op.add_column(
        "user_roles",
        sa.Column("platform_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("user_roles", sa.Column("platform_role_id", sa.Uuid()))
    op.add_column("file_attachments", sa.Column("platform_object_id", sa.Uuid()))
    op.create_index(
        "ix_file_attachments_platform_object_id",
        "file_attachments",
        ["platform_object_id"],
    )
    op.add_column("audit_events", sa.Column("authorization_decision_id", sa.Uuid()))
    op.add_column("audit_events", sa.Column("authorization_policy_version", sa.BigInteger()))
    op.add_column(
        "studies",
        sa.Column("platform_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("studies", sa.Column("platform_revision", sa.BigInteger()))
    op.add_column("studies", sa.Column("platform_registry_status", sa.String(16)))
    op.create_table(
        "platform_projection_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_platform_projection_events_aggregate",
        "platform_projection_events",
        ["aggregate_id"],
    )
    op.create_table(
        "platform_membership_projections",
        sa.Column("scope_key", sa.String(160), primary_key=True),
        sa.Column("study_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid()),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "authorization_policy_version")
    op.drop_column("audit_events", "authorization_decision_id")
    op.drop_index("ix_file_attachments_platform_object_id", table_name="file_attachments")
    op.drop_column("file_attachments", "platform_object_id")
    op.drop_table("platform_membership_projections")
    op.drop_index(
        "ix_platform_projection_events_aggregate",
        table_name="platform_projection_events",
    )
    op.drop_table("platform_projection_events")
    op.drop_column("studies", "platform_registry_status")
    op.drop_column("studies", "platform_revision")
    op.drop_column("studies", "platform_managed")
    op.drop_column("users", "platform_revision")
    op.drop_column("users", "platform_managed")
    op.drop_column("user_roles", "platform_role_id")
    op.drop_column("user_roles", "platform_managed")
