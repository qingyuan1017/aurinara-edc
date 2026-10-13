"""Complete the CTMS monitoring MVP.

Revision ID: 0067
Revises: 0066
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | Sequence[str] | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owned_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
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
    ]


def upgrade() -> None:
    json_type = sa.JSON()
    op.add_column("ctms_monitoring_activities", sa.Column("visit_code", sa.String(40)))
    op.add_column(
        "ctms_monitoring_activities",
        sa.Column("modality", sa.String(20), nullable=False, server_default="On-site"),
    )
    op.add_column(
        "ctms_monitoring_activities", sa.Column("actual_start_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "ctms_monitoring_activities", sa.Column("actual_end_at", sa.DateTime(timezone=True))
    )
    op.drop_constraint(
        "ck_ctms_monitoring_activities_type", "ctms_monitoring_activities", type_="check"
    )
    op.create_check_constraint(
        "ck_ctms_monitoring_activities_type",
        "ctms_monitoring_activities",
        "activity_type IN ('Site Qualification','Site Initiation','Routine Monitoring','Close-out','Remote Review','Triggered Review','Unscheduled')",
    )
    op.create_check_constraint(
        "ck_ctms_monitoring_activities_modality",
        "ctms_monitoring_activities",
        "modality IN ('On-site','Remote','Hybrid')",
    )
    op.create_index(
        "ix_ctms_monitoring_activities_code",
        "ctms_monitoring_activities",
        ["visit_code"],
        unique=True,
    )

    op.create_table(
        "ctms_monitoring_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "plan_version_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_plan_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("visit_type", sa.String(40), nullable=False),
        sa.Column("frequency_value", sa.Integer()),
        sa.Column("frequency_unit", sa.String(30)),
        sa.Column("trigger", sa.Text()),
        sa.Column("allowed_modalities", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expected_duration_hours", sa.Integer()),
        sa.Column("required_activities", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("report_due_days", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "frequency_value IS NULL OR frequency_value > 0",
            name="ck_ctms_monitoring_rules_frequency",
        ),
        sa.CheckConstraint("report_due_days >= 0", name="ck_ctms_monitoring_rules_report_due"),
    )
    op.create_index(
        "ix_ctms_monitoring_rules_version",
        "ctms_monitoring_rules",
        ["plan_version_id", "sort_order"],
    )

    op.create_table(
        "ctms_monitoring_visit_activities",
        *_owned_columns(),
        sa.Column(
            "visit_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "rule_id", sa.Uuid(), sa.ForeignKey("ctms_monitoring_rules.id", ondelete="RESTRICT")
        ),
        sa.Column("requirement_key", sa.String(100), nullable=False),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("plan_reference", sa.String(255)),
        sa.Column("result", sa.String(30), nullable=False, server_default="Pending"),
        sa.Column("review_details", sa.Text()),
        sa.Column("observations", sa.Text()),
        sa.Column("subject_reference", sa.String(255)),
        sa.Column("record_reference", sa.String(255)),
        sa.Column("evidence_references", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "result IN ('Pending','Completed','Not Completed','Not Applicable')",
            name="ck_ctms_monitoring_visit_activity_result",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_visit_activities_visit",
        "ctms_monitoring_visit_activities",
        ["visit_id", "sort_order"],
    )
    op.create_index(
        "ix_ctms_monitoring_visit_activities_correlation_id",
        "ctms_monitoring_visit_activities",
        ["correlation_id"],
    )

    op.create_table(
        "ctms_monitoring_visit_reports",
        *_owned_columns(),
        sa.Column(
            "visit_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "previous_report_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_visit_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("content", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reviewer_comments", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("controlled_snapshot", json_type),
        sa.Column("document_reference", sa.String(500)),
        sa.UniqueConstraint(
            "visit_id", "version_number", name="uq_ctms_monitoring_visit_reports_version"
        ),
        sa.CheckConstraint("version_number > 0", name="ck_ctms_monitoring_visit_reports_version"),
        sa.CheckConstraint(
            "status IN ('Draft','Submitted','Under Review','Revision Required','Approved','Finalized')",
            name="ck_ctms_monitoring_visit_reports_status",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_visit_reports_status",
        "ctms_monitoring_visit_reports",
        ["study_id", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_visit_reports_correlation_id",
        "ctms_monitoring_visit_reports",
        ["correlation_id"],
    )

    op.create_table(
        "ctms_monitoring_findings",
        *_owned_columns(),
        sa.Column("finding_code", sa.String(40), nullable=False, unique=True),
        sa.Column(
            "visit_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_activities.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_visit_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("responsible_party", sa.String(255)),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="Open"),
        sa.Column("capa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capa_reference", sa.String(255)),
        sa.Column("resolution", sa.Text()),
        sa.Column("verified_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closure_reason", sa.Text()),
        sa.CheckConstraint(
            "severity IN ('Critical','Major','Minor','Observation')",
            name="ck_ctms_monitoring_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('Open','Action Assigned','In Progress','Pending Verification','Closed','Cancelled')",
            name="ck_ctms_monitoring_findings_status",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_findings_scope",
        "ctms_monitoring_findings",
        ["study_id", "site_id", "status"],
    )
    op.create_index("ix_ctms_monitoring_findings_visit", "ctms_monitoring_findings", ["visit_id"])
    op.create_index(
        "ix_ctms_monitoring_findings_correlation_id", "ctms_monitoring_findings", ["correlation_id"]
    )

    op.create_table(
        "ctms_monitoring_action_items",
        *_owned_columns(),
        sa.Column(
            "finding_id",
            sa.Uuid(),
            sa.ForeignKey("ctms_monitoring_findings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("responsible_party", sa.String(255)),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="Open"),
        sa.Column("completion_evidence", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint(
            "status IN ('Open','Completed','Cancelled')",
            name="ck_ctms_monitoring_action_items_status",
        ),
    )
    op.create_index(
        "ix_ctms_monitoring_action_items_finding",
        "ctms_monitoring_action_items",
        ["finding_id", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_action_items_due",
        "ctms_monitoring_action_items",
        ["study_id", "due_date", "status"],
    )
    op.create_index(
        "ix_ctms_monitoring_action_items_correlation_id",
        "ctms_monitoring_action_items",
        ["correlation_id"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ctms_finalized_mvr_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status = 'Finalized' THEN
                RAISE EXCEPTION 'Finalized monitoring visit reports are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_monitoring_visit_reports_immutable
        BEFORE UPDATE OR DELETE ON ctms_monitoring_visit_reports
        FOR EACH ROW EXECUTE FUNCTION prevent_ctms_finalized_mvr_modification();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_published_ctms_monitoring_rule_modification()
        RETURNS TRIGGER AS $$
        DECLARE parent_status text;
        DECLARE target_plan_version_id uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_plan_version_id := OLD.plan_version_id;
            ELSE
                target_plan_version_id := NEW.plan_version_id;
            END IF;
            SELECT status INTO parent_status
            FROM ctms_monitoring_plan_versions
            WHERE id = target_plan_version_id;
            IF parent_status = 'Published' THEN
                RAISE EXCEPTION 'Rules for published monitoring plan versions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ctms_monitoring_rules_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON ctms_monitoring_rules
        FOR EACH ROW EXECUTE FUNCTION prevent_published_ctms_monitoring_rule_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ctms_monitoring_rules_immutable ON ctms_monitoring_rules")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_ctms_monitoring_rule_modification()")
    op.execute(
        "DROP TRIGGER IF EXISTS ctms_monitoring_visit_reports_immutable ON ctms_monitoring_visit_reports"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_ctms_finalized_mvr_modification()")
    for table in (
        "ctms_monitoring_action_items",
        "ctms_monitoring_findings",
        "ctms_monitoring_visit_reports",
        "ctms_monitoring_visit_activities",
        "ctms_monitoring_rules",
    ):
        op.drop_table(table)
    op.drop_index("ix_ctms_monitoring_activities_code", table_name="ctms_monitoring_activities")
    op.drop_constraint(
        "ck_ctms_monitoring_activities_modality", "ctms_monitoring_activities", type_="check"
    )
    op.drop_constraint(
        "ck_ctms_monitoring_activities_type", "ctms_monitoring_activities", type_="check"
    )
    op.create_check_constraint(
        "ck_ctms_monitoring_activities_type",
        "ctms_monitoring_activities",
        "activity_type IN ('Site Initiation','Routine Monitoring','Close-out','Remote Review','Triggered Review')",
    )
    op.drop_column("ctms_monitoring_activities", "actual_end_at")
    op.drop_column("ctms_monitoring_activities", "actual_start_at")
    op.drop_column("ctms_monitoring_activities", "modality")
    op.drop_column("ctms_monitoring_activities", "visit_code")
