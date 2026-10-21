"""Remove obsolete local mappings for Platform-owned roles.

Revision ID: 0084
Revises: 0083
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_platform_role_mappings_local_role_id",
        table_name="platform_role_mappings",
    )
    op.drop_table("platform_role_mappings")


def downgrade() -> None:
    op.create_table(
        "platform_role_mappings",
        sa.Column("platform_role_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "local_role_id",
            sa.Uuid(),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_platform_role_mappings_local_role_id",
        "platform_role_mappings",
        ["local_role_id"],
    )
