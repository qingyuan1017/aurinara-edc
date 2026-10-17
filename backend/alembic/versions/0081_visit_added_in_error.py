"""Add audited added-in-error support for user-added visits.

Revision ID: 0081
Revises: 0080
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | Sequence[str] | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visit_instances",
        sa.Column(
            "is_user_added",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="True for visit occurrences explicitly added by an EDC user",
        ),
    )
    op.execute(
        """
        UPDATE visit_instances AS instance
           SET is_user_added = true
         WHERE instance.visit_definition_id IS NULL
            OR EXISTS (
                SELECT 1
                  FROM visit_definitions AS definition
                 WHERE definition.id = instance.visit_definition_id
                   AND definition.addable = true
            )
        """
    )


def downgrade() -> None:
    op.drop_column("visit_instances", "is_user_added")
