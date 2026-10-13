"""Allow platform authorization projections at system scope.

Revision ID: 0061
Revises: 0060
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "platform_membership_projections",
        "study_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform_membership_projections WHERE study_id IS NULL")
    op.alter_column(
        "platform_membership_projections",
        "study_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
