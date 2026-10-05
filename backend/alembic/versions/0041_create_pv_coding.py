"""Add PV MedDRA/WHODrug coding tables and dictionary-version registry.

Feature: pv-safety-module, Task 3.2

This revision is additive. It creates the PV-owned coding tables:

  - ``pv_coding_dictionary_versions``  named/versioned dictionaries available to PV
  - ``pv_meddra_codings``              MedDRA coding of an Adverse_Event_Record term
  - ``pv_whodrug_codings``             WHODrug coding of a reported product

Each coding row retains the ``Coding_Dictionary_Version`` string used and the
assigning actor and timestamp. Recoding never mutates a prior assignment: a new
row references the prior one via ``prior_coding_id`` (Requirement 6.5). Every
table uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns, actor/correlation
metadata, and retention/soft-deletion columns. Partial indexes exclude
soft-deleted rows. The coding tables are Safety_Data and are protected from
physical deletion by the shared ``prevent_pv_safety_data_deletion`` guard
installed by revision 0038 (Requirements 17.1-17.6).

The optional PostgreSQL setting ``app.pv_phase`` gates the revision: when set it
must be at least 2 (MedDRA/WHODrug coding are Phase 2 capabilities). An unset
setting preserves local/offline migration compatibility.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_TABLES = ("users", "pv_adverse_event_records")

# Ordered parent -> child so downgrade can drop in reverse safely.
_PV_TABLES = (
    "pv_coding_dictionary_versions",
    "pv_meddra_codings",
    "pv_whodrug_codings",
)

# Coding assignments are Safety_Data and may never be physically removed; PV
# applies Soft_Deletion instead (Requirement 17.2).
_PROTECTED_SAFETY_TABLES = (
    "pv_meddra_codings",
    "pv_whodrug_codings",
)


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled PV Phase 2."""

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
                            'PV coding migration requires app.pv_phase >= 2';
                    END IF;
                END $$;
                """
            )
        )


def _assert_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating coding references without their parents."""

    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [name for name in _REQUIRED_TABLES if not inspect(bind).has_table(name)]
        if missing:
            raise RuntimeError(
                "PV coding tables require: " + ", ".join(missing)
            )


def _install_deletion_guard() -> None:
    """Attach the shared physical-delete guard to the coding Safety_Data tables.

    Reuses the ``prevent_pv_safety_data_deletion`` function installed by revision
    0038; PV deletion is logical (Soft_Deletion) only.
    """

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
                    pv_meddra_codings,
                    pv_whodrug_codings
                FROM edc_app;
            END IF;
        END $$;
        """
    )


def _common_columns() -> list[sa.Column]:
    """Return the shared PV metadata columns for a coding table."""

    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_dependencies(bind)

    not_deleted = sa.text("deleted_at IS NULL")

    op.create_table(
        "pv_coding_dictionary_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("coding_system", sa.String(20), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_common_columns(),
        sa.CheckConstraint(
            "coding_system IN ('MedDRA','WHODrug')",
            name="ck_pv_coding_dictionary_versions_system",
        ),
    )
    op.create_index(
        "uq_pv_coding_dictionary_versions_system_version",
        "pv_coding_dictionary_versions",
        ["coding_system", "version"],
        unique=True,
        postgresql_where=not_deleted,
    )
    op.create_index(
        "ix_pv_coding_dictionary_versions_system",
        "pv_coding_dictionary_versions",
        ["coding_system", "available"],
        postgresql_where=not_deleted,
    )

    op.create_table(
        "pv_meddra_codings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ae_id", sa.Uuid(), sa.ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("prior_coding_id", sa.Uuid(), sa.ForeignKey("pv_meddra_codings.id", ondelete="RESTRICT")),
        sa.Column("term_id", sa.String(100), nullable=False),
        sa.Column("term_label", sa.String(255)),
        sa.Column("dictionary_version", sa.String(50), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        *_common_columns(),
    )
    op.create_index("ix_pv_meddra_codings_ae", "pv_meddra_codings", ["ae_id"], postgresql_where=not_deleted)
    op.create_index("ix_pv_meddra_codings_prior", "pv_meddra_codings", ["prior_coding_id"], postgresql_where=not_deleted)

    op.create_table(
        "pv_whodrug_codings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("prior_coding_id", sa.Uuid(), sa.ForeignKey("pv_whodrug_codings.id", ondelete="RESTRICT")),
        sa.Column("term_id", sa.String(100), nullable=False),
        sa.Column("term_label", sa.String(255)),
        sa.Column("dictionary_version", sa.String(50), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        *_common_columns(),
    )
    op.create_index("ix_pv_whodrug_codings_product", "pv_whodrug_codings", ["product_id"], postgresql_where=not_deleted)
    op.create_index("ix_pv_whodrug_codings_prior", "pv_whodrug_codings", ["prior_coding_id"], postgresql_where=not_deleted)

    if bind.dialect.name == "postgresql":
        _install_deletion_guard()


def downgrade() -> None:
    """Drop only PV coding objects, leaving EDC/CTMS and other PV tables untouched."""

    bind = op.get_bind()

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
