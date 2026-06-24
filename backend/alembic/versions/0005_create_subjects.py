"""Create subjects table.

Revision ID: 0005
Revises: 0004
Create Date: 2024-01-05 00:00:00.000000

Requirements:
  - 7.1: Subject metadata — bound to a published study version.
  - 7.2: Subject number unique within the study.
  - 22.5: Soft-delete via deleted_at + deleted_by + deletion_reason.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.Uuid(), primary_key=True),
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
            nullable=False,
        ),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Binds the subject to a published study version",
        ),
        sa.Column(
            "subject_number",
            sa.String(100),
            nullable=False,
            comment="Unique within the study",
        ),
        sa.Column(
            "status", sa.String(30), nullable=False, server_default="Screening"
        ),
        sa.Column(
            "created_by",
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
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
        ),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "study_id", "subject_number", name="uq_study_subject_number"
        ),
    )

    # Filter indexes for efficient querying (Requirement 22.6)
    op.create_index(
        "ix_subjects_study_id_subject_number",
        "subjects",
        ["study_id", "subject_number"],
    )
    op.create_index("ix_subjects_site_id", "subjects", ["site_id"])
    op.create_index("ix_subjects_status", "subjects", ["status"])
    op.create_index(
        "ix_subjects_study_version_id", "subjects", ["study_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_subjects_study_version_id", table_name="subjects")
    op.drop_index("ix_subjects_status", table_name="subjects")
    op.drop_index("ix_subjects_site_id", table_name="subjects")
    op.drop_index("ix_subjects_study_id_subject_number", table_name="subjects")
    op.drop_table("subjects")
