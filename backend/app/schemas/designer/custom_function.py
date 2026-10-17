"""API contracts for approved, sandboxed custom Python functions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.shared.base import UtcDatetime


class CustomFunctionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1, max_length=262_144)
    entrypoint: str = Field(default="main", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    language: Literal["python"] = "python"

    @field_validator("source_code")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("source_code must not contain null bytes")
        return value


class CustomFunctionCreate(CustomFunctionSource):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    description: str | None = Field(default=None, max_length=4000)


class CustomFunctionVersionCreate(CustomFunctionSource):
    pass


class CustomFunctionRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class CustomFunctionExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)


class CustomFunctionVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    definition_id: UUID
    version_number: int
    language: str
    source_sha256: str
    entrypoint: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str
    created_by: UUID | None
    created_at: UtcDatetime
    submitted_by: UUID | None
    submitted_at: UtcDatetime | None
    approved_by: UUID | None
    approved_at: UtcDatetime | None
    rejection_reason: str | None
    activated_at: UtcDatetime | None
    retired_at: UtcDatetime | None


class CustomFunctionVersionResponse(CustomFunctionVersionSummary):
    source_code: str


class CustomFunctionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    study_version_id: UUID
    name: str
    description: str | None
    created_by: UUID | None
    created_at: UtcDatetime
    versions: list[CustomFunctionVersionSummary] = Field(default_factory=list)


class CustomFunctionExecutionResponse(BaseModel):
    execution_id: UUID
    runtime_execution_id: str | None = None
    status: Literal["succeeded", "failed"]
    result: Any = None
    commands: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    duration_ms: int | None = None


__all__ = [
    "CustomFunctionCreate",
    "CustomFunctionExecuteRequest",
    "CustomFunctionExecutionResponse",
    "CustomFunctionRejectRequest",
    "CustomFunctionResponse",
    "CustomFunctionVersionCreate",
    "CustomFunctionVersionResponse",
    "CustomFunctionVersionSummary",
]
