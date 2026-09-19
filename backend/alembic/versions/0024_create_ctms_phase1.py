"""Add phase-gated CTMS Phase 1 operational tables.

This revision is additive.  CTMS stores operational records in ``ctms_*``
tables and references canonical EDC identities; it never creates a competing
study, site, subject, visit, form, query, or clinical export table.

The optional PostgreSQL setting ``app.ctms_phase`` is a deployment gate.  When
set, it must be at least 1.  An unset setting preserves local/offline migration
compatibility while allowing production provisioning to gate the revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_EDC_TABLES = ("users", "studies", "sites", "subjects")
_CTMS_TABLES = (
    "ctms_operational_studies",
    "ctms_study_plans",
    "ctms_operational_sites",
    "ctms_activation_actions",
    "ctms_enrollment_targets",
    "ctms_operational_milestones",
    "ctms_tasks",
    "ctms_contacts",
    "ctms_status_history",
)


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Reject a deployment that has not enabled the requested CTMS phase."""

    # ``current_setting(..., true)`` returns NULL when the optional setting is
    # not provisioned.  This keeps local development and offline SQL generation
    # usable while production can set app.ctms_phase=0 to block the revision.
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                DO $$
                DECLARE configured_phase text;
                BEGIN
                    configured_phase := current_setting('app.ctms_phase', true);
                    IF configured_phase IS NOT NULL
                       AND configured_phase <> ''
                       AND configured_phase::integer < 1 THEN
                        RAISE EXCEPTION
                            'CTMS Phase 1 migration is disabled by app.ctms_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_edc_dependencies(bind: sa.Connection) -> None:
    """Fail early rather than creating CTMS references without EDC authority."""

    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [name for name in _REQUIRED_EDC_TABLES if not inspect(bind).has_table(name)]
        if missing:
            raise RuntimeError(
                "CTMS Phase 1 requires canonical EDC tables: " + ", ".join(missing)
            )


def _create_site_study_scope_guard() -> None:
    """Ensure separately stored study/site references describe one EDC scope."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ctms_validate_site_study_scope()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.site_id IS NOT NULL AND NEW.study_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM sites WHERE sites.id = NEW.site_id AND sites.study_id = NEW.study_id
            ) THEN
                RAISE EXCEPTION 'CTMS study_id and site_id must belong to one canonical EDC study';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in (
        "ctms_operational_sites",
        "ctms_activation_actions",
        "ctms_enrollment_targets",
        "ctms_operational_milestones",
        "ctms_tasks",
        "ctms_contacts",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_scope_guard
            BEFORE INSERT OR UPDATE OF study_id, site_id ON {table}
            FOR EACH ROW EXECUTE FUNCTION ctms_validate_site_study_scope();
            """
        )


