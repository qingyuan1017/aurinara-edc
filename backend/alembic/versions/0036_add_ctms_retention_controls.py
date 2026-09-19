"""Add configured CTMS retention metadata and sanitized conflict records.

This revision is additive. Retention jobs update only CTMS-owned rows or the
module discriminator on shared primitives; no EDC clinical row is deleted or
cascaded by this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add(table: str, name: str, column: sa.Column) -> None:
    op.add_column(table, column)


def upgrade() -> None:
    for table in (
        "ctms_operational_projections",
        "ctms_coordination_events",
        "ctms_outbox",
        "exports",
        "notifications",
        "ctms_escalations",
    ):
        _add(table, "retention_state", sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"))
        _add(table, "archived_at", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        _add(table, "archived_by", sa.Column("archived_by", sa.Uuid(), nullable=True))
        _add(table, "retention_reason", sa.Column("retention_reason", sa.Text(), nullable=True))
        _add(table, "deleted_at", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        _add(table, "deleted_by", sa.Column("deleted_by", sa.Uuid(), nullable=True))
        _add(table, "deletion_reason", sa.Column("deletion_reason", sa.Text(), nullable=True))

    _add("file_attachments", "retention_state", sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"))

    for table in ("ctms_event_attempts", "ctms_coordination_event_logs"):
        _add(table, "retention_state", sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"))
        _add(table, "archived_at", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        _add(table, "archived_by", sa.Column("archived_by", sa.Uuid(), nullable=True))
        _add(table, "retention_reason", sa.Column("retention_reason", sa.Text(), nullable=True))

    op.create_index("ix_ctms_projection_retention", "ctms_operational_projections", ["retention_state", "projected_at"])
    op.create_index("ix_ctms_event_attempt_retention", "ctms_event_attempts", ["retention_state", "started_at"])
    op.create_index("ix_ctms_event_log_retention", "ctms_coordination_event_logs", ["retention_state", "completed_at"])
    op.create_index("ix_exports_ctms_retention", "exports", ["module", "retention_state", "created_at"])
    op.create_index("ix_notifications_ctms_retention", "notifications", ["module", "retention_state", "created_at"])
    op.create_index("ix_file_attachments_ctms_retention", "file_attachments", ["module", "retention_state", "uploaded_at"])

    op.create_table(
        "ctms_retention_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("module", sa.String(20), nullable=False, server_default="CTMS"),
    )
    op.create_index("ix_ctms_retention_actions_entity", "ctms_retention_actions", ["entity_type", "entity_id", "occurred_at"])
    op.create_index("ix_ctms_retention_actions_action", "ctms_retention_actions", ["action", "occurred_at"])

    op.create_table(
        "ctms_failed_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("ctms_coordination_events.event_id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(100), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("retention_reason", sa.String(255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("deletion_reason", sa.String(255), nullable=True),
    )
    op.create_index("ix_ctms_failed_events_retention", "ctms_failed_events", ["retention_state", "created_at"])

    op.create_table(
        "ctms_coordination_conflicts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("conflict_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("source_version", sa.String(128), nullable=True),
        sa.Column("current_version", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("retention_reason", sa.String(255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("deletion_reason", sa.String(255), nullable=True),
    )
    op.create_index("ix_ctms_coordination_conflicts_retention", "ctms_coordination_conflicts", ["retention_state", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ctms_coordination_conflicts_retention", table_name="ctms_coordination_conflicts")
    op.drop_table("ctms_coordination_conflicts")
    op.drop_index("ix_ctms_failed_events_retention", table_name="ctms_failed_events")
    op.drop_table("ctms_failed_events")
    op.drop_index("ix_ctms_retention_actions_action", table_name="ctms_retention_actions")
    op.drop_index("ix_ctms_retention_actions_entity", table_name="ctms_retention_actions")
    op.drop_table("ctms_retention_actions")
    for index, table in (
        ("ix_file_attachments_ctms_retention", "file_attachments"),
        ("ix_notifications_ctms_retention", "notifications"),
        ("ix_exports_ctms_retention", "exports"),
        ("ix_ctms_event_log_retention", "ctms_coordination_event_logs"),
        ("ix_ctms_event_attempt_retention", "ctms_event_attempts"),
        ("ix_ctms_projection_retention", "ctms_operational_projections"),
    ):
        op.drop_index(index, table_name=table)
    for table in ("ctms_event_attempts", "ctms_coordination_event_logs"):
        for name in ("retention_reason", "archived_by", "archived_at", "retention_state"):
            op.drop_column(table, name)
    for table in (
        "ctms_escalations", "notifications", "exports", "ctms_outbox",
        "ctms_coordination_events", "ctms_operational_projections",
    ):
        for name in ("deletion_reason", "deleted_by", "deleted_at", "retention_reason", "archived_by", "archived_at", "retention_state"):
            op.drop_column(table, name)
    op.drop_column("file_attachments", "retention_state")
