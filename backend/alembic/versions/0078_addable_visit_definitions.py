"""Allow Designer visits to be instantiated again in EDC.

Revision ID: 0078
Revises: 0077
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visit_definitions",
        sa.Column(
            "addable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Whether EDC users may add another instance of this visit definition",
        ),
    )
    op.create_check_constraint(
        "ck_visit_definitions_addable_real_visit",
        "visit_definitions",
        "NOT addable OR definition_kind IN ('visit', 'cycle_visit')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_visit_definitions_addable_real_visit",
        "visit_definitions",
        type_="check",
    )
    op.drop_column("visit_definitions", "addable")