def _create_status_history_guard() -> None:
    """Make status history append-only at the database boundary."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ctms_status_history_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'CTMS status history cannot be modified or deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_status_history_immutable
        BEFORE UPDATE OR DELETE ON ctms_status_history
        FOR EACH ROW EXECUTE FUNCTION prevent_ctms_status_history_modification();
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edc_app') THEN
                REVOKE UPDATE, DELETE ON ctms_status_history FROM edc_app;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_edc_dependencies(bind)

    op.create_table(
        "ctms_operational_studies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operational_owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("sponsor", sa.String(255)),
        sa.Column("phase", sa.String(50)),
        sa.Column("therapeutic_area", sa.String(255)),
        sa.Column("indication", sa.String(255)),
        sa.Column("readiness_criteria", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("retention_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.UniqueConstraint("study_id", name="uq_ctms_operational_studies_study_id"),
        sa.CheckConstraint("status IN ('Draft','Planning','Ready','Active','Enrollment Closed','Suspended','Closed')", name="ck_ctms_operational_studies_status"),
    )
    op.create_index("ix_ctms_operational_studies_status", "ctms_operational_studies", ["status"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_ctms_operational_studies_correlation_id", "ctms_operational_studies", ["correlation_id"])

    op.create_table(
        "ctms_study_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text()),
        sa.Column("planning_scope", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("retention_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint("status IN ('Draft','Active','Completed','Archived')", name="ck_ctms_study_plans_status"),
    )
    op.create_index("ix_ctms_study_plans_study_status", "ctms_study_plans", ["study_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "ctms_operational_sites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("monitoring_readiness", sa.String(30)),
        sa.Column("responsible_role", sa.String(150)),
        sa.Column("planned_activation_date", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="Not Started"),
        sa.Column("retention_state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.UniqueConstraint("site_id", name="uq_ctms_operational_sites_site_id"),
        sa.CheckConstraint("status IN ('Not Started','In Progress','Ready for Activation','Active','Suspended','Closed','Site Archived')", name="ck_ctms_operational_sites_status"),
    )
    op.create_index("ix_ctms_operational_sites_study_site", "ctms_operational_sites", ["study_id", "site_id"])
    op.create_index("ix_ctms_operational_sites_status", "ctms_operational_sites", ["study_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "ctms_activation_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("responsible_role", sa.String(150)),
        sa.Column("responsible_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("planned_date", sa.DateTime(timezone=True)),
        sa.Column("completion_criteria", sa.Text()),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_reference", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False, server_default="Open"),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint("status IN ('Open','In Progress','Completed','Cancelled','Archived')", name="ck_ctms_activation_actions_status"),
    )
    op.create_index("uq_ctms_activation_actions_active", "ctms_activation_actions", ["site_id", "action_type"], unique=True, postgresql_where=sa.text("deleted_at IS NULL AND status NOT IN ('Completed','Cancelled','Archived')"))
    op.create_index("ix_ctms_activation_actions_study_site", "ctms_activation_actions", ["study_id", "site_id"])

    op.create_table(
        "ctms_enrollment_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_quantity", sa.Integer(), nullable=False),
        sa.Column("planning_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planning_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dimension", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint("target_type IN ('Recruitment','Screening','Enrollment')", name="ck_ctms_enrollment_targets_type"),
        sa.CheckConstraint("target_quantity > 0", name="ck_ctms_enrollment_targets_quantity"),
        sa.CheckConstraint("planning_period_end >= planning_period_start", name="ck_ctms_enrollment_targets_period"),
        sa.CheckConstraint("status IN ('Draft','Active','Met','Expired','Cancelled')", name="ck_ctms_enrollment_targets_status"),
    )
    op.create_index("ix_ctms_enrollment_targets_scope_period", "ctms_enrollment_targets", ["study_id", "site_id", "target_type", "planning_period_start", "planning_period_end"], postgresql_where=sa.text("deleted_at IS NULL AND status IN ('Draft','Active')"))
    op.create_index("ix_ctms_enrollment_targets_status", "ctms_enrollment_targets", ["study_id", "status"])

    op.create_table(
        "ctms_operational_milestones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("subject_id", sa.Uuid(), sa.ForeignKey("subjects.id", ondelete="RESTRICT")),
        sa.Column("approved_pseudonym", sa.String(255)),
        sa.Column("milestone_type", sa.String(100), nullable=False),
        sa.Column("milestone_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="Recorded"),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
    )
    op.create_index("ix_ctms_operational_milestones_subject", "ctms_operational_milestones", ["subject_id", "milestone_date"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_ctms_operational_milestones_scope", "ctms_operational_milestones", ["study_id", "site_id", "status"])

    op.create_table(
        "ctms_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.String(20), nullable=False, server_default="Normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="Open"),
        sa.Column("query_id", sa.Uuid(), sa.ForeignKey("queries.id", ondelete="SET NULL")),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint("priority IN ('Low','Normal','High','Urgent')", name="ck_ctms_tasks_priority"),
        sa.CheckConstraint("status IN ('Open','In Progress','Blocked','Completed','Cancelled','Archived')", name="ck_ctms_tasks_status"),
    )
    op.create_index("ix_ctms_tasks_scope_status", "ctms_tasks", ["study_id", "site_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_ctms_tasks_owner_due_date", "ctms_tasks", ["owner_id", "due_date"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "ctms_contacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(150)),
        sa.Column("organization", sa.String(255)),
        sa.Column("channels", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="Active"),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.CheckConstraint("status IN ('Active','Inactive','Archived')", name="ck_ctms_contacts_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from", name="ck_ctms_contacts_effective_period"),
    )
    op.create_index("ix_ctms_contacts_scope_status", "ctms_contacts", ["study_id", "site_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))

    op.create_table(
        "ctms_status_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT")),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("previous_status", sa.String(50)),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reason", sa.Text()),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
    )
    op.create_index("ix_ctms_status_history_entity", "ctms_status_history", ["entity_type", "entity_id", "changed_at"])
    op.create_index("ix_ctms_status_history_scope", "ctms_status_history", ["study_id", "site_id", "changed_at"])

    _create_site_study_scope_guard()
    _create_status_history_guard()


def downgrade() -> None:
    """Drop only CTMS Phase 1 objects, leaving all EDC tables untouched."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        existing = set(inspect(bind).get_table_names())
        missing = [name for name in _CTMS_TABLES if name not in existing]
        if missing:
            raise RuntimeError("Cannot downgrade CTMS Phase 1; missing tables: " + ", ".join(missing))

    op.execute("DROP TRIGGER IF EXISTS ctms_status_history_immutable ON ctms_status_history;")
    op.execute("DROP FUNCTION IF EXISTS prevent_ctms_status_history_modification();")
    for table in (
        "ctms_operational_sites",
        "ctms_activation_actions",
        "ctms_enrollment_targets",
        "ctms_operational_milestones",
        "ctms_tasks",
        "ctms_contacts",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_scope_guard ON {table};")
    op.execute("DROP FUNCTION IF EXISTS ctms_validate_site_study_scope();")

    for table in reversed(_CTMS_TABLES):
        indexes = (
            inspect(bind).get_indexes(table)
            if bind.dialect.name == "postgresql" and not context.is_offline_mode()
            else []
        )
        for index in indexes:
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
