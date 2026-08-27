"""Create queries and query_messages tables.

Revision ID: 0009
Revises: 0008
Create Date: 2024-01-09 00:00:00.000000

Queries target exactly one affected object (target_type + target_id).
Query messages form an append-only thread.

Requirements:
  - 13.1: Query linked to exactly one affected object.
  - 13.6: Complete threaded message history (append-only).
  - 22.6: Indexed for efficient querying.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- queries ---
    op.create_table(
        "queries",
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
            sa.ForeignKey("sites.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("subjects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_type",
            sa.String(30),
            nullable=False,
            comment="One of: Subject, Visit_Instance, Form_Instance, Form_Record, Field",
        ),
        sa.Column(
            "target_id",
            sa.Uuid(),
            nullable=False,
            comment="ID of the affected object",
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "query_type",
            sa.String(10),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="Open",
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
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "closed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_queries_study_id", "queries", ["study_id"])
    op.create_index(
        "ix_queries_target_type_target_id", "queries", ["target_type", "target_id"]
    )
    op.create_index("ix_queries_status", "queries", ["status"])

    # --- query_messages ---
    op.create_table(
        "query_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "query_id",
            sa.Uuid(),
            sa.ForeignKey("queries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_query_messages_query_id", "query_messages", ["query_id"])


def downgrade() -> None:
    op.drop_index("ix_query_messages_query_id", table_name="query_messages")
    op.drop_table("query_messages")

    op.drop_index("ix_queries_status", table_name="queries")
    op.drop_index("ix_queries_target_type_target_id", table_name="queries")
    op.drop_index("ix_queries_study_id", table_name="queries")
    op.drop_table("queries")
