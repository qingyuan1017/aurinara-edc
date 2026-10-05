"""Add phase-gated PV EDC adverse-event reconciliation tables.

Feature: pv-safety-module, Task 5.2

This revision is additive. It creates ``pv_reconciliation_runs`` and
``pv_reconciliation_discrepancies``, the PV-owned records for one-way, read-only
reconciliation of PV Safety_Cases against the approved, minimized, read-only
``Safety_Operational_Projection`` of EDC adverse events (subject reference,
verbatim term, onset date, seriousness).

Design ("Reconciliation"): ``Reconciliation_Service.run`` compares Safety_Cases
against the projected EDC adverse events for a Study within the acting user's
Authorization_Scope and records one run with the count of matches and
discrepancies (Requirements 10.1, 10.3). Each differing record produces one
``ReconciliationDiscrepancy`` identifying the affected Safety_Case, the EDC
reference, and the differing reconciled fields (Requirement 10.2). Reconciliation
is one-way and read-only; nothing here opens a write path into EDC clinical or
CTMS operational state (Requirement 10.6).

Reconciliation runs and discrepancies are PV Safety_Data: they may not be
physically deleted, so this revision installs the shared PV physical-deletion
guard on both tables (Requirement 17.2). Every table uses a UUID primary key,
UTC ``TIMESTAMPTZ`` columns, actor/correlation metadata, and retention/
soft-deletion columns. Partial indexes exclude soft-deleted rows.

The optional PostgreSQL setting ``app.pv_phase`` is a deployment gate. When set
it must be at least 2 (EDC adverse-event reconciliation is a Phase 2
capability); an unset setting preserves local/offline migration compatibility
while allowing production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECONCILIATION_TABLES = (
    "pv_reconciliation_runs",
    "pv_reconciliation_discrepancies",
)

# Records in these tables are PV Safety_Data and may never be physically
# removed; PV applies Soft_Deletion instead (Requirement 17.2).
_PROTECTED_SAFETY_TABLES = _RECONCILIATION_TABLES

_DISCREPANCY_STATUS_VALUES = ("Open", "Resolved")
_DISCREPANCY_STATUS_SQL = "','".join(_DISCREPANCY_STATUS_VALUES)

_NOT_DELETED = sa.text("deleted_at IS NULL")


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
                            'PV reconciliation migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_pv_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating reconciliation without the PV case root."""

    if (
        bind.dialect.name == "postgresql"
        and not context.is_offline_mode()
        and not inspect(bind).has_table("pv_safety_cases")
    ):
        raise RuntimeError(
            "PV reconciliation tables require the pv_safety_cases table from revision 0038"
        )


def _common_metadata_columns() -> list[sa.Column]:
    """Return the shared PV metadata columns used by every reconciliation table."""

    return [
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
    ]


def _create_safety_data_deletion_guard() -> None:
    """Forbid physical DELETE of the reconciliation Safety_Data tables.

    Revision 0038 defines ``prevent_pv_safety_data_deletion``. This revision
    reuses that function and attaches a BEFORE DELETE trigger to each new table.
    """

    for table in _PROTECTED_SAFETY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_physical_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_pv_safety_data_deletion();
            """
        )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_pv_dependencies(bind)

    op.create_table(
        "pv_reconciliation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            "match_count >= 0",
            name="ck_pv_reconciliation_runs_match_count",
        ),
        sa.CheckConstraint(
            "discrepancy_count >= 0",
            name="ck_pv_reconciliation_runs_discrepancy_count",
        ),
    )
    op.create_index(
        "ix_pv_reconciliation_runs_study",
        "pv_reconciliation_runs",
        ["study_id"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_reconciliation_runs_created_at",
        "pv_reconciliation_runs",
        ["created_at"],
        postgresql_where=_NOT_DELETED,
    )

    op.create_table(
        "pv_reconciliation_discrepancies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("pv_reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("edc_reference", sa.Uuid()),
        sa.Column(
            "differing_fields",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="Open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            f"status IN ('{_DISCREPANCY_STATUS_SQL}')",
            name="ck_pv_reconciliation_discrepancies_status",
        ),
    )
    op.create_index(
        "ix_pv_reconciliation_discrepancies_run",
        "pv_reconciliation_discrepancies",
        ["run_id"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_reconciliation_discrepancies_case",
        "pv_reconciliation_discrepancies",
        ["case_id"],
        postgresql_where=_NOT_DELETED,
    )
    op.create_index(
        "ix_pv_reconciliation_discrepancies_status",
        "pv_reconciliation_discrepancies",
        ["status"],
        postgresql_where=_NOT_DELETED,
    )

    if bind.dialect.name == "postgresql":
        _create_safety_data_deletion_guard()


def downgrade() -> None:
    """Drop only PV reconciliation objects, leaving other tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _RECONCILIATION_TABLES if name not in existing]
        if missing:
            raise RuntimeError(
                "Cannot downgrade PV reconciliation tables; missing: " + ", ".join(missing)
            )
        for table in _PROTECTED_SAFETY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_physical_delete ON {table};")

    for table in reversed(_RECONCILIATION_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
