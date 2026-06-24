"""Create studies and study_versions tables.

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03 00:00:00.000000

Requirements:
  - 4.1: Study metadata — code, protocol number, title, sponsor, phase,
          therapeutic area, indication, status.
  - 4.2: Globally unique study code.
  - 5.1: Study versions with draft/published lifecycle.
  - 5.5: Each form definition is associated with exactly one Study_Version.
  - 22.1: UUID primary keys.
  - 22.5: Soft-delete via deleted_at column.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- studies ---
    op.create_table(
        "studies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_code",
            sa.String(100),
            nullable=False,
            comment="Globally unique study code",
        ),
        sa.Column("protocol_number", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("sponsor", sa.String(255), nullable=True),
        sa.Column(
            "phase",
            sa.String(50),
            nullable=True,
            comment="e.g. Phase I, Phase II, Phase III, Phase IV",
        ),
        sa.Column("therapeutic_area", sa.String(255), nullable=True),
        sa.Column("indication", sa.String(255), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
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
    )
    op.create_index("ix_studies_study_code", "studies", ["study_code"], unique=True)
    op.create_index("ix_studies_status", "studies", ["status"])

    # --- study_versions ---
    op.create_table(
        "study_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.String(20),
            nullable=False,
            comment="e.g. 1.0, 2.0",
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("amendment_reason", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("study_id", "version_number", name="uq_study_version_number"),
    )
    op.create_index("ix_study_versions_study_id", "study_versions", ["study_id"])
    op.create_index("ix_study_versions_status", "study_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_study_versions_status", table_name="study_versions")
    op.drop_index("ix_study_versions_study_id", table_name="study_versions")
    op.drop_table("study_versions")

    op.drop_index("ix_studies_status", table_name="studies")
    op.drop_index("ix_studies_study_code", table_name="studies")
    op.drop_table("studies")
