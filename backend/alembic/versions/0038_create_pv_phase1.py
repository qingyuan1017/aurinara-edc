"""Add phase-gated PV_Safety_Module Phase 1 tables and PV permission seeds.

This revision is additive. PV stores safety records in ``pv_*`` tables and
references canonical Study/Site identity and the EDC ``Subject_Reference``; it
never creates a competing study, site, subject, visit, form, query, clinical
export, or CTMS operational table. No PV migration rewrites an EDC clinical or
CTMS operational table.

Phase 1 tables (design "Migration and integrity plan", step 1):
  - ``pv_safety_cases``           globally unique case identifier
  - ``pv_adverse_event_records``  verbatim 1-200, resolution >= onset
  - ``pv_case_versions``          initial=1 / follow-up=max+1, immutable when submitted
  - ``pv_seriousness_assessments``serious requires >= 1 criterion

Every PV table uses a UUID primary key, UTC ``TIMESTAMPTZ`` columns, study/site
scope, actor/correlation metadata, and retention/soft-deletion columns. Partial
indexes exclude soft-deleted rows. Database guards forbid physical deletion of
Safety_Data and Audit_Events (Requirements 17.1-17.6).

The optional PostgreSQL setting ``app.pv_phase`` is a deployment gate. When set
it must be at least 1; an unset setting preserves local/offline migration
compatibility while allowing production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_EDC_TABLES = ("users", "studies", "sites", "subjects", "permissions")

# Ordered parent -> child so downgrade can drop in reverse safely.
_PV_TABLES = (
    "pv_safety_cases",
    "pv_adverse_event_records",
    "pv_case_versions",
    "pv_seriousness_assessments",
)

# Records in these tables are Safety_Data and may never be physically removed;
# PV applies Soft_Deletion instead (Requirement 17.2).
_PROTECTED_SAFETY_TABLES = (
    "pv_safety_cases",
    "pv_adverse_event_records",
    "pv_case_versions",
    "pv_seriousness_assessments",
)

# Phase 1 PV permission seeds (Requirement 17 permission-seed scope; roles are
# bound to these permissions in a later authorization task).
_PV_PERMISSIONS = (
    ("safety_case.enter", "Create and capture PV safety cases and adverse events"),
    ("safety_case.read", "Read PV safety cases and adverse events in scope"),
    ("safety_case.lifecycle", "Transition PV safety case lifecycle and submit versions"),
    ("safety_assessment.record", "Record PV seriousness/causality/expectedness/severity assessments"),
    ("safety_audit.read", "Read the PV safety audit trail in scope"),
)


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled the requested PV phase."""

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
                            'PV Phase 1 migration is disabled by app.pv_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_edc_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating PV references without canonical authority."""

    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [name for name in _REQUIRED_EDC_TABLES if not inspect(bind).has_table(name)]
        if missing:
            raise RuntimeError(
                "PV Phase 1 requires canonical platform tables: " + ", ".join(missing)
            )


def _seed_pv_permissions() -> None:
    """Insert PV permission codes idempotently; never touch EDC/CTMS permissions."""

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.Text()),
    )
    bind = op.get_bind()
    for code, description in _PV_PERMISSIONS:
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
        else:
            existing = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).first()
            if existing is None:
                import uuid

                op.bulk_insert(
                    permissions,
                    [{"id": uuid.uuid4(), "code": code, "description": description}],
                )


def _create_safety_data_deletion_guard() -> None:
    """Forbid physical DELETE of PV Safety_Data at the database boundary.

    PV deletion is logical (Soft_Deletion) only. This guard raises on any DELETE
    against a protected Safety_Data table and revokes DELETE from the app role.
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
                    pv_safety_cases,
                    pv_adverse_event_records,
                    pv_case_versions,
                    pv_seriousness_assessments
                FROM edc_app;
            END IF;
        END $$;
        """
    )


