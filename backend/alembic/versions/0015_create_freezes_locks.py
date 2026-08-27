"""Create freezes_locks table.

Revision ID: 0015
Revises: 0010
Create Date: 2024-01-15 00:00:00.000000

Stores freeze and lock records across the clinical object hierarchy:
field → form → visit → subject → site → study.

Requirements:
  - 16.1: Freeze state on target objects.
  - 16.2: Lock state on target objects.
  - 16.4: Unlock reason recorded; required on unlock.
  - 22.6: Indexed on (object_type, object_id) for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "freezes_locks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "object_type",
            sa.String(20),
            nullable=False,
            comment="One of: field, form, visit, subject, site, study",
        ),
        sa.Column(
            "object_id",
            sa.Uuid(),
            nullable=False,
            comment="ID of the target object",
        ),
        sa.Column(
            "lock_type",
            sa.String(10),
            nullable=False,
            comment="One of: freeze, lock",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="True while the freeze/lock is in effect",
        ),
        sa.Column(
            "locked_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "unlocked_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "unlock_reason",
            sa.Text(),
            nullable=True,
            comment="Required when unlocking (Requirement 16.4)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_freezes_locks_object_type_object_id",
        "freezes_locks",
        ["object_type", "object_id"],
    )
    op.create_index("ix_freezes_locks_lock_type", "freezes_locks", ["lock_type"])
    op.create_index("ix_freezes_locks_is_active", "freezes_locks", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_freezes_locks_is_active", table_name="freezes_locks")
    op.drop_index("ix_freezes_locks_lock_type", table_name="freezes_locks")
    op.drop_index("ix_freezes_locks_object_type_object_id", table_name="freezes_locks")
    op.drop_table("freezes_locks")
