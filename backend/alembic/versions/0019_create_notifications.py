"""Create notifications table.

Revision ID: 0019
Revises: 0018

Requirements:
  - 28.4: Notification statuses Unread, Read, and Archived.
  - 22.6: UUID primary key and indexes for recipient/status and creation time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="User receiving the notification",
        ),
        sa.Column(
            "type",
            sa.String(100),
            nullable=False,
            comment="Workflow event type, such as query_assigned or export_completed",
        ),
        sa.Column(
            "payload_json",
            JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            comment="Event-specific notification payload",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="Unread",
            comment="One of: Unread, Read, Archived",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_user_status", "notifications", ["user_id", "status"]
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_status", table_name="notifications")
    op.drop_table("notifications")
