"""Focused tests for task 31.1 AI streaming endpoints."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.routes import ai_assistant as ai_routes
from app.api.routes.ai_assistant import chat, draft_edit_check, summarize_query
from app.core.config import Settings
from app.core.exceptions import (
    AuthorizationError,
    ServiceUnavailableError,
)
from app.core.exceptions import (
    ValidationError as DomainValidationError,
)
from app.main import create_app
from app.schemas.ai_assistant import (
    AIChatRequest,
    AIEditCheckDraftRequest,
    AIQuerySummaryRequest,
)
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.ai_assistant_service import AIAssistantService


class FakeProvider:
    def __init__(self, *chunks: str) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, dict]] = []

    async def stream(self, operation, payload):
        self.calls.append((operation, payload))
        for chunk in self.chunks:
            yield chunk


async def _read_stream(response) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)


def _user():
    return SimpleNamespace(id=uuid4())


@pytest.mark.parametrize(
    ("handler", "body", "operation"),
    [
        (chat, AIChatRequest(message="hello"), "chat"),
        (
            draft_edit_check,
            AIEditCheckDraftRequest(prompt="draft an age check"),
            "edit-check-draft",
        ),
        (
            summarize_query,
            AIQuerySummaryRequest(query={"text": "Please clarify the date"}),
            "query-summary",
        ),
    ],
)
async def test_ai_routes_stream_sse_for_each_operation(monkeypatch, handler, body, operation):
    provider = FakeProvider("hello ", "world")
    service = AIAssistantService(provider=provider)
    monkeypatch.setattr(ai_routes, "ai_assistant_service", service)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.get_settings",
        lambda: Settings(ai_assistant_enabled=True),
    )

    response = await handler(body, _user())
    content = await _read_stream(response)

    assert response.media_type == "text/event-stream"
    assert '"type": "token"' in content
    assert '"content": "hello "' in content
    assert '"content": "world"' in content
    assert '"type": "done"' in content
    assert provider.calls[0][0] == operation
    assert provider.calls[0][1]["operation"] == operation


async def test_disabled_ai_assistant_fails_before_streaming(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_assistant_service.get_settings",
        lambda: Settings(ai_assistant_enabled=False),
    )
    service = AIAssistantService(provider=FakeProvider("never"))

    with pytest.raises(ServiceUnavailableError, match="disabled"):
        service.stream("chat", {"message": "hello"}, user_id=uuid4())


def test_ai_routes_are_registered_under_api_v1():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/ai/chat" in paths
    assert "/api/v1/ai/edit-check-draft" in paths
    assert "/api/v1/ai/query-summary" in paths
    assert "/api/v1/ai/apply-suggestion" in paths
    assert all("post" in paths[path] for path in (
        "/api/v1/ai/chat",
        "/api/v1/ai/edit-check-draft",
        "/api/v1/ai/query-summary",
        "/api/v1/ai/apply-suggestion",
    ))


def test_ai_request_schemas_reject_empty_prompts():
    with pytest.raises(ValidationError):
        AIChatRequest(message="")
    with pytest.raises(ValidationError):
        AIEditCheckDraftRequest(prompt="")
    with pytest.raises(ValidationError):
        AIQuerySummaryRequest(query={})


def _scoped_user(study_id, *, site_id=None, permissions=("form.read", "form.enter")):
    return SimpleNamespace(
        id=uuid4(),
        authorization_scope=AuthorizationScope(
            grants=[
                PermissionGrant(
                    permission_code=permission,
                    study_id=study_id,
                    site_id=site_id,
                )
                for permission in permissions
            ]
        ),
    )


def test_build_context_filters_out_of_scope_records_before_provider_payload():
    allowed_study = uuid4()
    denied_study = uuid4()
    user = _scoped_user(allowed_study)
    service = AIAssistantService(provider=FakeProvider())

    context = service.build_context(
        user,
        {
            "message": "summarize the records",
            "context": {
                "items": [
                    {"study_id": str(allowed_study), "value": "allowed"},
                    {"study_id": str(denied_study), "value": "must not be sent"},
                ]
            },
        },
    )

    assert context["message"] == "summarize the records"
    assert context["context"]["items"] == [
        {"study_id": str(allowed_study), "value": "allowed"}
    ]


def test_build_context_rejects_explicit_out_of_scope_target():
    allowed_study = uuid4()
    denied_study = uuid4()
    service = AIAssistantService(provider=FakeProvider())

    with pytest.raises(AuthorizationError):
        service.build_context(
            _scoped_user(allowed_study),
            {"study_id": str(denied_study), "message": "do not disclose data"},
        )


@pytest.mark.asyncio
async def test_apply_suggestion_requires_independent_human_confirmation():
    service = AIAssistantService(provider=FakeProvider())
    apply_calls = []

    with pytest.raises(DomainValidationError, match="Explicit human confirmation"):
        await service.apply_suggestion(
            {
                "target": {"id": str(uuid4()), "study_id": str(uuid4())},
                "changes": {"field": "secret"},
                "confirmed": True,
            },
            confirmed=False,
            apply_change=lambda suggestion: apply_calls.append(suggestion),
        )

    assert apply_calls == []


@pytest.mark.asyncio
async def test_confirmed_ai_change_is_scoped_applied_and_audited(monkeypatch):
    study_id = uuid4()
    target_id = uuid4()
    user = _scoped_user(study_id)
    service = AIAssistantService(provider=FakeProvider())
    audit_calls = []

    async def record_audit(session, **kwargs):
        audit_calls.append((session, kwargs))

    monkeypatch.setattr(
        "app.services.ai_assistant_service.audit_service.record", record_audit
    )

    async def apply_change(suggestion):
        return {"changed": True}

    session = object()
    result = await service.apply_suggestion(
        {
            "target": {
                "id": str(target_id),
                "entity_type": "form_instance",
                "study_id": str(study_id),
            },
            "changes": {"field": "new value"},
            "reason": "Human reviewed the AI suggestion",
        },
        user=user,
        session=session,
        confirmed=True,
        apply_change=apply_change,
    )

    assert result["status"] == "applied"
    assert result["result"] == {"changed": True}
    assert audit_calls[0][0] is session
    assert audit_calls[0][1]["action"] == "ai_assisted_change"
    assert audit_calls[0][1]["entity_id"] == target_id
    assert audit_calls[0][1]["study_id"] == study_id
    assert audit_calls[0][1]["actor_id"] == user.id


async def test_apply_suggestion_route_keeps_confirmation_server_side(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_assistant_service.get_settings",
        lambda: Settings(ai_assistant_enabled=True),
    )
    with pytest.raises(DomainValidationError, match="Explicit human confirmation"):
        await ai_routes.apply_suggestion(
            ai_routes.AIApplySuggestionRequest(
                suggestion={
                    "target": {"id": str(uuid4()), "entity_type": "form_instance"},
                    "changes": {"field": "new"},
                    "confirmed": True,
                },
                confirmed=False,
            ),
            _user(),
            object(),
        )
