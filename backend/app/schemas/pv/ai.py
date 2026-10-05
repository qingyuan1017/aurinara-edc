"""Request schemas for the optional PV-scoped streaming AI assistant.

These mirror the shared AI request contracts but are scoped to PV safety
context. A PV AI request carries only optional canonical scope identifiers
(``study_id``/``site_id``) and PV-owned context. EDC clinical and CTMS
operational payloads are additionally stripped by the shared context
minimizer before any content is sent to the model (Requirement 22.3).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseCreateSchema


class _ScopedPVAIRequest(BaseCreateSchema):
    """Common optional canonical scope supplied with a PV AI request."""

    study_id: UUID | None = None
    site_id: UUID | None = None


class PVAIChatMessage(BaseCreateSchema):
    """A prior conversational turn supplied to the PV assistant."""

    role: str = Field(..., min_length=1, max_length=32)
    content: str = Field(..., min_length=1, max_length=20_000)


class PVAIChatRequest(_ScopedPVAIRequest):
    """Input for the PV-scoped assistant chat stream."""

    message: str = Field(..., min_length=1, max_length=20_000)
    conversation: list[PVAIChatMessage] = Field(default_factory=list, max_length=100)
    context: dict[str, Any] = Field(default_factory=dict)


class PVAINarrativeDraftRequest(_ScopedPVAIRequest):
    """Input for drafting a Case_Narrative for a Safety_Case.

    ``case_id`` identifies the PV Safety_Case the draft is for. The draft is a
    preview only; applying it to Safety_Data requires an explicit, separate
    human confirmation (Requirement 22.4).
    """

    case_id: UUID
    prompt: str = Field(..., min_length=1, max_length=20_000)
    context: dict[str, Any] = Field(default_factory=dict)


class PVAICaseSummaryRequest(_ScopedPVAIRequest):
    """Input for summarizing a Safety_Case."""

    case_id: UUID
    context: dict[str, Any] = Field(default_factory=dict)


class PVAIApplySuggestionRequest(BaseCreateSchema):
    """A reviewed PV AI suggestion and an independent confirmation signal.

    The ``confirmed`` flag is deliberately separate from the model suggestion so
    a suggestion cannot self-confirm. A data-changing suggestion is applied only
    when ``confirmed`` is ``True`` (Requirement 22.4).
    """

    suggestion: dict[str, Any] = Field(..., min_length=1)
    confirmed: bool = False


__all__ = [
    "PVAIApplySuggestionRequest",
    "PVAICaseSummaryRequest",
    "PVAIChatMessage",
    "PVAIChatRequest",
    "PVAINarrativeDraftRequest",
]
