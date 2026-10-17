"""Complete the CTMS study workspace with dedicated operational records.

Revision ID: 0071
Revises: 0070
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    op.create_table(
        "ctms_study_team_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column(
            "staff_entity_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_managed_entities.id", ondelete="RESTRICT"),
        ),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("assignment_type", sa.String(20), nullable=False, server_default="Primary"),
        sa.Column("responsibilities", sa.Text()),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_audit_columns(),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND staff_entity_id IS NULL) OR "
            "(user_id IS NULL AND staff_entity_id IS NOT NULL)",
            name="ck_ctms_study_team_one_identity",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_ctms_study_team_dates",
        ),
    )
    op.create_index(
        "ix_ctms_study_team_scope", "ctms_study_team_assignments", ["study_id", "site_id", "active"]
    )
    op.create_index(
        "ix_ctms_study_team_user_dates",
        "ctms_study_team_assignments",
        ["user_id", "effective_from", "effective_to"],
    )

    op.create_table(
        "ctms_study_amendments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("amendment_number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_module", sa.String(20), nullable=False),
        sa.Column("source_reference_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.String(100)),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("effective_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(40), nullable=False, server_default="Draft"),
        sa.Column("summary", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_audit_columns(),
        sa.UniqueConstraint("study_id", "amendment_number", name="uq_ctms_study_amendment_number"),
    )
    op.create_index(
        "ix_ctms_study_amendment_status",
        "ctms_study_amendments",
        ["study_id", "status", "due_date"],
    )
    op.create_table(
        "ctms_study_amendment_impacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "amendment_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_study_amendments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("impact_area", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Open"),
        sa.Column("evidence_references", sa.JSON(), nullable=False, server_default="[]"),
        *_audit_columns(),
    )
    op.create_index(
        "ix_ctms_amendment_impact_scope",
        "ctms_study_amendment_impacts",
        ["study_id", "site_id", "status"],
    )
    op.create_table(
        "ctms_study_amendment_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "amendment_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_study_amendments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(40), nullable=False),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_ctms_amendment_transition",
        "ctms_study_amendment_transitions",
        ["amendment_id", "created_at"],
    )

    op.create_table(
        "ctms_site_closeout_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "site_id",
            sa.Uuid(),
            sa.ForeignKey("sites.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("planned_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Not Started"),
        sa.Column("closure_reason", sa.Text()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        *_audit_columns(),
        sa.UniqueConstraint("site_id", name="uq_ctms_site_closeout_site"),
    )
    op.create_index(
        "ix_ctms_site_closeout_scope",
        "ctms_site_closeout_plans",
        ["study_id", "status", "planned_date"],
    )
    op.create_table(
        "ctms_site_closeout_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_site_closeout_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("item_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Open"),
        sa.Column("due_date", sa.Date()),
        sa.Column("evidence_references", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_audit_columns(),
    )
    op.create_index("ix_ctms_closeout_item_plan", "ctms_site_closeout_items", ["plan_id", "status"])
    op.create_table(
        "ctms_site_closeout_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_site_closeout_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(30), nullable=False),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "ctms_risk_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("legacy_record_id", sa.Uuid(), unique=True),
        *_audit_columns(),
    )
    op.create_index("ix_ctms_ract_study_status", "ctms_risk_assessments", ["study_id", "status"])
    op.create_table(
        "ctms_risk_assessment_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_risk_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("rationale", sa.Text()),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("assessment_id", "version_number", name="uq_ctms_ract_version"),
    )
    op.create_table(
        "ctms_risk_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_risk_assessment_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("probability", sa.Integer(), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("detectability", sa.Integer(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("mitigation", sa.Text()),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_audit_columns(),
        sa.CheckConstraint(
            "probability BETWEEN 1 AND 5 AND impact BETWEEN 1 AND 5 "
            "AND detectability BETWEEN 1 AND 5",
            name="ck_ctms_risk_item_scale",
        ),
    )

    op.create_table(
        "ctms_kri_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("legacy_record_id", sa.Uuid(), unique=True),
        *_audit_columns(),
        sa.UniqueConstraint("study_id", "code", name="uq_ctms_kri_code"),
    )
    op.create_index("ix_ctms_kri_study_status", "ctms_kri_definitions", ["study_id", "status"])
    op.create_table(
        "ctms_kri_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "kri_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_kri_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("unit", sa.String(50)),
        sa.Column("amber_threshold", sa.Numeric(18, 4), nullable=False),
        sa.Column("red_threshold", sa.Numeric(18, 4), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False, server_default="above"),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("kri_id", "version_number", name="uq_ctms_kri_version"),
        sa.CheckConstraint(
            "(direction = 'above' AND red_threshold >= amber_threshold) OR "
            "(direction = 'below' AND red_threshold <= amber_threshold)",
            name="ck_ctms_kri_threshold_order",
        ),
    )
    op.create_table(
        "ctms_kri_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "kri_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_kri_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_kri_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("source_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reference_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_ctms_kri_observation_scope",
        "ctms_kri_observations",
        ["study_id", "site_id", "observed_at"],
    )

    op.create_table(
        "ctms_protocol_deviation_followups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("projection_id", sa.Uuid()),
        sa.Column("source_record_id", sa.Uuid()),
        sa.Column("approved_reference", sa.String(255), nullable=False),
        sa.Column("classification", sa.String(100)),
        sa.Column("severity", sa.String(30)),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False, server_default="New"),
        sa.Column("action_summary", sa.Text()),
        sa.Column("legacy_record_id", sa.Uuid(), unique=True),
        *_audit_columns(),
        sa.UniqueConstraint("projection_id", name="uq_ctms_pd_projection"),
    )
    op.create_index(
        "ix_ctms_pd_scope_status",
        "ctms_protocol_deviation_followups",
        ["study_id", "site_id", "status"],
    )

    op.create_table(
        "ctms_icf_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("version_code", sa.String(100), nullable=False),
        sa.Column("country_code", sa.String(3)),
        sa.Column("source_reference", sa.String(500), nullable=False),
        sa.Column("approved_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Approved"),
        sa.Column("legacy_record_id", sa.Uuid(), unique=True),
        *_audit_columns(),
        sa.UniqueConstraint(
            "study_id", "version_code", "country_code", name="uq_ctms_icf_version_country"
        ),
    )
    op.create_table(
        "ctms_icf_site_rollouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "icf_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_icf_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False, server_default="Planned"),
        sa.Column("distributed_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("training_completed_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_references", sa.JSON(), nullable=False, server_default="[]"),
        *_audit_columns(),
        sa.UniqueConstraint("icf_version_id", "site_id", name="uq_ctms_icf_site_rollout"),
    )
    op.create_index(
        "ix_ctms_icf_rollout_scope", "ctms_icf_site_rollouts", ["study_id", "site_id", "status"]
    )

    op.create_table(
        "ctms_tracking_log_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        *_audit_columns(),
    )
    op.create_table(
        "ctms_tracking_log_definition_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "definition_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_tracking_log_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("columns_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "definition_id", "version_number", name="uq_ctms_tracking_definition_version"
        ),
    )
    op.create_table(
        "ctms_study_tracking_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "definition_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_tracking_log_definition_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(30), nullable=False, server_default="Active"),
        sa.Column("legacy_record_id", sa.Uuid(), unique=True),
        *_audit_columns(),
    )
    op.create_index(
        "ix_ctms_tracking_log_study", "ctms_study_tracking_logs", ["study_id", "status"]
    )
    op.create_table(
        "ctms_tracking_log_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "log_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_study_tracking_logs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("row_key", sa.String(100), nullable=False),
        sa.Column("values_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.UniqueConstraint("log_id", "row_key", name="uq_ctms_tracking_entry_key"),
    )
    op.create_table(
        "ctms_tracking_log_entry_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "entry_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_tracking_log_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("values_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("entry_id", "revision_number", name="uq_ctms_tracking_entry_revision"),
    )

    # Preserve generic records and map them into the dedicated read models. The
    # old table remains available as a one-release read compatibility adapter.
    op.execute(
        sa.text("""
        INSERT INTO ctms_risk_assessments
            (id, study_id, name, owner_id, status, legacy_record_id, version, created_by,
             updated_by, correlation_id, created_at, updated_at, deleted_at)
        SELECT id, study_id, title, owner_id, 'Draft', id, 1, created_by, updated_by,
               correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'ract'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_risk_assessment_versions
            (id, assessment_id, version_number, status, rationale, created_by, created_at)
        SELECT id, id, 1, 'Draft', details_json->>'description', created_by, created_at
        FROM ctms_study_operation_records WHERE resource_type = 'ract'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_kri_definitions
            (id, study_id, code, name, owner_id, status, legacy_record_id, version, created_by,
             updated_by, correlation_id, created_at, updated_at, deleted_at)
        SELECT id, study_id, 'LEGACY-' || left(id::text, 8), title, owner_id, 'Draft', id, 1,
               created_by, updated_by, correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'kri'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_kri_versions
            (id, kri_id, version_number, source_type, amber_threshold, red_threshold, direction,
             created_by, created_at)
        SELECT id, id, 1, 'ctms_operational', 0, 0, 'above', created_by, created_at
        FROM ctms_study_operation_records WHERE resource_type = 'kri'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_protocol_deviation_followups
            (id, study_id, site_id, approved_reference, classification, severity, owner_id,
             due_date, status, action_summary, legacy_record_id, version, created_by, updated_by,
             correlation_id, created_at, updated_at, deleted_at)
        SELECT id, study_id, site_id, 'Legacy CTMS record ' || id::text, record_subtype,
               details_json->>'severity', owner_id, end_at::date, 'New',
               details_json->>'action_summary', id, 1, created_by, updated_by,
               correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'protocol_deviation'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_icf_versions
            (id, study_id, version_code, source_reference, approved_date, status,
             legacy_record_id, version, created_by, updated_by, correlation_id,
             created_at, updated_at, deleted_at)
        SELECT id, study_id, 'LEGACY-' || left(id::text, 8),
               'Legacy CTMS record ' || id::text, created_at::date, 'Approved', id, 1,
               created_by, updated_by, correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'icf'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_tracking_log_definitions
            (id, code, name, current_version, status, version, created_by, updated_by,
             correlation_id, created_at, updated_at, deleted_at)
        SELECT id, 'LEGACY-' || left(id::text, 8), title, 1, 'Published', 1,
               created_by, updated_by, correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'tracking_log'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_tracking_log_definition_versions
            (id, definition_id, version_number, columns_json, status, created_by, created_at)
        SELECT id, id, 1, '[]'::json, 'Published', created_by, created_at
        FROM ctms_study_operation_records WHERE resource_type = 'tracking_log'
        ON CONFLICT DO NOTHING
    """)
    )
    op.execute(
        sa.text("""
        INSERT INTO ctms_study_tracking_logs
            (id, study_id, definition_version_id, name, owner_id, status, legacy_record_id,
             version, created_by, updated_by, correlation_id, created_at, updated_at, deleted_at)
        SELECT id, study_id, id, title, owner_id, 'Active', id, 1, created_by, updated_by,
               correlation_id::text, created_at, updated_at, deleted_at
        FROM ctms_study_operation_records WHERE resource_type = 'tracking_log'
        ON CONFLICT DO NOTHING
    """)
    )


def downgrade() -> None:
    for table in (
        "ctms_tracking_log_entry_revisions",
        "ctms_tracking_log_entries",
        "ctms_study_tracking_logs",
        "ctms_tracking_log_definition_versions",
        "ctms_tracking_log_definitions",
        "ctms_icf_site_rollouts",
        "ctms_icf_versions",
        "ctms_protocol_deviation_followups",
        "ctms_kri_observations",
        "ctms_kri_versions",
        "ctms_kri_definitions",
        "ctms_risk_items",
        "ctms_risk_assessment_versions",
        "ctms_risk_assessments",
        "ctms_site_closeout_transitions",
        "ctms_site_closeout_items",
        "ctms_site_closeout_plans",
        "ctms_study_amendment_transitions",
        "ctms_study_amendment_impacts",
        "ctms_study_amendments",
        "ctms_study_team_assignments",
    ):
        op.drop_table(table)
