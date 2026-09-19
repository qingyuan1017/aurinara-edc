"""Add additive CTMS Phase 2 monitoring persistence.

The revision creates only CTMS-owned monitoring plans, immutable plan versions,
operational activities, and scheduling history.  The optional EDC visit link is
a foreign-key reference to the canonical ``visit_instances`` row; no protocol
visit or clinical-data columns are duplicated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_EDC_TABLES = ("users", "studies", "sites", "visit_instances")
_CTMS_TABLES = (
    "ctms_monitoring_plans",
    "ctms_monitoring_plan_versions",
    "ctms_monitoring_activities",
    "ctms_monitoring_activity_schedule_history",
)


def _assert_phase_gate(bind: sa.Connection) -> None:
    """Allow local migrations while permitting production Phase 2 gating."""

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
                       AND configured_phase::integer < 2 THEN
                        RAISE EXCEPTION
                            'CTMS Phase 2 migration is disabled by app.ctms_phase';
                    END IF;
                END $$;
                """
            )
        )


def _assert_edc_dependencies(bind: sa.Connection) -> None:
    """Never provision CTMS monitoring without canonical EDC references."""

    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [name for name in _REQUIRED_EDC_TABLES if not inspect(bind).has_table(name)]
        if missing:
            raise RuntimeError(
                "CTMS monitoring requires canonical EDC tables: " + ", ".join(missing)
            )


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            sa.Uuid(),
            sa.ForeignKey("sites.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("retention_state", sa.String(30), nullable=False, server_default="active"),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("archived_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("retention_reason", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _create_guards() -> None:
    """Install scope and append-only guards at the database boundary."""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ctms_monitoring_validate_site_study_scope()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.site_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM sites
                WHERE sites.id = NEW.site_id AND sites.study_id = NEW.study_id
            ) THEN
                RAISE EXCEPTION 'CTMS monitoring study_id and site_id must share canonical study';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("ctms_monitoring_plans", "ctms_monitoring_activities"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_scope_guard
            BEFORE INSERT OR UPDATE OF study_id, site_id ON {table}
            FOR EACH ROW EXECUTE FUNCTION ctms_monitoring_validate_site_study_scope();
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ctms_published_monitoring_version_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'Published' THEN
                RAISE EXCEPTION 'Published monitoring plan versions are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_monitoring_plan_versions_immutable
        BEFORE UPDATE OR DELETE ON ctms_monitoring_plan_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_ctms_published_monitoring_version_modification();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ctms_monitoring_history_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'CTMS monitoring activity history cannot be modified or deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_monitoring_schedule_history_immutable
        BEFORE UPDATE OR DELETE ON ctms_monitoring_activity_schedule_history
        FOR EACH ROW EXECUTE FUNCTION prevent_ctms_monitoring_history_modification();
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_edc_dependencies(bind)

    op.create_table(
        "ctms_monitoring_plans",
        *_common_columns(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('Draft','Published','Archived')",
            name="ck_ctms_monitoring_plans_status",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_plans_scope_status",
        "ctms_monitoring_plans",
        ["study_id", "site_id", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_plans_correlation_id",
        "ctms_monitoring_plans",
        ["correlation_id"],
    )

    json_type = sa.JSON()
    op.create_table(
        "ctms_monitoring_plan_versions",
        *_common_columns(),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Draft"),
        sa.Column("objectives", sa.Text()),
        sa.Column("activity_types", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("frequency", sa.String(100)),
        sa.Column("frequency_value", sa.Integer()),
        sa.Column("frequency_unit", sa.String(30)),
        sa.Column("cadence", sa.String(100)),
        sa.Column("responsibilities", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scope", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("completion_criteria", sa.Text()),
        sa.Column("risk_level", sa.String(50)),
        sa.Column("risk_strategy", sa.String(255)),
        sa.Column("monitoring_strategy", sa.String(255)),
        sa.Column("risk_threshold", sa.String(255)),
        sa.Column("thresholds", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("amendment_reason", sa.Text()),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "plan_id", "version_number", name="uq_ctms_monitoring_plan_versions_number"
        ),
        sa.CheckConstraint(
            "status IN ('Draft','Published','Retired')",
            name="ck_ctms_monitoring_plan_versions_status",
        ),
        sa.CheckConstraint("version_number > 0", name="ck_ctms_monitoring_plan_versions_positive"),
    )
    op.create_index(
        "ix_ctms_monitoring_plan_versions_status",
        "ctms_monitoring_plan_versions",
        ["plan_id", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_plan_versions_published_at",
        "ctms_monitoring_plan_versions",
        ["published_at"],
    )
    op.create_index(
        "ix_ctms_monitoring_plan_versions_correlation_id",
        "ctms_monitoring_plan_versions",
        ["correlation_id"],
    )
    op.create_foreign_key(
        "fk_ctms_monitoring_plans_current_version",
        "ctms_monitoring_plans",
        "ctms_monitoring_plan_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ctms_monitoring_activities",
        *_common_columns(),
        sa.Column(
            "plan_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_plan_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(40), nullable=False),
        sa.Column("planned_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_cra_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False, server_default="Planned"),
        sa.Column(
            "edc_visit_instance_id",
            sa.Uuid(),
            sa.ForeignKey("visit_instances.id", ondelete="RESTRICT"),
        ),
        sa.Column("completion_evidence", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("completion_notes", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("cancellation_reason", sa.Text()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("issue_id", sa.Uuid()),
        sa.Column("issue_reference", sa.String(255)),
        sa.Column("escalation_id", sa.Uuid()),
        sa.Column("escalation_reference", sa.String(255)),
        sa.CheckConstraint(
            "activity_type IN ('Site Initiation','Routine Monitoring','Close-out','Remote Review','Triggered Review')",
            name="ck_ctms_monitoring_activities_type",
        ),
        sa.CheckConstraint(
            "status IN ('Planned','Scheduled','In Progress','Completed','Rescheduled','Cancelled','Overdue')",
            name="ck_ctms_monitoring_activities_status",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_activities_planned_date",
        "ctms_monitoring_activities",
        ["study_id", "planned_date"],
    )
    op.create_index(
        "ix_ctms_monitoring_activities_status",
        "ctms_monitoring_activities",
        ["study_id", "site_id", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_activities_cra",
        "ctms_monitoring_activities",
        ["assigned_cra_id", "planned_date"],
    )
    op.create_index(
        "ix_ctms_monitoring_activities_edc_visit",
        "ctms_monitoring_activities",
        ["edc_visit_instance_id"],
    )
    op.create_index(
        "ix_ctms_monitoring_activities_plan_version",
        "ctms_monitoring_activities",
        ["plan_version_id"],
    )

    op.create_table(
        "ctms_monitoring_activity_schedule_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "activity_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_planned_date", sa.DateTime(timezone=True)),
        sa.Column("planned_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "changed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_ctms_monitoring_activity_schedule_history_activity",
        "ctms_monitoring_activity_schedule_history",
        ["activity_id", "changed_at"],
    )
    op.create_index(
        "ix_ctms_monitoring_activity_schedule_history_correlation",
        "ctms_monitoring_activity_schedule_history",
        ["correlation_id"],
    )

    _create_guards()


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ctms_monitoring_schedule_history_immutable ON ctms_monitoring_activity_schedule_history;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_ctms_monitoring_history_modification();"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS ctms_monitoring_plan_versions_immutable ON ctms_monitoring_plan_versions;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS prevent_ctms_published_monitoring_version_modification();"
    )
    for table in ("ctms_monitoring_plans", "ctms_monitoring_activities"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_scope_guard ON {table};")
    op.execute("DROP FUNCTION IF EXISTS ctms_monitoring_validate_site_study_scope();")

    op.drop_index(
        "ix_ctms_monitoring_activity_schedule_history_correlation",
        table_name="ctms_monitoring_activity_schedule_history",
    )
    op.drop_index(
        "ix_ctms_monitoring_activity_schedule_history_activity",
        table_name="ctms_monitoring_activity_schedule_history",
    )
    op.drop_table("ctms_monitoring_activity_schedule_history")

    for name in (
        "ix_ctms_monitoring_activities_plan_version",
        "ix_ctms_monitoring_activities_edc_visit",
        "ix_ctms_monitoring_activities_cra",
        "ix_ctms_monitoring_activities_status",
        "ix_ctms_monitoring_activities_planned_date",
    ):
        op.drop_index(name, table_name="ctms_monitoring_activities")
    op.drop_table("ctms_monitoring_activities")

    op.drop_constraint(
        "fk_ctms_monitoring_plans_current_version",
        "ctms_monitoring_plans",
        type_="foreignkey",
    )
    for name in (
        "ix_ctms_monitoring_plan_versions_correlation_id",
        "ix_ctms_monitoring_plan_versions_published_at",
        "ix_ctms_monitoring_plan_versions_status",
    ):
        op.drop_index(name, table_name="ctms_monitoring_plan_versions")
    op.drop_table("ctms_monitoring_plan_versions")

    op.drop_index("ix_ctms_monitoring_plans_correlation_id", table_name="ctms_monitoring_plans")
    op.drop_index("ix_ctms_monitoring_plans_scope_status", table_name="ctms_monitoring_plans")
    op.drop_table("ctms_monitoring_plans")
