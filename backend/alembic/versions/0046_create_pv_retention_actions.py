"""Add the PV retention lifecycle ledger (``pv_retention_actions``).

This revision is additive. PV retention jobs update only PV-owned/shared
metadata and append an immutable actor/time/reason ledger row; no EDC clinical
or CTMS operational row is deleted or cascaded by this revision, and no PV
Safety_Data is physically removed (Requirements 17.2, 17.3, 20.3, 20.5).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEDGER_TABLE = "pv_retention_actions"


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled at least PV Phase 1."""

    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                DO $$
                DECLARE configured_phase text;
                BEGIN
                    configured_phase := current_setting('app.pv_phase', true);
                    IF configured_phase IS NOT NULL
                       AND configured_phase <> ''
                       AND configured_phase::integer < 1 THEN
                        RAISE EXCEPTION
                            'PV retention ledger migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _create_immutability_guard() -> None:
    """Forbid UPDATE/DELETE of PV retention ledger rows at the database boundary."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_pv_retention_action_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'PV retention action history is immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_LEDGER_TABLE}_immutable
        BEFORE UPDATE OR DELETE ON {_LEDGER_TABLE}
        FOR EACH ROW EXECUTE FUNCTION prevent_pv_retention_action_mutation();
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)

    op.create_table(
        _LEDGER_TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("module", sa.String(20), nullable=False, server_default="PV"),
    )
    op.create_index(
        "ix_pv_retention_actions_entity", _LEDGER_TABLE, ["entity_type", "entity_id", "occurred_at"]
    )
    op.create_index("ix_pv_retention_actions_action", _LEDGER_TABLE, ["action", "occurred_at"])

    if bind.dialect.name == "postgresql":
        _create_immutability_guard()


def downgrade() -> None:
    """Drop only the PV retention ledger objects, leaving all else untouched."""

    bind = op.get_bind()
    if (
        bind.dialect.name == "postgresql"
        and not context.is_offline_mode()
        and not inspect(bind).has_table(_LEDGER_TABLE)
    ):
        raise RuntimeError("Cannot downgrade PV retention ledger; table is missing")

    if bind.dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_LEDGER_TABLE}_immutable ON {_LEDGER_TABLE};")
        op.execute("DROP FUNCTION IF EXISTS prevent_pv_retention_action_mutation();")

    op.drop_index("ix_pv_retention_actions_action", table_name=_LEDGER_TABLE)
    op.drop_index("ix_pv_retention_actions_entity", table_name=_LEDGER_TABLE)
    op.drop_table(_LEDGER_TABLE)
