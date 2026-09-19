"""Create transactional CTMS coordination events, attempts, and immutable logs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ctms_coordination_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("target_module", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("target_record_id", sa.Uuid(), nullable=True),
        sa.Column("target_projection_type", sa.String(60), nullable=True),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("allowlist_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="accepted"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resulting_projection_id", sa.Uuid(), nullable=True),
        sa.Column("current_version", sa.String(128), nullable=True),
        sa.Column("sanitized_reason", sa.String(160), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_ctms_coordination_events_event_id"),
        sa.UniqueConstraint("source_module", "idempotency_key", name="uq_ctms_coordination_event_idempotency"),
        sa.CheckConstraint("source_module IN ('EDC', 'CTMS')", name="ck_ctms_coordination_event_source_module"),
        sa.CheckConstraint("target_module IN ('EDC', 'CTMS')", name="ck_ctms_coordination_event_target_module"),
        sa.CheckConstraint("source_sequence IS NULL OR source_sequence >= 0", name="ck_ctms_coordination_event_source_sequence"),
        sa.CheckConstraint("rule_version > 0", name="ck_ctms_coordination_event_rule_version"),
        sa.CheckConstraint("status IN ('accepted', 'queued', 'processing', 'succeeded', 'skipped', 'retrying', 'failed', 'conflict')", name="ck_ctms_coordination_event_status"),
    )
    op.create_index(
        "ix_ctms_coordination_event_order",
        "ctms_coordination_events",
        ["source_module", "entity_type", "source_record_id", "source_sequence", "source_version"],
    )
    op.create_index("ix_ctms_coordination_event_status", "ctms_coordination_events", ["status", "accepted_at"])
    op.create_index("ix_ctms_coordination_event_correlation", "ctms_coordination_events", ["correlation_id"])

    op.create_table(
        "ctms_event_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("error_category", sa.String(100), nullable=True),
        sa.Column("sanitized_detail", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["event_id"], ["ctms_coordination_events.event_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("event_id", "attempt_number", name="uq_ctms_event_attempt_number"),
    )
    op.create_index("ix_ctms_event_attempt_event", "ctms_event_attempts", ["event_id", "attempt_number"])

    op.create_table(
        "ctms_coordination_event_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("target_module", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("target_projection_id", sa.Uuid(), nullable=True),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.String(128), nullable=False),
        sa.Column("current_version", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("sanitized_reason", sa.String(160), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["event_id"], ["ctms_coordination_events.event_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("event_id", name="uq_ctms_coordination_event_logs_event_id"),
        sa.CheckConstraint("outcome IN ('succeeded', 'skipped', 'retrying', 'failed', 'conflict')", name="ck_ctms_event_log_outcome"),
    )
    op.create_index("ix_ctms_event_log_source", "ctms_coordination_event_logs", ["source_module", "entity_type", "source_record_id", "source_sequence"])
    op.create_index("ix_ctms_event_log_correlation", "ctms_coordination_event_logs", ["correlation_id"])

    for _name, column in (
        ("coordination_event_id", sa.Column("coordination_event_id", sa.Uuid(), nullable=True)),
        ("target_record_id", sa.Column("target_record_id", sa.Uuid(), nullable=True)),
        ("target_projection_type", sa.Column("target_projection_type", sa.String(60), nullable=True)),
        ("allowlist_json", sa.Column("allowlist_json", sa.JSON(), nullable=False, server_default="{}")),
        ("payload_fingerprint", sa.Column("payload_fingerprint", sa.String(64), nullable=True)),
        ("sanitized_reason", sa.Column("sanitized_reason", sa.String(160), nullable=True)),
    ):
        op.add_column("ctms_outbox", column)
    op.create_unique_constraint("uq_ctms_outbox_coordination_event_id", "ctms_outbox", ["coordination_event_id"])

    # PostgreSQL enforces the same completed-log immutability as the ORM event
    # listeners.  The trigger is intentionally scoped to completed rows only.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ctms_reject_completed_event_log_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.completed_at IS NOT NULL THEN
                RAISE EXCEPTION 'completed coordination event logs are immutable';
            END IF;
            RETURN OLD;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_coordination_event_logs_no_update
        BEFORE UPDATE ON ctms_coordination_event_logs
        FOR EACH ROW EXECUTE FUNCTION ctms_reject_completed_event_log_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_coordination_event_logs_no_delete
        BEFORE DELETE ON ctms_coordination_event_logs
        FOR EACH ROW EXECUTE FUNCTION ctms_reject_completed_event_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ctms_coordination_event_logs_no_delete ON ctms_coordination_event_logs")
    op.execute("DROP TRIGGER IF EXISTS ctms_coordination_event_logs_no_update ON ctms_coordination_event_logs")
    op.execute("DROP FUNCTION IF EXISTS ctms_reject_completed_event_log_mutation()")
    op.drop_constraint("uq_ctms_outbox_coordination_event_id", "ctms_outbox", type_="unique")
    for name in (
        "sanitized_reason",
        "payload_fingerprint",
        "allowlist_json",
        "target_projection_type",
        "target_record_id",
        "coordination_event_id",
    ):
        op.drop_column("ctms_outbox", name)
    op.drop_index("ix_ctms_event_log_correlation", table_name="ctms_coordination_event_logs")
    op.drop_index("ix_ctms_event_log_source", table_name="ctms_coordination_event_logs")
    op.drop_table("ctms_coordination_event_logs")
    op.drop_index("ix_ctms_event_attempt_event", table_name="ctms_event_attempts")
    op.drop_table("ctms_event_attempts")
    op.drop_index("ix_ctms_coordination_event_correlation", table_name="ctms_coordination_events")
    op.drop_index("ix_ctms_coordination_event_status", table_name="ctms_coordination_events")
    op.drop_index("ix_ctms_coordination_event_order", table_name="ctms_coordination_events")
    op.drop_table("ctms_coordination_events")
