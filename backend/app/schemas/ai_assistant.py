"""Request schemas for the optional streaming AI assistant."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema


class AIChatMessage(BaseCreateSchema):
    """A prior conversational turn supplied to the assistant."""

    role: str = Field(..., min_length=1, max_length=32)
    content: str = Field(..., min_length=1, max_length=20_000)


class _ScopedAIRequest(BaseCreateSchema):
    """Common optional scope supplied with clinical AI requests."""

    study_id: UUID | None = None
    site_id: UUID | None = None


class AIChatRequest(_ScopedAIRequest):
    """Input for the general AI chat stream."""

    message: str = Field(..., min_length=1, max_length=20_000)
    conversation: list[AIChatMessage] = Field(default_factory=list, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class AIEditCheckDraftRequest(_ScopedAIRequest):
    """Input for drafting a declarative edit check."""

    prompt: str = Field(..., min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)


class AIQuerySummaryRequest(_ScopedAIRequest):
    """Input for summarizing a query or query-shaped clinical context."""

    query: dict[str, Any] = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AIApplySuggestionRequest",
    "AIChatMessage",
    "AIChatRequest",
    "AIEditCheckDraftRequest",
    "AIQuerySummaryRequest",
]


class AIApplySuggestionRequest(BaseCreateSchema):
    """A reviewed AI suggestion and an independent confirmation signal."""

    suggestion: dict[str, Any] = Field(..., min_length=1)
    confirmed: bool = False
