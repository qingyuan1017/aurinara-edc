"""Complete CTMS portfolio operational workspaces.

Revision ID: 0070
Revises: 0069
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0070"
down_revision: str | Sequence[str] | None = "0069"
branch_labels = None
depends_on = None

JSON = postgresql.JSONB(astext_type=sa.Text())


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ctms_operational_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("template_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_ctms_operational_template_type", "ctms_operational_templates", ["template_type", "name"]
    )
    op.create_table(
        "ctms_operational_template_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_operational_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content_json", JSON, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("template_id", "version_number", name="uq_ctms_template_version"),
    )
    op.create_index(
        "ix_ctms_template_version_status",
        "ctms_operational_template_versions",
        ["template_id", "status"],
    )
    op.create_table(
        "ctms_site_feasibility_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "questionnaire_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_operational_template_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("criteria_json", JSON, nullable=False),
        sa.Column("responses_json", JSON, nullable=False),
        sa.Column("score", sa.Numeric(5, 2)),
        sa.Column("recommendation", sa.String(50)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("retention_state", sa.String(30), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("study_id", "site_id", name="uq_ctms_feasibility_study_site"),
    )
    op.create_index(
        "ix_ctms_feasibility_scope_status",
        "ctms_site_feasibility_assessments",
        ["study_id", "site_id", "status"],
    )
    op.create_index(
        "ix_ctms_feasibility_owner_status",
        "ctms_site_feasibility_assessments",
        ["owner_id", "status"],
    )
    op.create_table(
        "ctms_site_performance_scorecards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("weights_json", JSON, nullable=False),
        sa.Column("thresholds_json", JSON, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "version_number", name="uq_ctms_scorecard_name_version"),
    )
    op.create_index(
        "ix_ctms_scorecard_status", "ctms_site_performance_scorecards", ["status", "published_at"]
    )
    scorecard_id = uuid.uuid4()
    op.execute(
        sa.text(
            "INSERT INTO ctms_site_performance_scorecards (id,name,version_number,status,weights_json,thresholds_json,published_at,created_at) VALUES (:id,'Default operational scorecard',1,'Published',CAST(:weights AS jsonb),CAST('{}' AS jsonb),CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ).bindparams(
            id=scorecard_id,
            weights='{"startup_timeliness":15,"enrollment_attainment":25,"monitoring_timeliness":20,"finding_aging":15,"task_timeliness":10,"data_quality":15}',
        )
    )
    op.create_table(
        "ctms_site_performance_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "scorecard_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_site_performance_scorecards.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("component_scores_json", JSON, nullable=False),
        sa.Column("component_sources_json", JSON, nullable=False),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("source_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "study_id",
            "site_id",
            "scorecard_id",
            "snapshot_date",
            name="uq_ctms_site_performance_snapshot",
        ),
    )
    op.create_index(
        "ix_ctms_site_performance_scope_date",
        "ctms_site_performance_snapshots",
        ["study_id", "site_id", "snapshot_date"],
    )
    op.create_table(
        "ctms_corrective_action_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("root_cause", sa.Text()),
        sa.Column("corrective_actions_json", JSON, nullable=False),
        sa.Column("preventive_actions_json", JSON, nullable=False),
        sa.Column("evidence_references_json", JSON, nullable=False),
        sa.Column("effectiveness_criteria", sa.Text()),
        sa.Column("effectiveness_result", sa.Text()),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closure_reason", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("retention_state", sa.String(30), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_type", "source_id", name="uq_ctms_capa_source"),
    )
    op.create_index(
        "ix_ctms_capa_scope_status",
        "ctms_corrective_action_plans",
        ["study_id", "site_id", "status"],
    )
    op.create_index(
        "ix_ctms_capa_owner_due", "ctms_corrective_action_plans", ["owner_id", "due_date"]
    )
    op.create_table(
        "ctms_capa_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "capa_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_corrective_action_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(30), nullable=False),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ctms_capa_transition_history", "ctms_capa_transitions", ["capa_id", "created_at"]
    )
    op.create_table(
        "ctms_template_applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "template_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_operational_template_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("result_json", JSON, nullable=False),
        sa.Column(
            "applied_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("study_id", "idempotency_key", name="uq_ctms_template_application_key"),
    )
    op.create_table(
        "ctms_workflow_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ctms_workflow_rule_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_workflow_rules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("conditions_json", JSON, nullable=False),
        sa.Column("actions_json", JSON, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_id", "version_number", name="uq_ctms_workflow_rule_version"),
    )
    op.create_index(
        "ix_ctms_workflow_trigger_status", "ctms_workflow_rule_versions", ["trigger_type", "status"]
    )
    op.create_table(
        "ctms_workflow_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_workflow_rule_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_json", JSON, nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "rule_version_id",
            "source_type",
            "source_id",
            "occurrence_key",
            name="uq_ctms_workflow_execution",
        ),
    )
    op.create_table(
        "ctms_cra_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("planned_hours_per_week", sa.Numeric(6, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("over_capacity_reason", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ctms_cra_assignment_scope", "ctms_cra_assignments", ["study_id", "site_id", "active"]
    )
    op.create_index(
        "ix_ctms_cra_assignment_user_dates",
        "ctms_cra_assignments",
        ["user_id", "effective_from", "effective_to"],
    )
    op.create_table(
        "ctms_cra_capacity_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("capacity_hours", sa.Numeric(6, 2), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "week_start", name="uq_ctms_cra_capacity_week"),
    )
    op.create_table(
        "ctms_cra_availability_exceptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("exception_type", sa.String(30), nullable=False),
        sa.Column("unavailable_hours", sa.Numeric(6, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ctms_cra_exception_user_date",
        "ctms_cra_availability_exceptions",
        ["user_id", "exception_date"],
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(
        permissions,
        [
            {
                "id": uuid.uuid4(),
                "code": "ctms.template_rule_management",
                "description": "Manage CTMS operational templates and workflow rules",
            },
            {
                "id": uuid.uuid4(),
                "code": "ctms.capa_management",
                "description": "Manage CTMS corrective and preventive actions",
            },
            {
                "id": uuid.uuid4(),
                "code": "ctms.capacity_override",
                "description": "Override CRA capacity controls with a reason",
            },
        ],
    )
    op.execute(
        sa.text("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE (r.name = 'CTMS_Admin' AND p.code IN ('ctms.template_rule_management','ctms.capa_management','ctms.capacity_override'))
           OR (r.name = 'CTMS_Operations_User' AND p.code = 'ctms.capa_management')
        ON CONFLICT DO NOTHING
    """)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('ctms.template_rule_management','ctms.capa_management','ctms.capacity_override'))"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions WHERE code IN ('ctms.template_rule_management','ctms.capa_management','ctms.capacity_override')"
        )
    )
    for table in (
        "ctms_cra_availability_exceptions",
        "ctms_cra_capacity_plans",
        "ctms_cra_assignments",
        "ctms_workflow_executions",
        "ctms_workflow_rule_versions",
        "ctms_workflow_rules",
        "ctms_template_applications",
        "ctms_capa_transitions",
        "ctms_corrective_action_plans",
        "ctms_site_performance_snapshots",
        "ctms_site_performance_scorecards",
        "ctms_site_feasibility_assessments",
        "ctms_operational_template_versions",
        "ctms_operational_templates",
    ):
        op.drop_table(table)
