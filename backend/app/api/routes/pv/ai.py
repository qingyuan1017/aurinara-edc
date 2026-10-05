"""Optional PV-scoped streaming AI assistant routes.

Satisfies Requirement 22. These authenticated routes under ``/api/v1/pv/ai``
expose PV-scoped chat, narrative drafting, and case summarization backed by AWS
Bedrock AgentCore, but only while the optional assistant is enabled
(``ai_assistant_enabled`` and ``pv_ai_enabled``). When the assistant is
disabled the service raises before any provider call, so no operation is
exposed (Requirement 22.1).

Shared AI controls apply on every route:

  - Context minimization: only in-scope PV safety context is sent to the model;
    EDC clinical and CTMS operational payloads are stripped, and an explicit
    out-of-scope target is rejected without sending context (Requirement 22.3).
  - Human confirmation: an AI suggestion that would change PV Safety_Data is
    applied only after a separate, explicit human confirmation signal; a
    declined or absent confirmation applies no change (Requirement 22.4).
  - Audit hooks: a confirmed AI-assisted change records exactly one PV safety
    Audit_Event identifying the user, the changed safety object, the action, and
    the AI-assisted origin, on the caller's transaction (Requirement 22.5).
  - PV-scoped authorization: the shared ``Permission_Service`` guards resolve a
    PV permission at the target scope; PV roles hold no EDC/CTMS mutation code,
    so a PV AI change can never mutate an EDC clinical or CTMS operational
    record (Requirements 22.3, 23.4, 23.5).

Streaming responses use Server-Sent Events so a client can render output
incrementally and observe a terminal ``done`` or ``error`` event; a provider or
stream failure emits an ``error`` event and applies no change (Requirement 22.6).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_pv_permission
from app.api.routes.pv._common import build_actor
from app.core.exceptions import NotFoundError, ValidationError
from app.models.identity import User
from app.repositories.pv.safety_case_repository import SafetyCaseRepository
from app.schemas.pv.ai import (
    PVAIApplySuggestionRequest,
    PVAICaseSummaryRequest,
    PVAIChatRequest,
    PVAINarrativeDraftRequest,
)
from app.services.ai_assistant_service import pv_ai_assistant_service
from app.services.narrative_service import narrative_service

router = APIRouter(prefix="/ai", tags=["pv-ai-assistant"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
# Reading PV safety context (chat, summarization, narrative drafting preview)
# requires PV read access; applying a confirmed narrative change requires the
# PV narrative write permission, enforced again in the service.
ReadGuard = Annotated[User, Depends(require_pv_permission("safety_case.read"))]
NarrativeGuard = Annotated[User, Depends(require_pv_permission("safety_narrative.write"))]


def _stream_response(
    operation: str,
    payload: dict[str, Any],
    current_user: User,
) -> StreamingResponse:
    """Build a standards-compliant SSE response from the PV AI service."""

    stream = pv_ai_assistant_service.stream(
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
    body: PVAIChatRequest,
    current_user: ReadGuard,
) -> StreamingResponse:
    """Stream a PV-scoped assistant conversation from Bedrock AgentCore."""

    return _stream_response("pv-chat", body.model_dump(mode="json"), current_user)


@router.post("/narrative-draft", response_class=StreamingResponse)
async def draft_narrative(
    body: PVAINarrativeDraftRequest,
    current_user: NarrativeGuard,
) -> StreamingResponse:
    """Stream an AI-drafted Case_Narrative for a Safety_Case.

    The stream returns a draft only. Persisting the draft to Safety_Data
    requires the separate ``/pv/ai/apply-suggestion`` call with an explicit
    human confirmation (Requirement 22.4).
    """

    return _stream_response(
        "pv-narrative-draft", body.model_dump(mode="json"), current_user
    )


@router.post("/case-summary", response_class=StreamingResponse)
async def summarize_case(
    body: PVAICaseSummaryRequest,
    current_user: ReadGuard,
) -> StreamingResponse:
    """Stream an AI-generated summary of a Safety_Case."""

    return _stream_response(
        "pv-case-summary", body.model_dump(mode="json"), current_user
    )


@router.post("/apply-suggestion")
async def apply_suggestion(
    body: PVAIApplySuggestionRequest,
    current_user: NarrativeGuard,
    session: DbSession,
) -> dict[str, Any]:
    """Apply a reviewed PV AI narrative suggestion inside the caller's transaction.

    The confirmation flag is separate from the model suggestion. A data-changing
    suggestion without confirmation is rejected before any state change
    (Requirement 22.4). A supported suggestion applies a Case_Narrative through
    the owning ``Narrative_Service`` (never through the AI boundary directly),
    and the shared service records exactly one PV safety Audit_Event with the
    AI-assisted origin on the same transaction (Requirement 22.5).
    """

    suggestion = body.suggestion
    changes = suggestion.get("data_changes")
    if changes is None:
        changes = suggestion.get("changes")
    is_data_change = bool(changes) or bool(
        suggestion.get("would_change_data") or suggestion.get("data_change")
    )
    if is_data_change and not body.confirmed:
        raise ValidationError(
            message="Explicit human confirmation is required before applying an AI data change",
            details={"requires_confirmation": True},
        )

    target = suggestion.get("target") or suggestion.get("object") or suggestion
    target_type = (
        str(target.get("entity_type") or target.get("target_type") or "")
        if isinstance(target, dict)
        else ""
    ).lower().replace("-", "_")

    apply_change = None
    if is_data_change:
        if target_type not in {"case_narrative", "narrative"}:
            raise ValidationError(
                message="Only Case_Narrative suggestions can be applied through the PV assistant",
                details={"supported_target": "case_narrative"},
            )
        # Resolve the target Safety_Case scope from authoritative PV state so
        # the scope and write-permission checks in the shared service run
        # against real relationships rather than client-supplied metadata.
        await _bind_authoritative_scope(session, suggestion, target)
        apply_change = _build_narrative_apply(session, suggestion, current_user)

    return await pv_ai_assistant_service.apply_suggestion(
        suggestion,
        user=current_user,
        session=session,
        confirmed=body.confirmed,
        apply_change=apply_change,
    )


async def _bind_authoritative_scope(
    session: AsyncSession, suggestion: dict[str, Any], target: Any
) -> None:
    """Stamp the suggestion target with authoritative Safety_Case scope.

    A narrative suggestion identifies either a ``case_id`` (new narrative) or a
    ``narrative_id`` (revision). The owning Safety_Case's canonical study/site
    scope and a persisted entity id are resolved from PV state and written back
    onto the target so the shared service authorizes the change against the real
    record and never trusts client-supplied scope.
    """

    if not isinstance(target, dict):
        raise ValidationError(
            message="A narrative suggestion target must be an object",
            details={"required": "target.case_id or target.narrative_id"},
        )

    narrative_id = target.get("narrative_id")
    case_id = target.get("case_id")
    from app.repositories.pv.narrative_repository import NarrativeRepository

    if narrative_id is not None:
        narrative = await NarrativeRepository(session).get_narrative(UUID(str(narrative_id)))
        if narrative is None:
            raise NotFoundError(
                message="Case_Narrative was not found",
                details={"reason": "RECORD_NOT_FOUND", "entity_type": "case_narrative"},
            )
        case_id = narrative.case_id
        target.setdefault("id", str(narrative.id))
        target["entity_type"] = "case_narrative"
    elif case_id is None:
        raise ValidationError(
            message="A narrative suggestion must identify a case_id or narrative_id",
            details={"required": "target.case_id or target.narrative_id"},
        )

    study_id, site_id, subject_reference = await _load_case_scope(session, UUID(str(case_id)))
    target["study_id"] = str(study_id)
    target["site_id"] = str(site_id)
    target["subject_id"] = str(subject_reference)
    target.setdefault("id", str(case_id))
    target.setdefault("entity_type", "case_narrative")
    suggestion["target"] = target


def _build_narrative_apply(session: AsyncSession, suggestion: dict[str, Any], current_user: User):
    """Return a callback that applies the confirmed narrative through PV service.

    The callback runs inside the shared service after scope and write-permission
    checks pass. Passing the owning-service callback keeps mutation authority
    with the PV ``Narrative_Service``; the AI boundary never writes PV records
    itself (Requirements 22.4, 22.5).
    """

    async def _apply(reviewed: dict[str, Any]) -> dict[str, Any]:
        target = reviewed.get("target") or reviewed.get("object") or reviewed
        text = target.get("text") if isinstance(target, dict) else None
        if text is None:
            text = reviewed.get("text")
        narrative_id = target.get("narrative_id") if isinstance(target, dict) else None
        case_id = target.get("case_id") if isinstance(target, dict) else None
        reason = str(
            reviewed.get("reason")
            or "AI-assisted narrative explicitly confirmed by a human"
        )
        actor = build_actor(current_user)

        if narrative_id is not None:
            version = await narrative_service.revise(
                session,
                narrative_id=UUID(str(narrative_id)),
                text=str(text),
                reason_for_change=reason,
                actor=actor,
            )
            return {"narrative_id": str(version.narrative_id), "version_id": str(version.id)}

        if case_id is None:
            raise ValidationError(
                message="A narrative suggestion must identify a case_id or narrative_id",
                details={"required": "target.case_id or target.narrative_id"},
            )
        narrative = await narrative_service.create(
            session,
            case_id=UUID(str(case_id)),
            text=str(text),
            actor=actor,
        )
        return {"narrative_id": str(narrative.id)}

    return _apply


async def _load_case_scope(session: AsyncSession, case_id: UUID) -> tuple[UUID, UUID, UUID]:
    """Resolve a Safety_Case's canonical scope, rejecting an unknown case."""

    case = await SafetyCaseRepository(session).get_case(case_id)
    if case is None:
        raise NotFoundError(
            message="Safety_Case was not found",
            details={"reason": "RECORD_NOT_FOUND", "entity_type": "safety_case"},
        )
    return case.study_id, case.site_id, case.subject_reference


__all__ = ["router"]
