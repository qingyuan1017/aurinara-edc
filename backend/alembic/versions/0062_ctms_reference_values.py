"""Add configurable CTMS reference values.

Revision ID: 0062
Revises: 0061
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REFERENCE_VALUES = {
    "country": [
        ("US", "United States"),
        ("CA", "Canada"),
        ("GB", "United Kingdom"),
        ("DE", "Germany"),
        ("JP", "Japan"),
    ],
    "participating_organization_type": [
        ("CRO", "CRO"),
        ("SPONSOR", "Sponsor"),
        ("VENDOR", "Vendor"),
        ("COMMITTEE", "Committee"),
        ("HEALTH_CARE_PROVIDER", "Health Care Provider"),
    ],
    "therapeutic_area": [
        ("ONCOLOGY", "Oncology"),
        ("CARDIOLOGY", "Cardiology"),
        ("NEUROLOGY", "Neurology"),
        ("IMMUNOLOGY", "Immunology"),
        ("INFECTIOUS_DISEASES", "Infectious Diseases"),
    ],
    "indication": [
        ("BREAST_CANCER", "Breast Cancer"),
        ("HYPERTENSION", "Hypertension"),
        ("MAJOR_DEPRESSIVE_DISORDER", "Major Depressive Disorder"),
        ("RHEUMATOID_ARTHRITIS", "Rheumatoid Arthritis"),
        ("TYPE_2_DIABETES", "Type 2 Diabetes"),
    ],
}


def upgrade() -> None:
    table = op.create_table(
        "ctms_reference_values",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.Uuid()),
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
        sa.CheckConstraint(
            "category IN ('country','participating_organization_type','therapeutic_area','indication')",
            name="ck_ctms_reference_values_category",
        ),
        sa.UniqueConstraint("category", "code", name="uq_ctms_reference_values_category_code"),
    )
    op.create_index(
        "ix_ctms_reference_values_category_active_order",
        "ctms_reference_values",
        ["category", "active", "sort_order"],
    )
    rows = []
    for category, values in REFERENCE_VALUES.items():
        for sort_order, (code, label) in enumerate(values, start=10):
            rows.append(
                {
                    "id": uuid.uuid5(
                        uuid.NAMESPACE_URL, f"aurinara:ctms-reference:{category}:{code}"
                    ),
                    "category": category,
                    "code": code,
                    "label": label,
                    "sort_order": sort_order,
                    "active": True,
                }
            )
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index(
        "ix_ctms_reference_values_category_active_order", table_name="ctms_reference_values"
    )
    op.drop_table("ctms_reference_values")
