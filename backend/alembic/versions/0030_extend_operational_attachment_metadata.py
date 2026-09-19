"""Extend shared attachment metadata for CTMS traceability and retention.

This additive revision keeps one shared object-storage metadata table while
making CTMS ownership, correlation, archival, and retention state explicit.
Clinical attachment rows remain EDC-owned and nullable defaults preserve them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_attachments",
        sa.Column("correlation_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "file_attachments",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "file_attachments",
        sa.Column("archived_by", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "file_attachments",
        sa.Column("archive_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_file_attachments_correlation_id", "file_attachments", ["correlation_id"]
    )
    op.create_index(
        "ix_file_attachments_archived_at", "file_attachments", ["archived_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_file_attachments_archived_at", table_name="file_attachments")
    op.drop_index("ix_file_attachments_correlation_id", table_name="file_attachments")
    for name in ("archive_reason", "archived_by", "archived_at", "correlation_id"):
        op.drop_column("file_attachments", name)
