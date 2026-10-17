"""Add governed custom-function definitions, versions, and execution metadata.

Revision ID: 0075
Revises: 0074
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = (
    ("designer.custom_function.author", "Author immutable custom Python function versions"),
    ("designer.custom_function.approve", "Approve and activate custom Python functions"),
    ("designer.custom_function.execute", "Execute approved custom Python functions"),
)


def _seed_permission_catalog() -> None:
    bind = op.get_bind()
    for code, description in _PERMISSIONS:
        if context.is_offline_mode() or bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "INSERT INTO permissions (id, code, description) "
                    "VALUES (gen_random_uuid(), :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code, description=description)
            )
        else:
            exists = bind.execute(
                sa.text("SELECT id FROM permissions WHERE code = :code").bindparams(code=code)
            ).first()
            if exists is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO permissions (id, code, description) "
                        "VALUES (:id, :code, :description)"
                    ).bindparams(id=str(uuid.uuid4()), code=code, description=description)
                )


def upgrade() -> None:
    op.create_table(
        "custom_function_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "study_version_id",
            sa.Uuid(),
            sa.ForeignKey("study_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "study_version_id", "name", name="uq_custom_function_definition_version_name"
        ),
    )
    op.create_index(
        "ix_custom_function_definitions_version",
        "custom_function_definitions",
        ["study_version_id"],
    )

    op.create_table(
        "custom_function_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "definition_id",
            sa.Uuid(),
            sa.ForeignKey("custom_function_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(20), nullable=False, server_default="python"),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("entrypoint", sa.String(128), nullable=False, server_default="main"),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("language = 'python'", name="ck_custom_function_language_python"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_custom_function_source_hash"),
        sa.UniqueConstraint(
            "definition_id", "version_number", name="uq_custom_function_version_number"
        ),
    )
    op.create_index(
        "ix_custom_function_versions_definition", "custom_function_versions", ["definition_id"]
    )
    op.create_index("ix_custom_function_versions_status", "custom_function_versions", ["status"])
    bind = op.get_bind()
    if context.is_offline_mode() or bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_custom_function_source_update()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.definition_id IS DISTINCT FROM OLD.definition_id
                   OR NEW.version_number IS DISTINCT FROM OLD.version_number
                   OR NEW.language IS DISTINCT FROM OLD.language
                   OR NEW.source_code IS DISTINCT FROM OLD.source_code
                   OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256
                   OR NEW.entrypoint IS DISTINCT FROM OLD.entrypoint
                   OR NEW.input_schema IS DISTINCT FROM OLD.input_schema
                   OR NEW.output_schema IS DISTINCT FROM OLD.output_schema
                   OR NEW.created_by IS DISTINCT FROM OLD.created_by
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'custom function source versions are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_custom_function_source_immutable
            BEFORE UPDATE ON custom_function_versions
            FOR EACH ROW EXECUTE FUNCTION reject_custom_function_source_update();
            """
        )

    op.create_table(
        "custom_function_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "function_version_id",
            sa.Uuid(),
            sa.ForeignKey("custom_function_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "study_id",
            sa.Uuid(),
            sa.ForeignKey("studies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("invoked_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("runtime_execution_id", sa.String(128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_custom_function_executions_version",
        "custom_function_executions",
        ["function_version_id"],
    )
    op.create_index(
        "ix_custom_function_executions_study_created",
        "custom_function_executions",
        ["study_id", "created_at"],
    )
    _seed_permission_catalog()


def downgrade() -> None:
    for code, _description in _PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ).bindparams(code=code)
        )
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
    bind = op.get_bind()
    if context.is_offline_mode() or bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_custom_function_source_immutable "
            "ON custom_function_versions"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_custom_function_source_update()")
    op.drop_table("custom_function_executions")
    op.drop_table("custom_function_versions")
    op.drop_table("custom_function_definitions")
