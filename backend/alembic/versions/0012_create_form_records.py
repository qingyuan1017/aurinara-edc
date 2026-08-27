"""Create form_records table.

Revision ID: 0012
Revises: 0010
Create Date: 2024-01-12 00:00:00.000000

Repeating records within a form instance — each record is identified by a
monotonically assigned sequence number per form_instance. Supports soft-delete
with actor, timestamp, and reason for regulatory traceability.

Requirements:
  - 11.1: Add record with monotonic sequence number.
  - 11.3: Soft-delete with actor, timestamp, reason; row retained.
  - 22.2: Soft-delete retention (no physical removal).
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "form_instance_id",
            sa.Uuid(),
            sa.ForeignKey("form_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sequence_number",
            sa.Integer(),
            nullable=False,
            comment="Monotonically assigned per form_instance (not globally unique)",
        ),
        sa.Column(
            "data_jsonb",
            JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Row field values stored as JSON",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft-delete timestamp",
        ),
        sa.Column(
            "deleted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Actor who performed the soft-delete",
        ),
        sa.Column(
            "deletion_reason",
            sa.Text(),
            nullable=True,
            comment="Reason for soft-deletion",
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
    )
    op.create_index(
        "ix_form_records_form_instance_id", "form_records", ["form_instance_id"]
    )
    op.create_index(
        "ix_form_records_form_instance_sequence",
        "form_records",
        ["form_instance_id", "sequence_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_form_records_form_instance_sequence", table_name="form_records"
    )
    op.drop_index(
        "ix_form_records_form_instance_id", table_name="form_records"
    )
    op.drop_table("form_records")
