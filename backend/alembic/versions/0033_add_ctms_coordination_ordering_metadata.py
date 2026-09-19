"""Add source-order and target-outcome metadata for CTMS coordination."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ctms_operational_projections",
        sa.Column("source_sequence", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_ctms_operational_projections_source_sequence",
        "ctms_operational_projections",
        ["source_module", "source_record_id", "source_sequence"],
    )

    for _name, column in (
        ("source_module", sa.Column("source_module", sa.String(20), nullable=True)),
        ("target_module", sa.Column("target_module", sa.String(20), nullable=True)),
        ("source_record_id", sa.Column("source_record_id", sa.Uuid(), nullable=True)),
        ("source_sequence", sa.Column("source_sequence", sa.Integer(), nullable=True)),
        ("source_version", sa.Column("source_version", sa.String(128), nullable=True)),
        ("rule_version", sa.Column("rule_version", sa.Integer(), nullable=True)),
        ("idempotency_key", sa.Column("idempotency_key", sa.String(255), nullable=True)),
        ("resulting_projection_id", sa.Column("resulting_projection_id", sa.Uuid(), nullable=True)),
        ("current_version", sa.Column("current_version", sa.String(128), nullable=True)),
        ("outcome", sa.Column("outcome", sa.String(30), nullable=True)),
        ("processed_at", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column("ctms_outbox", column)

    op.execute(
        "UPDATE ctms_outbox SET source_module = module, target_module = 'CTMS', "
        "source_record_id = aggregate_id, source_version = payload_json->>'source_version', "
        "rule_version = CASE WHEN (payload_json->>'rule_version') ~ '^[0-9]+$' "
        "THEN (payload_json->>'rule_version')::integer ELSE NULL END"
    )
    op.alter_column("ctms_outbox", "source_module", nullable=False, server_default="CTMS")
    op.alter_column("ctms_outbox", "target_module", nullable=False, server_default="CTMS")
    op.create_index(
        "ix_ctms_outbox_source_order",
        "ctms_outbox",
        ["source_module", "aggregate_type", "source_record_id", "source_sequence", "source_version", "event_id"],
    )
    op.create_index("ix_ctms_outbox_idempotency_key", "ctms_outbox", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ctms_outbox_idempotency_key", table_name="ctms_outbox")
    op.drop_index("ix_ctms_outbox_source_order", table_name="ctms_outbox")
    for name in (
        "processed_at",
        "outcome",
        "current_version",
        "resulting_projection_id",
        "idempotency_key",
        "rule_version",
        "source_version",
        "source_sequence",
        "source_record_id",
        "target_module",
        "source_module",
    ):
        op.drop_column("ctms_outbox", name)
    op.drop_index(
        "ix_ctms_operational_projections_source_sequence",
        table_name="ctms_operational_projections",
    )
    op.drop_column("ctms_operational_projections", "source_sequence")
