"""Create file_attachments table.

Revision ID: 0018
Revises: 0017
Create Date: 2024-01-18 00:00:00.000000

Stores metadata for files held in S3 or local object storage.  The parent
clinical object is represented by a polymorphic (object_type, object_id)
pair, while study/site/subject scope columns support authorization and
filtering.  Attachments are soft-deleted for retention and auditability.

Requirements:
  - 27.1: Persist uploaded-file metadata linked to a clinical object.
  - 27.3: Soft-delete attachments without removing the row.
  - 22.6: UUID keys, UTC timestamps, and indexes for common filters.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "object_type",
            sa.String(30),
            nullable=False,
            comment="Parent clinical object type (field, form, visit, subject, site, or study)",
        ),
        sa.Column(
            "object_id",
            sa.Uuid(),
            nullable=False,
            comment="ID of the parent clinical object",
        ),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            sa.Uuid(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "storage_key",
            sa.Text(),
            nullable=False,
            comment="S3 or local object-storage key",
        ),
        sa.Column(
            "uploaded_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deleted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("delete_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_file_attachments_object_type_object_id",
        "file_attachments",
        ["object_type", "object_id"],
    )
    op.create_index("ix_file_attachments_study_id", "file_attachments", ["study_id"])
    op.create_index("ix_file_attachments_site_id", "file_attachments", ["site_id"])
    op.create_index("ix_file_attachments_subject_id", "file_attachments", ["subject_id"])
    op.create_index(
        "ix_file_attachments_uploaded_by", "file_attachments", ["uploaded_by"]
    )
    op.create_index("ix_file_attachments_deleted_at", "file_attachments", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_file_attachments_deleted_at", table_name="file_attachments")
    op.drop_index("ix_file_attachments_uploaded_by", table_name="file_attachments")
    op.drop_index("ix_file_attachments_subject_id", table_name="file_attachments")
    op.drop_index("ix_file_attachments_site_id", table_name="file_attachments")
    op.drop_index("ix_file_attachments_study_id", table_name="file_attachments")
    op.drop_index(
        "ix_file_attachments_object_type_object_id", table_name="file_attachments"
    )
    op.drop_table("file_attachments")
