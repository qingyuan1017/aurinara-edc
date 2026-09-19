"""Add the query role assignment used by workflow notifications.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import Column, String

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "queries",
        Column(
            "assigned_role",
            String(length=100),
            nullable=True,
            comment="Role whose in-scope active users receive assignment notifications",
        ),
    )


def downgrade() -> None:
    op.drop_column("queries", "assigned_role")
