"""Create review_status table.

Revision ID: 0014
Revises: 0010
Create Date: 2024-01-14 00:00:00.000000

Tracks clinical review state per form instance. One row per form_instance
with a unique constraint enforcing at most one review record per form.

Requirements:
  - 15.1: Mark form instances as reviewed with actor/timestamp.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_status",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "form_instance_id",
            sa.Uuid(),
            sa.ForeignKey("form_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "form_instance_id", name="uq_review_status_form_instance_id"
        ),
    )
    op.create_index(
        "ix_review_status_form_instance_id", "review_status", ["form_instance_id"]
    )
    op.create_index(
        "ix_review_status_reviewed_by", "review_status", ["reviewed_by"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_status_reviewed_by", table_name="review_status")
    op.drop_index("ix_review_status_form_instance_id", table_name="review_status")
    op.drop_table("review_status")
