"""Project Platform-managed role definitions into EDC.

Revision ID: 0074
Revises: 0073
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "roles",
        sa.Column("platform_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("roles", sa.Column("platform_revision", sa.BigInteger(), nullable=True))
    op.add_column("roles", sa.Column("platform_status", sa.String(length=16), nullable=True))
    op.execute(
        sa.text(
            "UPDATE roles SET platform_managed = true, platform_status = 'active' "
            "WHERE EXISTS (SELECT 1 FROM user_roles ur "
            "WHERE ur.role_id = roles.id AND ur.platform_managed = true)"
        )
    )


def downgrade() -> None:
    op.drop_column("roles", "platform_status")
    op.drop_column("roles", "platform_revision")
    op.drop_column("roles", "platform_managed")
