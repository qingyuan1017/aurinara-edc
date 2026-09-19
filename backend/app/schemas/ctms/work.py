"""Pydantic contracts for CTMS operational work management."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.ctms import ensure_utc
from app.models.ctms.work import (
    EscalationStatus,
    OperationalContactStatus,
    OperationalTaskPriority,
    OperationalTaskStatus,
)
from app.schemas.base import BaseCreateSchema, BaseSchema


class TaskCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    site_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_id: UUID | None = None
    due_date: datetime | None = None
    priority: OperationalTaskPriority = OperationalTaskPriority.NORMAL
    status: OperationalTaskStatus = OperationalTaskStatus.OPEN
    query_id: UUID | None = None
    query_summary: str | None = Field(default=None, max_length=512)

    @field_validator("title", "description", "query_summary")
    @classmethod
    def no_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("text values must not be blank")
        return value.strip() if value is not None else None

    @field_validator("due_date")
    @classmethod
    def utc_due_date(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def query_summary_requires_query(self) -> TaskCreate:
        if self.query_summary is not None and self.query_id is None:
            raise ValueError("query_summary requires query_id")
        return self


class TaskUpdate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_id: UUID | None = None
    due_date: datetime | None = None
    priority: OperationalTaskPriority | None = None

    @field_validator("title", "description")
    @classmethod
    def no_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("text values must not be blank")
        return value.strip() if value is not None else None

    @field_validator("due_date")
    @classmethod
    def utc_due_date(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class TaskStatusChange(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    status: OperationalTaskStatus
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def non_blank_reason(cls, value: str) -> str:
        return value.strip()


class TaskResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    title: str
    description: str | None
    owner_id: UUID | None
    due_date: datetime | None
    priority: OperationalTaskPriority
    status: OperationalTaskStatus
    query_id: UUID | None
    query_summary: str | None
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ContactCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    study_id: UUID
    site_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=150)
    organization: str | None = Field(default=None, max_length=255)
    channels: dict[str, str] = Field(default_factory=dict)
    owner_id: UUID | None = None
    status: OperationalContactStatus = OperationalContactStatus.ACTIVE

    @field_validator("name", "role", "organization")
    @classmethod
    def no_blank_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("text values must not be blank")
        return value.strip() if value is not None else None


class ContactStatusChange(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    status: OperationalContactStatus
    reason: str = Field(min_length=1, max_length=1000)


class ContactResponse(BaseSchema):
    id: UUID
    study_id: UUID
    site_id: UUID | None
    name: str
    role: str | None
    organization: str | None
    channels: dict[str, Any]
    owner_id: UUID | None
    status: OperationalContactStatus
    correlation_id: UUID
    created_by: UUID
    updated_by: UUID | None
    created_at: datetime
    updated_at: datetime


class DependencyCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    depends_on_task_id: UUID


class EscalationCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    owner_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=1000)
    deadline: datetime | None = None
    status: EscalationStatus = EscalationStatus.OPEN

    @field_validator("deadline")
    @classmethod
    def utc_deadline(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class EscalationStatusChange(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    status: EscalationStatus
    reason: str = Field(min_length=1, max_length=1000)


__all__ = [
    "ContactCreate",
    "ContactResponse",
    "ContactStatusChange",
    "DependencyCreate",
    "EscalationCreate",
    "EscalationStatus",
    "EscalationStatusChange",
    "OperationalContactStatus",
    "OperationalTaskPriority",
    "OperationalTaskStatus",
    "TaskCreate",
    "TaskResponse",
    "TaskStatusChange",
    "TaskUpdate",
]


class QueryFollowUpCreate(BaseCreateSchema):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    approved_summary: str | None = Field(default=None, max_length=512)
    owner_id: UUID | None = None
    due_date: datetime | None = None
    priority: OperationalTaskPriority = OperationalTaskPriority.NORMAL

    @field_validator("due_date")
    @classmethod
    def utc_due_date(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None