def _assert_audit_events_protected() -> None:
    """Confirm the shared audit trail already forbids physical deletion.

    Revision 0001 installs ``prevent_audit_modification`` on ``audit_events``.
    PV depends on that immutability guard for Audit_Events (Requirement 17.2);
    this migration never weakens it. On PostgreSQL we assert the trigger exists.
    """

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'audit_events_immutable'"
            )
        ).first()
        if exists is None:
            raise RuntimeError(
                "PV Phase 1 requires the immutable audit_events guard from revision 0001"
            )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_edc_dependencies(bind)
    _assert_audit_events_protected()

    op.create_table(
        "pv_safety_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_identifier", sa.String(100), nullable=False),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_reference", sa.Uuid(), sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("case_type", sa.String(100), nullable=False),
        sa.Column("lifecycle_state", sa.String(30), nullable=False, server_default="Open"),
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
        sa.CheckConstraint(
            "lifecycle_state IN ('Open','In Review','Follow-up Required','Ready to Report','Reported','Closed','Reopened')",
            name="ck_pv_safety_cases_lifecycle_state",
        ),
    )
    # Globally unique safety case identifier across the platform (Req 3.2, 17.4).
    op.create_index("uq_pv_safety_cases_case_identifier", "pv_safety_cases", ["case_identifier"], unique=True)
    # Queryable indexes, partial to exclude soft-deleted rows (Req 17.5).
    op.create_index("ix_pv_safety_cases_study", "pv_safety_cases", ["study_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_pv_safety_cases_site", "pv_safety_cases", ["site_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_pv_safety_cases_subject_reference", "pv_safety_cases", ["subject_reference"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_pv_safety_cases_status", "pv_safety_cases", ["study_id", "lifecycle_state"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_pv_safety_cases_created_at", "pv_safety_cases", ["created_at"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "pv_adverse_event_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("verbatim_term", sa.String(200), nullable=False),
        sa.Column("onset_date", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(100), nullable=False),
        sa.Column("resolution_date", sa.Date()),
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
        sa.CheckConstraint("char_length(verbatim_term) BETWEEN 1 AND 200", name="ck_pv_adverse_event_records_verbatim_length"),
        sa.CheckConstraint("resolution_date IS NULL OR resolution_date >= onset_date", name="ck_pv_adverse_event_records_resolution_after_onset"),
    )
    op.create_index("ix_pv_adverse_event_records_case", "pv_adverse_event_records", ["case_id"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "pv_case_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("pv_safety_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("version_kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("captured_content", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
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
        sa.CheckConstraint("version_kind IN ('Initial','Follow-up')", name="ck_pv_case_versions_version_kind"),
        sa.CheckConstraint("status IN ('Draft','Submitted')", name="ck_pv_case_versions_status"),
        sa.CheckConstraint("sequence_number >= 1", name="ck_pv_case_versions_sequence_number"),
        sa.CheckConstraint("reason_for_change IS NULL OR char_length(reason_for_change) <= 4000", name="ck_pv_case_versions_reason_length"),
    )
    op.create_index("uq_pv_case_versions_case_sequence", "pv_case_versions", ["case_id", "sequence_number"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_pv_case_versions_case", "pv_case_versions", ["case_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "pv_seriousness_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ae_id", sa.Uuid(), sa.ForeignKey("pv_adverse_event_records.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("serious", sa.Boolean(), nullable=False),
        sa.Column("criteria", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
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
        # A serious determination requires at least one seriousness criterion (Req 5.1/5.3).
        sa.CheckConstraint("serious = false OR jsonb_array_length(criteria) >= 1", name="ck_pv_seriousness_assessments_serious_requires_criterion"),
    )
    op.create_index("ix_pv_seriousness_assessments_ae", "pv_seriousness_assessments", ["ae_id"], postgresql_where=sa.text("deleted_at IS NULL"))

    _seed_pv_permissions()

    if bind.dialect.name == "postgresql":
        _create_safety_data_deletion_guard()


def downgrade() -> None:
    """Drop only PV Phase 1 objects, leaving EDC/CTMS tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _PV_TABLES if name not in existing]
        if missing:
            raise RuntimeError("Cannot downgrade PV Phase 1; missing tables: " + ", ".join(missing))

    if bind.dialect.name == "postgresql":
        for table in _PROTECTED_SAFETY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_physical_delete ON {table};")
        op.execute("DROP FUNCTION IF EXISTS prevent_pv_safety_data_deletion();")

    # Remove PV permission seeds without disturbing EDC/CTMS permissions.
    for code, _ in _PV_PERMISSIONS:
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))

    for table in reversed(_PV_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
