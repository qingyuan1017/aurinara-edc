"""Retain abandonment metadata for Designer study-version drafts.

Revision ID: 0077
Revises: 0076
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_versions",
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "study_versions",
        sa.Column("abandoned_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "study_versions",
        sa.Column("abandonment_reason", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_study_versions_abandoned_by_users",
        "study_versions",
        "users",
        ["abandoned_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_study_versions_abandoned_by_users",
        "study_versions",
        type_="foreignkey",
    )
    op.drop_column("study_versions", "abandonment_reason")
    op.drop_column("study_versions", "abandoned_by")
    op.drop_column("study_versions", "abandoned_at")
