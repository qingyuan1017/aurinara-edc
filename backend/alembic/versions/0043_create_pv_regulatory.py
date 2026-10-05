"""Add phase-gated PV regulatory reporting tables.

Feature: pv-safety-module, Task 4.1

This revision is additive. It creates ``pv_reportability_rules``,
``pv_regulatory_reports``, and ``pv_regulatory_clocks`` that back reportability
evaluation, expedited Regulatory_Clocks, and the Regulatory_Report status state
machine. PV stores these in ``pv_*`` tables and references the PV-owned
``pv_safety_cases`` root; it never creates a competing EDC clinical or CTMS
operational table.

Design ("Regulatory clock and reportability"): reportability evaluation creates
one Pending ``RegulatoryReport`` per matched configured ``ReportabilityRule``
(report type and destination); a report cannot be created without an
Awareness_Date. ``due_date = awareness_date + timedelta(days=timeline_days)``
with ``timeline_days`` constrained to 1-90 inclusive, counting whole calendar
days in UTC where the Awareness_Date is day zero (Requirements 8.1-8.4).

All tables use a UUID primary key, UTC ``TIMESTAMPTZ`` columns, actor/
correlation metadata, and retention/soft-deletion columns. Partial indexes
exclude soft-deleted rows. The Safety_Data tables (reports and clocks) are
registered with the existing PostgreSQL guard that forbids physical deletion of
PV Safety_Data (Requirements 17.1-17.6).

The optional PostgreSQL setting ``app.pv_phase`` is a deployment gate. When set
it must be at least 3 (regulatory reporting is a Phase 3 capability); an unset
setting preserves local/offline migration compatibility while allowing
production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGULATORY_TABLES = (
    "pv_reportability_rules",
    "pv_regulatory_reports",
    "pv_regulatory_clocks",
)

# Regulatory_Reports and Regulatory_Clocks are Safety_Data and may never be
# physically removed; PV applies Soft_Deletion instead (Requirement 17.2).
# Reportability rules are PV configuration and are not gated by the guard.
_PROTECTED_SAFETY_TABLES = (
    "pv_regulatory_reports",
    "pv_regulatory_clocks",
)

_TIMELINE_MIN = 1
_TIMELINE_MAX = 90

_REPORT_STATUS_VALUES = ("Pending", "Submitted", "Acknowledged", "Rejected", "Cancelled")
_REPORT_STATUS_SQL = "','".join(_REPORT_STATUS_VALUES)


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled at least PV Phase 3."""

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
                       AND configured_phase::integer < 3 THEN
                        RAISE EXCEPTION
                            'PV regulatory reporting migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_pv_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating reports without the PV case root."""

    if (
        bind.dialect.name == "postgresql"
        and not context.is_offline_mode()
        and not inspect(bind).has_table("pv_safety_cases")
    ):
        raise RuntimeError(
            "PV regulatory tables require the pv_safety_cases table from revision 0038"
        )


def _register_deletion_guard() -> None:
    """Attach the PV Safety_Data physical-deletion guard to report/clock tables.

    Revision 0038 installs ``prevent_pv_safety_data_deletion``. This revision
    reuses it (creating it defensively if absent) so a report or clock row can
    never be physically deleted; PV uses Soft_Deletion instead (Requirement
    17.2).
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
                    pv_regulatory_reports,
                    pv_regulatory_clocks
                FROM edc_app;
            END IF;
        END $$;
        """
    )


def _common_metadata_columns() -> list[sa.Column]:
    """Return the shared PV metadata columns used by every regulatory table."""

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


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_pv_dependencies(bind)

    op.create_table(
        "pv_reportability_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("report_type", sa.String(100), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("timeline_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            f"timeline_days BETWEEN {_TIMELINE_MIN} AND {_TIMELINE_MAX}",
            name="ck_pv_reportability_rules_timeline_days",
        ),
    )
    op.create_index(
        "ix_pv_reportability_rules_study",
        "pv_reportability_rules",
        ["study_id", "active"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "pv_regulatory_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Uuid(),
            sa.ForeignKey("pv_reportability_rules.id", ondelete="RESTRICT"),
        ),
        sa.Column("report_type", sa.String(100), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Pending"),
        sa.Column("awareness_date", sa.Date(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("e2b_message_ref", sa.String(255)),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            f"status IN ('{_REPORT_STATUS_SQL}')",
            name="ck_pv_regulatory_reports_status",
        ),
    )
    op.create_index(
        "ix_pv_regulatory_reports_case",
        "pv_regulatory_reports",
        ["case_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_pv_regulatory_reports_status",
        "pv_regulatory_reports",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "pv_regulatory_clocks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("pv_regulatory_reports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("awareness_date", sa.Date(), nullable=False),
        sa.Column("timeline_days", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        *_common_metadata_columns(),
        sa.CheckConstraint(
            f"timeline_days BETWEEN {_TIMELINE_MIN} AND {_TIMELINE_MAX}",
            name="ck_pv_regulatory_clocks_timeline_days",
        ),
    )
    op.create_index(
        "uq_pv_regulatory_clocks_report",
        "pv_regulatory_clocks",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    if bind.dialect.name == "postgresql":
        _register_deletion_guard()


def downgrade() -> None:
    """Drop only PV regulatory objects, leaving other tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _REGULATORY_TABLES if name not in existing]
        if missing:
            raise RuntimeError(
                "Cannot downgrade PV regulatory tables; missing: " + ", ".join(missing)
            )

    if bind.dialect.name == "postgresql":
        for table in _PROTECTED_SAFETY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_physical_delete ON {table};")

    for table in reversed(_REGULATORY_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
