"""Add source-version traceability for study amendments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_versions",
        sa.Column(
            "amended_from_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="RESTRICT"),
            nullable=True,
            comment="Published source version for an amendment",
        ),
    )
    op.create_index(
        "ix_study_versions_amended_from_version_id",
        "study_versions",
        ["amended_from_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_study_versions_amended_from_version_id", table_name="study_versions"
    )
    op.drop_column("study_versions", "amended_from_version_id")
