"""Streaming AI assistant endpoints.

Satisfies Requirements 31.1 and 31.2.  The routes authenticate and authorize
requests, validate input with Pydantic, then delegate all provider work to the
AI_Assistant_Service.  Responses use Server-Sent Events so clients can render
AgentCore output incrementally.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db, require_permission
from app.core.exceptions import ValidationError
from app.models.identity import User
from app.schemas.ai_assistant import (
    AIApplySuggestionRequest,
    AIChatRequest,
    AIEditCheckDraftRequest,
    AIQuerySummaryRequest,
)
from app.services.ai_assistant_service import ai_assistant_service
from app.services.data_capture_service import data_capture_service

router = APIRouter(prefix="/ai", tags=["ai-assistant"])


async def _stream_response(
    operation: str,
    payload: dict[str, Any],
    current_user: User,
) -> StreamingResponse:
    """Build a standards-compliant SSE response from the AI service."""
    stream = ai_assistant_service.stream(
        operation,
        payload,
        user_id=current_user.id,
        user=current_user,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat", response_class=StreamingResponse)
async def chat(
    body: AIChatRequest,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> StreamingResponse:
    """Stream a general assistant conversation from Bedrock AgentCore."""
    return await _stream_response("chat", body.model_dump(mode="json"), current_user)


@router.post("/edit-check-draft", response_class=StreamingResponse)
async def draft_edit_check(
    body: AIEditCheckDraftRequest,
    current_user: Annotated[User, Depends(require_permission("editcheck.configure"))],
) -> StreamingResponse:
    """Stream an AI-drafted declarative edit check."""
    return await _stream_response(
        "edit-check-draft", body.model_dump(mode="json"), current_user
    )


@router.post("/query-summary", response_class=StreamingResponse)
async def summarize_query(
    body: AIQuerySummaryRequest,
    current_user: Annotated[User, Depends(require_permission("form.read"))],
) -> StreamingResponse:
    """Stream an AI-generated summary of a query."""
    return await _stream_response(
        "query-summary", body.model_dump(mode="json"), current_user
    )


__all__ = ["router"]


@router.post("/apply-suggestion")
async def apply_suggestion(
    body: AIApplySuggestionRequest,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Apply a reviewed AI suggestion inside the caller's transaction.

    The confirmation flag is deliberately separate from the model suggestion.
    For form-instance changes, the target is loaded from the database before the
    service applies it, so object scope and write permission are checked against
    authoritative clinical relationships rather than client-supplied metadata.
    """
    suggestion = body.suggestion
    changes = suggestion.get("data_changes")
    if changes is None:
        changes = suggestion.get("changes")
    if changes and not body.confirmed:
        raise ValidationError(
            message="Explicit human confirmation is required before applying an AI data change",
            details={"requires_confirmation": True},
        )
    target = suggestion.get("target") or suggestion.get("object") or suggestion
    target_type = target.get("entity_type") or target.get("target_type") if isinstance(target, dict) else None
    target_id = target.get("id") or target.get("target_id") if isinstance(target, dict) else None
    target_object: Any | None = None
    if changes and str(target_type).lower().replace("-", "_") == "form_instance":
        if target_id is None:
            raise ValidationError(
                message="AI form suggestions require a persisted target id",
                details={"required": "target.id"},
            )
        target_object = await data_capture_service.load(session, UUID(str(target_id)))

    return await ai_assistant_service.apply_suggestion(
        suggestion,
        user=current_user,
        session=session,
        confirmed=body.confirmed,
        target_object=target_object,
    )
