"""Versioned, approved custom Python functions for Designer rules.

Source is stored as immutable versions. Execution is delegated to the isolated
custom-function runtime and is never performed by the API process.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CustomFunctionVersionStatus(enum.StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    active = "active"
    rejected = "rejected"
    retired = "retired"
    disabled = "disabled"


class CustomFunctionExecutionStatus(enum.StrEnum):
    succeeded = "succeeded"
    failed = "failed"


class CustomFunctionDefinition(Base):
    __tablename__ = "custom_function_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    study_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("study_versions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    versions: Mapped[list[CustomFunctionVersion]] = relationship(
        "CustomFunctionVersion",
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="CustomFunctionVersion.version_number",
    )

    __table_args__ = (
        UniqueConstraint(
            "study_version_id", "name", name="uq_custom_function_definition_version_name"
        ),
        Index("ix_custom_function_definitions_version", "study_version_id"),
    )


class CustomFunctionVersion(Base):
    __tablename__ = "custom_function_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("custom_function_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[CustomFunctionVersionStatus] = mapped_column(
        String(32), nullable=False, default=CustomFunctionVersionStatus.draft
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    definition: Mapped[CustomFunctionDefinition] = relationship(
        "CustomFunctionDefinition", back_populates="versions", lazy="selectin"
    )
    executions: Mapped[list[CustomFunctionExecution]] = relationship(
        "CustomFunctionExecution", back_populates="function_version", lazy="raise"
    )

    __table_args__ = (
        UniqueConstraint(
            "definition_id", "version_number", name="uq_custom_function_version_number"
        ),
        CheckConstraint("language = 'python'", name="ck_custom_function_language_python"),
        CheckConstraint("length(source_sha256) = 64", name="ck_custom_function_source_hash"),
        Index("ix_custom_function_versions_definition", "definition_id"),
        Index("ix_custom_function_versions_status", "status"),
    )


class CustomFunctionExecution(Base):
    __tablename__ = "custom_function_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    function_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("custom_function_versions.id", ondelete="RESTRICT"), nullable=False
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studies.id", ondelete="RESTRICT"), nullable=False
    )
    invoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[CustomFunctionExecutionStatus] = mapped_column(String(20), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    function_version: Mapped[CustomFunctionVersion] = relationship(
        "CustomFunctionVersion", back_populates="executions"
    )

    __table_args__ = (
        Index("ix_custom_function_executions_version", "function_version_id"),
        Index("ix_custom_function_executions_study_created", "study_id", "created_at"),
    )


__all__ = [
    "CustomFunctionDefinition",
    "CustomFunctionExecution",
    "CustomFunctionExecutionStatus",
    "CustomFunctionVersion",
    "CustomFunctionVersionStatus",
]


@event.listens_for(CustomFunctionVersion, "before_update")
def _reject_source_mutation(_mapper, _connection, target: CustomFunctionVersion) -> None:
    """Require a new row for every source-bearing change."""
    state = inspect(target)
    immutable_fields = (
        "definition_id",
        "version_number",
        "language",
        "source_code",
        "source_sha256",
        "entrypoint",
        "input_schema",
        "output_schema",
        "created_by",
        "created_at",
    )
    if any(state.attrs[name].history.has_changes() for name in immutable_fields):
        raise ValueError("Custom function source versions are immutable")
