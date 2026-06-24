"""Create visit_definitions and visit_instances tables.

Revision ID: 0006
Revises: 0005
Create Date: 2024-01-06 00:00:00.000000

Requirements:
  - 8.1: Visit definitions — name, visit number, visit type, target day, window bounds,
          display order, required flag.
  - 8.2: Visit instances created from a bound study version's visit definitions.
  - 8.3: Visit instances carry a window status.
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visit_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("visit_number", sa.Integer(), nullable=False),
        sa.Column(
            "visit_type",
            sa.String(50),
            nullable=False,
            comment="e.g. scheduled, unscheduled, screening",
        ),
        sa.Column(
            "target_day",
            sa.Integer(),
            nullable=True,
            comment="Day relative to baseline",
        ),
        sa.Column(
            "window_before",
            sa.Integer(),
            nullable=True,
            comment="Days before target",
        ),
        sa.Column(
            "window_after",
            sa.Integer(),
            nullable=True,
            comment="Days after target",
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_visit_definitions_study_version_id",
        "visit_definitions",
        ["study_version_id"],
    )

    op.create_table(
        "visit_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visit_definition_id",
            sa.Uuid(),
            sa.ForeignKey("visit_definitions.id", ondelete="SET NULL"),
            nullable=True,
            comment="Null for unscheduled visits",
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "visit_date",
            sa.Date(),
            nullable=True,
            comment="Recorded when the visit occurs",
        ),
        sa.Column(
            "window_status",
            sa.String(20),
            nullable=True,
            comment="before_window, in_window, after_window",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_visit_instances_subject_id", "visit_instances", ["subject_id"]
    )
    op.create_index("ix_visit_instances_status", "visit_instances", ["status"])


def downgrade() -> None:
    op.drop_index("ix_visit_instances_status", table_name="visit_instances")
    op.drop_index("ix_visit_instances_subject_id", table_name="visit_instances")
    op.drop_table("visit_instances")
    op.drop_index(
        "ix_visit_definitions_study_version_id", table_name="visit_definitions"
    )
    op.drop_table("visit_definitions")
