"""Add phase-gated PV Case_Narrative tables.

Feature: pv-safety-module, Task 3.3

This revision is additive. It creates the ``pv_case_narratives`` and
``pv_narrative_versions`` tables that back versioned Case_Narratives. PV stores
narratives in ``pv_*`` tables and references the PV-owned ``pv_safety_cases``
root; it never creates a competing EDC clinical or CTMS operational table.

Design ("Data Models"): a Case_Narrative holds the current narrative text
(non-empty after trim, <= 20,000 characters) for one Safety_Case and retains a
chain of immutable Narrative_Versions. Version 1 is the authoring version and
carries no Reason_For_Change; every revision appends a version with a
Reason_For_Change (non-empty after trim, <= 4,000 characters) and retains all
prior versions (Requirements 7.1, 7.2, 7.3).

Both tables use a UUID primary key, UTC ``TIMESTAMPTZ`` columns, actor/
correlation metadata, and retention/soft-deletion columns. Partial indexes
exclude soft-deleted rows. The tables are registered with the existing
PostgreSQL guard that forbids physical deletion of PV Safety_Data
(Requirements 17.1-17.6).

The optional PostgreSQL setting ``app.pv_phase`` is a deployment gate. When set
it must be at least 2 (case narratives are a Phase 2 capability); an unset
setting preserves local/offline migration compatibility while allowing
production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NARRATIVE_TABLES = (
    "pv_case_narratives",
    "pv_narrative_versions",
)

# Records in these tables are Safety_Data and may never be physically removed;
# PV applies Soft_Deletion instead (Requirement 17.2).
_PROTECTED_SAFETY_TABLES = _NARRATIVE_TABLES

_TEXT_MAX = 20_000
_REASON_MAX = 4_000


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled at least PV Phase 2."""

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
                       AND configured_phase::integer < 2 THEN
                        RAISE EXCEPTION
                            'PV Case_Narrative migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_pv_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating narratives without the PV case root."""

    if (
        bind.dialect.name == "postgresql"
        and not context.is_offline_mode()
        and not inspect(bind).has_table("pv_safety_cases")
    ):
        raise RuntimeError(
            "PV Case_Narrative tables require the pv_safety_cases table from revision 0038"
        )


def _register_deletion_guard() -> None:
    """Attach the existing PV Safety_Data physical-deletion guard to new tables.

    Revision 0038 installs ``prevent_pv_safety_data_deletion``. This revision
    reuses it (creating it defensively if absent) so a narrative row can never
    be physically deleted; PV uses Soft_Deletion instead (Requirement 17.2).
    """

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_pv_safety_data_deletion()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'PV Safety_Data cannot be physically deleted; use Soft_Deletion';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _PROTECTED_SAFETY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_physical_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_pv_safety_data_deletion();
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edc_app') THEN
                REVOKE DELETE ON
                    pv_case_narratives,
                    pv_narrative_versions
                FROM edc_app;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_pv_dependencies(bind)

    op.create_table(
        "pv_case_narratives",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("current_text", sa.Text(), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint(f"char_length(current_text) BETWEEN 1 AND {_TEXT_MAX}", name="ck_pv_case_narratives_text_length"),
        sa.CheckConstraint("current_version_number >= 1", name="ck_pv_case_narratives_version_number"),
    )
    op.create_index("ix_pv_case_narratives_case", "pv_case_narratives", ["case_id"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "pv_narrative_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("narrative_id", sa.Uuid(), sa.ForeignKey("pv_case_narratives.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("text_value", sa.Text(), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authored_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reason_for_change", sa.Text()),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint(f"char_length(text_value) BETWEEN 1 AND {_TEXT_MAX}", name="ck_pv_narrative_versions_text_length"),
        sa.CheckConstraint("version_number >= 1", name="ck_pv_narrative_versions_version_number"),
        sa.CheckConstraint(
            f"reason_for_change IS NULL OR char_length(reason_for_change) BETWEEN 1 AND {_REASON_MAX}",
            name="ck_pv_narrative_versions_reason_length",
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND reason_for_change IS NULL) "
            "OR (version_number > 1 AND reason_for_change IS NOT NULL)",
            name="ck_pv_narrative_versions_reason_presence",
        ),
    )
    op.create_index(
        "uq_pv_narrative_versions_narrative_sequence",
        "pv_narrative_versions",
        ["narrative_id", "version_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_pv_narrative_versions_narrative",
        "pv_narrative_versions",
        ["narrative_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    if bind.dialect.name == "postgresql":
        _register_deletion_guard()


def downgrade() -> None:
    """Drop only PV Case_Narrative objects, leaving other tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _NARRATIVE_TABLES if name not in existing]
        if missing:
            raise RuntimeError(
                "Cannot downgrade PV Case_Narratives; missing tables: " + ", ".join(missing)
            )

    if bind.dialect.name == "postgresql":
        for table in _PROTECTED_SAFETY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_physical_delete ON {table};")

    for table in reversed(_NARRATIVE_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
