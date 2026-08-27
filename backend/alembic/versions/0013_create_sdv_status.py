"""Create sdv_status table.

Revision ID: 0013
Revises: 0012
Create Date: 2024-01-13 00:00:00.000000

Tracks source data verification status at field/form/visit/subject scope.
Each (scope_type, scope_id) pair has at most one SDV record.

Requirements:
  - 14.1: Persists verified status with actor and timestamp at field/form/visit/subject scope.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdv_status",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scope_type",
            sa.String(20),
            nullable=False,
            comment="Scope level: field, form, visit, or subject",
        ),
        sa.Column(
            "scope_id",
            sa.Uuid(),
            nullable=False,
            comment="ID of the scoped entity",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "verified_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "verified_at",
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
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_sdv_status_scope"),
    )
    op.create_index(
        "ix_sdv_status_scope_type_scope_id", "sdv_status", ["scope_type", "scope_id"]
    )
    op.create_index("ix_sdv_status_verified_by", "sdv_status", ["verified_by"])


def downgrade() -> None:
    op.drop_index("ix_sdv_status_verified_by", table_name="sdv_status")
    op.drop_index("ix_sdv_status_scope_type_scope_id", table_name="sdv_status")
    op.drop_table("sdv_status")
