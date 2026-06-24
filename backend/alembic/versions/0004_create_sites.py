"""Create sites and study_site_users tables.

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-04 00:00:00.000000

Requirements:
  - 6.1: Site metadata — site number, name, PI, country, region, address, status.
  - 6.2: Site number unique within the study.
  - 6.5: Site-level user assignment.
  - 22.5: Soft-delete via deleted_at column.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- sites ---
    op.create_table(
        "sites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_number",
            sa.String(50),
            nullable=False,
            comment="Unique within the study",
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("principal_investigator", sa.String(255), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
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
        sa.UniqueConstraint("study_id", "site_number", name="uq_study_site_number"),
    )
    op.create_index(
        "ix_sites_study_id_site_number", "sites", ["study_id", "site_number"]
    )
    op.create_index("ix_sites_status", "sites", ["status"])

    # --- study_site_users ---
    op.create_table(
        "study_site_users",
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
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "assigned_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "study_id", "site_id", "user_id", name="uq_study_site_user"
        ),
    )
    op.create_index(
        "ix_study_site_users_study_site_user",
        "study_site_users",
        ["study_id", "site_id", "user_id"],
    )
    op.create_index(
        "ix_study_site_users_user_id", "study_site_users", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_study_site_users_user_id", table_name="study_site_users")
    op.drop_index(
        "ix_study_site_users_study_site_user", table_name="study_site_users"
    )
    op.drop_table("study_site_users")

    op.drop_index("ix_sites_status", table_name="sites")
    op.drop_index("ix_sites_study_id_site_number", table_name="sites")
    op.drop_table("sites")
