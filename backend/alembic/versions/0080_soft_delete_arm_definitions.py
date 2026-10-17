"""Allow draft arm definitions to be soft-deleted and recreated.

Revision ID: 0080
Revises: 0079
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_arm_definition_name_per_version",
        "arm_definitions",
        type_="unique",
    )
    op.create_index(
        "uq_arm_definition_name_per_version_live",
        "arm_definitions",
        ["study_version_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_arm_definition_name_per_version_live",
        table_name="arm_definitions",
    )
    op.create_unique_constraint(
        "uq_arm_definition_name_per_version",
        "arm_definitions",
        ["study_version_id", "name"],
    )
