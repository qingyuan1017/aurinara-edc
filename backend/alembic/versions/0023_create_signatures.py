"""Create signatures table.

Revision ID: 0023
Revises: 0022

Requirements:
  - 17.2: Persist signer identity, timestamp, meaning, signed-object
    reference, and a hash of the signed data.
  - 17.3: Store valid/stale state and the stale reason.
  - 22.4: Store timestamps as timezone-aware UTC values.
  - 22.6: Use UUID keys and indexes for common signature queries.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signatures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "object_type",
            sa.String(20),
            nullable=False,
            comment="Signed object type: field, form, visit, subject, site, or study",
        ),
        sa.Column(
            "object_id",
            sa.Uuid(),
            nullable=False,
            comment="ID of the signed object",
        ),
        sa.Column(
            "signed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            comment="User who re-authenticated and recorded the signature",
        ),
        sa.Column(
            "signed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp at which the signature was recorded",
        ),
        sa.Column(
            "signature_meaning",
            sa.Text(),
            nullable=False,
            comment="Meaning or attestation represented by the signature",
        ),
        sa.Column(
            "data_hash",
            sa.String(128),
            nullable=False,
            comment="Hash of the signed data snapshot",
        ),
        sa.Column(
            "status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'valid'"),
            comment="One of: valid, stale",
        ),
        sa.Column(
            "stale_reason",
            sa.Text(),
            nullable=True,
            comment="Reason the signed data no longer matches the data hash",
        ),
    )
    op.create_index(
        "ix_signatures_object_type_object_id",
        "signatures",
        ["object_type", "object_id"],
    )
    op.create_index("ix_signatures_signed_by", "signatures", ["signed_by"])
    op.create_index("ix_signatures_status", "signatures", ["status"])
    op.create_index("ix_signatures_signed_at", "signatures", ["signed_at"])


def downgrade() -> None:
    op.drop_index("ix_signatures_signed_at", table_name="signatures")
    op.drop_index("ix_signatures_status", table_name="signatures")
    op.drop_index("ix_signatures_signed_by", table_name="signatures")
    op.drop_index(
        "ix_signatures_object_type_object_id",
        table_name="signatures",
    )
    op.drop_table("signatures")
