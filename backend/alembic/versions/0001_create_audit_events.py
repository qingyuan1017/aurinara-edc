"""Create audit_events table with immutability trigger and revoked privileges.

Revision ID: 0001
Revises: None
Create Date: 2024-01-01 00:00:00.000000

Requirements:
  - 18.1: Audit event captures actor, timestamp, entity, study, site, subject,
           action, field, old/new value, reason, request_id, ip/user-agent.
  - 18.2: UPDATE/DELETE revoked from app role; trigger raises on modification.
  - 22.4: UUID primary keys.
  - 22.6: Indexed for efficient querying.
  - 25.2: Timestamps are timezone-aware UTC.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Create audit_events table ---
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True, comment="FK to users; nullable for system events"),
        sa.Column(
            "actor_email",
            sa.String(320),
            nullable=True,
            comment="Denormalized for long-term retention",
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC server clock at event creation",
        ),
        sa.Column(
            "entity_type",
            sa.String(100),
            nullable=False,
            comment="e.g. form_instance, subject, study",
        ),
        sa.Column("entity_id", sa.Uuid(), nullable=False, comment="PK of the affected entity"),
        sa.Column("study_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column(
            "action",
            sa.String(50),
            nullable=False,
            comment="e.g. create, update, delete, submit, sign",
        ),
        sa.Column("field_name", sa.String(255), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True, comment="Reason_For_Change"),
        sa.Column(
            "request_id", sa.Uuid(), nullable=False, comment="Correlates to X-Request-ID header"
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )

    # --- Indexes for efficient audit queries (Req 22.6) ---
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_audit_events_study_id", "audit_events", ["study_id"])
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])

    # --- Database-level immutability guard (Req 18.2) ---
    # Trigger function that raises an exception on any UPDATE or DELETE attempt
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Audit events cannot be modified or deleted';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach the trigger to the audit_events table
    op.execute("""
        CREATE TRIGGER audit_events_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
    """)

    # --- Revoke UPDATE/DELETE from application role (Req 18.2) ---
    # The app role name is configurable; default to 'edc_app' which the application connects as.
    # If the role does not exist yet (e.g., local dev), this is a no-op at migration time
    # but should be applied in production provisioning.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edc_app') THEN
                REVOKE UPDATE, DELETE ON audit_events FROM edc_app;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Re-grant privileges (for rollback only — should not happen in production)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edc_app') THEN
                GRANT UPDATE, DELETE ON audit_events TO edc_app;
            END IF;
        END $$;
    """)

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_modification();")

    # Drop indexes
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_subject_id", table_name="audit_events")
    op.drop_index("ix_audit_events_study_id", table_name="audit_events")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")

    # Drop table
    op.drop_table("audit_events")
