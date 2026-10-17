"""Allow attachment metadata to reference Platform-only bytes.

Revision ID: 0082
Revises: 0081
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("file_attachments", "storage_key", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "ck_file_attachments_storage_locator",
        "file_attachments",
        "storage_key IS NOT NULL OR platform_object_id IS NOT NULL",
    )


def downgrade() -> None:
    connection = op.get_bind()
    missing = connection.scalar(
        sa.text("SELECT count(*) FROM file_attachments WHERE storage_key IS NULL")
    )
    if missing:
        raise RuntimeError("Cannot downgrade while Platform-only attachments exist")
    op.drop_constraint(
        "ck_file_attachments_storage_locator", "file_attachments", type_="check"
    )
    op.alter_column("file_attachments", "storage_key", existing_type=sa.Text(), nullable=False)
