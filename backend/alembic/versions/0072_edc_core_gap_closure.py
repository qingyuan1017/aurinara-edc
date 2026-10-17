"""Add independent EDC quality state, SDR, and controlled locks.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = (
    ("listing.read", "Read authorized EDC clinical listings"),
    ("review.read", "Read clinical review status and worklists"),
    ("sdv.read", "Read source data verification status and worklists"),
    ("sdr.read", "Read source data review status and worklists"),
    ("sdr.manage", "Perform source data review"),
    ("designer.sdr.configure", "Configure versioned SDR selection settings"),
    ("lock.read", "Read EDC freeze and lock status"),
    ("lock.request", "Request EDC freeze, lock, unfreeze, or unlock"),
    ("lock.approve", "Approve or reject EDC clinical control requests"),
    ("lock.execute", "Execute approved EDC clinical control requests"),
)


def _seed_permissions() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.Text()),
    )
    bind = op.get_bind()
    for code, description in _PERMISSIONS:
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
        else:
            exists = bind.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).first()
            if exists is None:
                import uuid

                op.bulk_insert(
                    permissions,
                    [{"id": uuid.uuid4(), "code": code, "description": description}],
                )

    grants = {
        "Data Manager": (
            "listing.read",
            "review.read",
            "sdv.read",
            "sdr.read",
            "lock.read",
            "lock.request",
            "lock.approve",
            "lock.execute",
        ),
        "CRA": ("listing.read", "sdv.read", "sdr.read", "sdr.manage", "lock.read"),
        "Medical Reviewer": ("listing.read", "review.read", "lock.read"),
        "Designer_Role": ("designer.sdr.configure",),
        "Site Coordinator": ("form.read",),
    }
    for role_name, codes in grants.items():
        for code in codes:
            op.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r JOIN permissions p ON p.code = :code "
                    "WHERE r.name = :role_name AND NOT EXISTS ("
                    "SELECT 1 FROM role_permissions rp "
                    "WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
                ).bindparams(role_name=role_name, code=code)
            )


def upgrade() -> None:
    op.add_column(
        "form_definitions",
        sa.Column("requires_signature", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for table in ("subjects", "visit_instances", "form_instances", "field_values"):
        op.add_column(
            table,
            sa.Column("data_revision", sa.Integer(), nullable=False, server_default="0"),
        )

    op.add_column(
        "form_instances",
        sa.Column("data_entry_status", sa.String(20), nullable=False, server_default="Not Started"),
    )
    op.execute(
        sa.text(
            "UPDATE form_instances SET data_entry_status = CASE "
            "WHEN status IN ('Reviewed','Frozen','Locked','Signed') THEN 'Submitted' "
            "ELSE status END"
        )
    )
    op.execute(
        sa.text(
            "UPDATE form_instances SET status = 'Submitted' "
            "WHERE status IN ('Reviewed','Frozen','Locked','Signed')"
        )
    )
    op.create_index("ix_form_instances_data_entry_status", "form_instances", ["data_entry_status"])
    op.add_column("sdv_status", sa.Column("verified_revision", sa.Integer()))
    op.add_column("review_status", sa.Column("reviewed_revision", sa.Integer()))

    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "sdr_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy", sa.String(20), nullable=False, server_default="all"),
        sa.Column("percentage", sa.Integer()),
        sa.Column("targeted_field_ids", json_type),
        sa.Column("is_required_for_lock", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("study_version_id", name="uq_sdr_settings_study_version"),
    )
    op.create_index("ix_sdr_settings_study_version", "sdr_settings", ["study_version_id"])

    op.create_table(
        "sdr_selections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "subject_id",
            sa.Uuid(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "form_instance_id",
            sa.Uuid(),
            sa.ForeignKey("form_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "design_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("selection_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("selection_reason", sa.String(255), nullable=False),
        sa.Column(
            "selected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "form_instance_id", "design_version_id", name="uq_sdr_selection_form_design"
        ),
    )
    op.create_index("ix_sdr_selections_study_status", "sdr_selections", ["study_id", "site_id"])

    op.create_table(
        "sdr_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "selection_id",
            sa.Uuid(),
            sa.ForeignKey("sdr_selections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="Pending"),
        sa.Column("reviewed_revision", sa.Integer()),
        sa.Column("outcome", sa.String(50)),
        sa.Column("comment", sa.Text()),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("selection_id", name="uq_sdr_result_selection"),
    )
    op.create_index("ix_sdr_results_status", "sdr_results", ["status"])

    op.create_table(
        "clinical_control_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_id", sa.Uuid(), sa.ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="Pending Approval"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "requested_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("executed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("readiness_snapshot", json_type),
        sa.Column("readiness_hash", sa.String(64)),
        sa.Column("failure_details", json_type),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_clinical_control_requests_scope",
        "clinical_control_requests",
        ["study_id", "scope_type", "scope_id", "status"],
    )
    op.create_index(
        "ix_clinical_control_requests_requested_at",
        "clinical_control_requests",
        ["requested_at"],
    )
    op.create_index(
        "uq_clinical_control_requests_active_action_scope",
        "clinical_control_requests",
        ["study_id", "scope_type", "scope_id", "action"],
        unique=True,
        postgresql_where=sa.text("status IN ('Pending Approval', 'Approved')"),
    )
    _seed_permissions()


def downgrade() -> None:
    codes = tuple(code for code, _ in _PERMISSIONS)
    bind = op.get_bind()
    for code in codes:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"code": code},
        )
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})

    op.drop_index(
        "uq_clinical_control_requests_active_action_scope",
        table_name="clinical_control_requests",
    )
    op.drop_index(
        "ix_clinical_control_requests_requested_at", table_name="clinical_control_requests"
    )
    op.drop_index("ix_clinical_control_requests_scope", table_name="clinical_control_requests")
    op.drop_table("clinical_control_requests")
    op.drop_index("ix_sdr_results_status", table_name="sdr_results")
    op.drop_table("sdr_results")
    op.drop_index("ix_sdr_selections_study_status", table_name="sdr_selections")
    op.drop_table("sdr_selections")
    op.drop_index("ix_sdr_settings_study_version", table_name="sdr_settings")
    op.drop_table("sdr_settings")
    op.drop_column("review_status", "reviewed_revision")
    op.drop_column("sdv_status", "verified_revision")
    op.drop_index("ix_form_instances_data_entry_status", table_name="form_instances")
    op.drop_column("form_instances", "data_entry_status")
    for table in ("field_values", "form_instances", "visit_instances", "subjects"):
        op.drop_column(table, "data_revision")
    op.drop_column("form_definitions", "requires_signature")
