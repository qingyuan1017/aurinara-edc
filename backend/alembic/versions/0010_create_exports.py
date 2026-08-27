"""Create exports table.

Revision ID: 0010
Revises: 0009
Create Date: 2024-01-10 00:00:00.000000

Tracks export job lifecycle: Queued → Running → Completed/Failed.
Stores filter parameters as JSON and resulting file metadata.

Requirements:
  - 19.1: Export job creation and status tracking.
  - 19.2: Subject list export.
  - 19.3: Filter parameters (site, subject, visit, form, domain, date_range,
           changed_since, locked_only, clean_only).
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "export_type",
            sa.String(30),
            nullable=False,
            server_default="csv",
            comment="Export format: csv, subject_list, etc.",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="Queued",
        ),
        sa.Column(
            "filters",
            JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
            comment="Filter params: site, subject, visit, form, domain, date_range, changed_since, locked_only, clean_only",
        ),
        sa.Column(
            "file_path",
            sa.Text(),
            nullable=True,
            comment="Path/key to the generated file (S3 or local)",
        ),
        sa.Column(
            "file_size",
            sa.BigInteger(),
            nullable=True,
            comment="File size in bytes",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Error message set on failure",
        ),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_exports_study_id", "exports", ["study_id"])
    op.create_index("ix_exports_status", "exports", ["status"])
    op.create_index("ix_exports_requested_by", "exports", ["requested_by"])


def downgrade() -> None:
    op.drop_index("ix_exports_requested_by", table_name="exports")
    op.drop_index("ix_exports_status", table_name="exports")
    op.drop_index("ix_exports_study_id", table_name="exports")
    op.drop_table("exports")
