"""Add phase-gated PV causality, expectedness, and severity assessment tables.

Feature: pv-safety-module, Task 3.1

This revision is additive. It extends the PV assessment persistence beyond the
Phase 1 ``pv_seriousness_assessments`` table with:

  - ``pv_causality_assessments``     suspect product, causality category, and
    the assessing actor and timestamp
  - ``pv_expectedness_assessments``  expected/unexpected against referenced
    safety information
  - ``pv_severity_grades``           configured severity classification

Every table references a PV ``Adverse_Event_Record`` and is PV-owned
Safety_Data. It never creates a competing EDC clinical or CTMS operational
table and never rewrites one. Each table uses a UUID primary key, UTC
``TIMESTAMPTZ`` columns, actor/correlation metadata, and retention/soft-deletion
columns. Partial indexes exclude soft-deleted rows. Records are Safety_Data and
may never be physically deleted; the database guard forbids physical DELETE and
revokes DELETE from the app role.

The optional PostgreSQL setting ``app.pv_phase`` gates the revision: when set it
must be at least 2 (causality/expectedness/severity are Phase 2 capabilities).
An unset setting preserves local/offline migration compatibility.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_PV_TABLES = ("pv_adverse_event_records",)

# Ordered so downgrade can drop safely.
_PV_TABLES = (
    "pv_causality_assessments",
    "pv_expectedness_assessments",
    "pv_severity_grades",
)

# Records in these tables are Safety_Data and may never be physically removed.
_PROTECTED_SAFETY_TABLES = _PV_TABLES


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
                            'PV causality/expectedness/severity migration requires app.pv_phase >= 2';
                    END IF;
                END $$;
                """
            )
        )


def _assert_pv_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating assessment references without their parent."""

    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [
            name for name in _REQUIRED_PV_TABLES if not inspect(bind).has_table(name)
        ]
        if missing:
            raise RuntimeError(
                "PV assessments require the Phase 1 PV tables: " + ", ".join(missing)
            )


def _create_safety_data_deletion_guard() -> None:
    """Forbid physical DELETE of the new PV Safety_Data at the database boundary.

    Reuses the ``prevent_pv_safety_data_deletion`` function installed by revision
    0038; PV deletion is logical (Soft_Deletion) only.
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
                    pv_causality_assessments,
                    pv_expectedness_assessments,
                    pv_severity_grades
                FROM edc_app;
            END IF;
        END $$;
        """
    )


def _common_metadata_columns() -> list[sa.Column]:
    """Return the shared PV record metadata columns (mirrors app.models.pv.common)."""

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
        "pv_causality_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ae_id",
            sa.Uuid(),
            sa.ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("suspect_product", sa.String(200), nullable=False),
        sa.Column("causality_category", sa.String(100), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        *_common_metadata_columns(),
    )
    op.create_index(
        "ix_pv_causality_assessments_ae",
        "pv_causality_assessments",
        ["ae_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "pv_expectedness_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ae_id",
            sa.Uuid(),
            sa.ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected", sa.Boolean(), nullable=False),
        sa.Column("reference_safety_information", sa.Text()),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        *_common_metadata_columns(),
    )
    op.create_index(
        "ix_pv_expectedness_assessments_ae",
        "pv_expectedness_assessments",
        ["ae_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "pv_severity_grades",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ae_id",
            sa.Uuid(),
            sa.ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("grade", sa.String(100), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        *_common_metadata_columns(),
    )
    op.create_index(
        "ix_pv_severity_grades_ae",
        "pv_severity_grades",
        ["ae_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    if bind.dialect.name == "postgresql":
        _create_safety_data_deletion_guard()


def downgrade() -> None:
    """Drop only the new PV assessment objects, leaving other tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _PV_TABLES if name not in existing]
        if missing:
            raise RuntimeError(
                "Cannot downgrade PV assessments; missing tables: " + ", ".join(missing)
            )

    if bind.dialect.name == "postgresql":
        for table in _PROTECTED_SAFETY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_physical_delete ON {table};")
        # The shared prevent_pv_safety_data_deletion function is still used by the
        # Phase 1 tables (revision 0038); it is intentionally left in place.

    for table in reversed(_PV_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
