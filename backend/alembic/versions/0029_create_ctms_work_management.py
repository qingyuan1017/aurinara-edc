"""Add CTMS work-management dependencies and environment-gated escalations.

Existing phase-1 task/contact tables remain authoritative CTMS tables. This
revision adds only operational metadata and work-management tables; EDC query
rows are referenced by ID and are never copied or mutated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED_EDC_TABLES = ("users", "studies", "sites", "queries")
_CTMS_TABLES = ("ctms_tasks", "ctms_contacts", "ctms_task_dependencies", "ctms_escalations")


def _assert_phase_gate(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("""
            DO $$
            DECLARE configured_phase text;
            BEGIN
                configured_phase := current_setting('app.ctms_phase', true);
                IF configured_phase IS NOT NULL AND configured_phase <> ''
                   AND configured_phase::integer < 2 THEN
                    RAISE EXCEPTION 'CTMS Phase 2 migration is disabled by app.ctms_phase';
                END IF;
            END $$;
        """))


def _assert_edc_dependencies(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql" and not context.is_offline_mode():
        missing = [name for name in _REQUIRED_EDC_TABLES if not inspect(bind).has_table(name)]
        if missing:
            raise RuntimeError("CTMS work management requires canonical EDC tables: " + ", ".join(missing))


def upgrade() -> None:
    bind = op.get_bind()
    _assert_phase_gate(bind)
    _assert_edc_dependencies(bind)
    existing = set(inspect(bind).get_table_names()) if not context.is_offline_mode() else set()

    if "ctms_tasks" in existing:
        columns = {column["name"] for column in inspect(bind).get_columns("ctms_tasks")}
        if "query_summary" not in columns:
            op.add_column("ctms_tasks", sa.Column("query_summary", sa.String(512), nullable=True))
    if "ctms_contacts" in existing:
        columns = {column["name"] for column in inspect(bind).get_columns("ctms_contacts")}
        if "owner_id" not in columns:
            op.add_column(
                "ctms_contacts",
                sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            )

    if "ctms_task_dependencies" not in existing:
        op.create_table(
            "ctms_task_dependencies",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("task_id", sa.Uuid(), sa.ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("depends_on_task_id", sa.Uuid(), sa.ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("correlation_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_ctms_task_dependency"),
            sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_ctms_task_dependency_not_self"),
        )
        op.create_index("ix_ctms_task_dependencies_task", "ctms_task_dependencies", ["task_id"])
        op.create_index("ix_ctms_task_dependencies_prerequisite", "ctms_task_dependencies", ["depends_on_task_id"])

    if "ctms_escalations" not in existing:
        op.create_table(
            "ctms_escalations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("task_id", sa.Uuid(), sa.ForeignKey("ctms_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("status", sa.String(20), nullable=False, server_default="Open"),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("deadline", sa.DateTime(timezone=True)),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("correlation_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("status IN ('Open','In Progress','Resolved','Cancelled')", name="ck_ctms_escalations_status"),
        )
        op.create_index("ix_ctms_escalations_task_status", "ctms_escalations", ["task_id", "status"])
        op.create_index("ix_ctms_escalations_deadline", "ctms_escalations", ["deadline"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names()) if not context.is_offline_mode() else set()
    if "ctms_escalations" in existing:
        op.drop_index("ix_ctms_escalations_deadline", table_name="ctms_escalations")
        op.drop_index("ix_ctms_escalations_task_status", table_name="ctms_escalations")
        op.drop_table("ctms_escalations")
    if "ctms_task_dependencies" in existing:
        op.drop_index("ix_ctms_task_dependencies_prerequisite", table_name="ctms_task_dependencies")
        op.drop_index("ix_ctms_task_dependencies_task", table_name="ctms_task_dependencies")
        op.drop_table("ctms_task_dependencies")
    if "ctms_contacts" in existing and "owner_id" in {column["name"] for column in inspect(bind).get_columns("ctms_contacts")}:
        op.drop_column("ctms_contacts", "owner_id")
    if "ctms_tasks" in existing and "query_summary" in {column["name"] for column in inspect(bind).get_columns("ctms_tasks")}:
        op.drop_column("ctms_tasks", "query_summary")
