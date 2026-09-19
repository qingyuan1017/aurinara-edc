"""Add module ownership metadata and the CTMS transaction outbox.

The shared tables remain shared infrastructure. These additive columns identify
which module owns content; they do not copy or transfer EDC clinical records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON()

    op.add_column(
        "audit_events",
        sa.Column("module", sa.String(20), nullable=False, server_default="EDC"),
    )
    op.add_column(
        "audit_events",
        sa.Column("actor_kind", sa.String(20), nullable=False, server_default="user"),
    )
    op.add_column("audit_events", sa.Column("worker_id", sa.String(128), nullable=True))
    op.add_column("audit_events", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.add_column("audit_events", sa.Column("scope_json", json_type, nullable=True))
    op.add_column("audit_events", sa.Column("changed_fields", json_type, nullable=True))
    op.add_column("audit_events", sa.Column("source_module", sa.String(20), nullable=True))
    op.add_column("audit_events", sa.Column("target_module", sa.String(20), nullable=True))
    op.add_column("audit_events", sa.Column("source_record_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("target_record_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_audit_events_module_correlation", "audit_events", ["module", "correlation_id"]
    )

    op.add_column(
        "notifications",
        sa.Column("module", sa.String(20), nullable=False, server_default="EDC"),
    )
    op.add_column("notifications", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.add_column("notifications", sa.Column("study_id", sa.Uuid(), nullable=True))
    op.add_column("notifications", sa.Column("site_id", sa.Uuid(), nullable=True))
    op.create_index("ix_notifications_correlation_id", "notifications", ["correlation_id"])
    op.create_index("ix_notifications_study_id", "notifications", ["study_id"])
    op.create_index("ix_notifications_site_id", "notifications", ["site_id"])

    op.add_column(
        "exports",
        sa.Column("module", sa.String(20), nullable=False, server_default="EDC"),
    )
    op.add_column(
        "exports",
        sa.Column("content_owner", sa.String(20), nullable=False, server_default="EDC"),
    )
    op.add_column("exports", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.create_index("ix_exports_module_owner", "exports", ["module", "content_owner"])

    op.add_column(
        "file_attachments",
        sa.Column("module", sa.String(20), nullable=False, server_default="EDC"),
    )
    op.add_column(
        "file_attachments",
        sa.Column(
            "attachment_type",
            sa.String(40),
            nullable=False,
            server_default="Clinical_Attachment",
        ),
    )
    op.add_column("file_attachments", sa.Column("retention_until", sa.DateTime(timezone=True)))
    op.add_column("file_attachments", sa.Column("restored_at", sa.DateTime(timezone=True)))
    op.add_column("file_attachments", sa.Column("restored_by", sa.Uuid(), nullable=True))
    op.create_index("ix_file_attachments_module_type", "file_attachments", ["module", "attachment_type"])

    op.create_table(
        "ctms_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("module", sa.String(20), nullable=False, server_default="CTMS"),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("payload_json", json_type, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_category", sa.String(100)),
    )
    op.create_index("ix_ctms_outbox_status_available", "ctms_outbox", ["status", "available_at"])
    op.create_index("ix_ctms_outbox_correlation", "ctms_outbox", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_ctms_outbox_correlation", table_name="ctms_outbox")
    op.drop_index("ix_ctms_outbox_status_available", table_name="ctms_outbox")
    op.drop_table("ctms_outbox")

    op.drop_index("ix_file_attachments_module_type", table_name="file_attachments")
    for name in ("restored_by", "restored_at", "retention_until", "attachment_type", "module"):
        op.drop_column("file_attachments", name)

    op.drop_index("ix_exports_module_owner", table_name="exports")
    op.drop_column("exports", "correlation_id")
    op.drop_column("exports", "content_owner")
    op.drop_column("exports", "module")

    for name in ("site_id", "study_id", "correlation_id", "module"):
        op.drop_index(f"ix_notifications_{name}", table_name="notifications")
    op.drop_column("notifications", "site_id")
    op.drop_column("notifications", "study_id")
    op.drop_column("notifications", "correlation_id")
    op.drop_column("notifications", "module")

    op.drop_index("ix_audit_events_module_correlation", table_name="audit_events")
    for name in (
        "target_record_id",
        "source_record_id",
        "target_module",
        "source_module",
        "changed_fields",
        "scope_json",
        "correlation_id",
        "worker_id",
        "actor_kind",
        "module",
    ):
        op.drop_column("audit_events", name)
