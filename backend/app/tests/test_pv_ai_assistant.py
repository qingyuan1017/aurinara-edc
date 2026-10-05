"""Tests for the optional PV-scoped AI assistant (task 8.3, Requirement 22).

These exercise the shared AI controls as bound to the PV module:

  - enablement gating by ``ai_assistant_enabled`` and ``pv_ai_enabled`` (22.1),
  - streaming SSE with terminal ``done``/``error`` events (22.2, 22.6),
  - PV context minimization and out-of-scope denial before any provider call
    (22.3),
  - explicit human confirmation before a Safety_Data change (22.4),
  - one PV safety Audit_Event with AI-assisted origin for a confirmed change
    (22.5), and
  - the PV assistant never mutating an EDC clinical or CTMS operational record.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.ctms import Module
from app.core.exceptions import (
    AuthorizationError,
    ServiceUnavailableError,
)
from app.core.exceptions import (
    ValidationError as DomainValidationError,
)
from app.main import create_app
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.schemas.pv.ai import (
    PVAICaseSummaryRequest,
    PVAIChatRequest,
    PVAINarrativeDraftRequest,
)
from app.services.ai_assistant_service import AIAssistantService


class FakeProvider:
    def __init__(self, *chunks: str) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, dict]] = []

    async def stream(self, operation, payload):
        self.calls.append((operation, payload))
        for chunk in self.chunks:
            yield chunk


class FailingProvider:
    async def stream(self, operation, payload):
        from app.services.ai_assistant_service import AIProviderError

        if False:  # pragma: no cover - keeps this an async generator
            yield ""
        raise AIProviderError("provider exploded before completion")


async def _read_stream(stream) -> str:
    return "".join([chunk async for chunk in stream])


def _pv_service(provider) -> AIAssistantService:
    return AIAssistantService(provider=provider, module=Module.PV)


def _enable_pv_ai(monkeypatch, *, enabled: bool = True, pv_ai: bool = True) -> None:
    settings = Settings(ai_assistant_enabled=enabled, pv_ai_enabled=pv_ai)
    monkeypatch.setattr(
        "app.services.ai_assistant_service.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.services.ai_platform_service.get_settings", lambda: settings
    )


def _scoped_user(study_id, *, site_id=None, permissions=("safety_case.read",)):
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


# --- Requirement 22.1: enablement gating -----------------------------------


def test_pv_ai_disabled_by_default(monkeypatch):
    _enable_pv_ai(monkeypatch, enabled=True, pv_ai=False)
    service = _pv_service(FakeProvider("never"))

    with pytest.raises(ServiceUnavailableError, match="disabled"):
        service.stream("pv-chat", {"message": "hello"}, user_id=uuid4())


def test_pv_ai_disabled_when_platform_ai_off(monkeypatch):
    _enable_pv_ai(monkeypatch, enabled=False, pv_ai=True)
    service = _pv_service(FakeProvider("never"))

    with pytest.raises(ServiceUnavailableError, match="disabled"):
        service.stream("pv-chat", {"message": "hello"}, user_id=uuid4())


def test_pv_ai_routes_absent_when_disabled():
    paths = create_app().openapi()["paths"]

    assert "/api/v1/pv/ai/chat" not in paths
    assert "/api/v1/pv/ai/narrative-draft" not in paths
    assert "/api/v1/pv/ai/case-summary" not in paths


def test_pv_ai_routes_present_when_enabled(monkeypatch):
    from app import main

    monkeypatch.setattr(
        main, "get_settings", lambda: Settings(ai_assistant_enabled=True, pv_ai_enabled=True)
    )
    paths = main.create_app().openapi()["paths"]

    assert "/api/v1/pv/ai/chat" in paths
    assert "/api/v1/pv/ai/narrative-draft" in paths
    assert "/api/v1/pv/ai/case-summary" in paths
    assert "/api/v1/pv/ai/apply-suggestion" in paths


# --- Requirement 22.2 / 22.6: streaming and terminal events -----------------


@pytest.mark.asyncio
async def test_pv_chat_streams_tokens_and_done(monkeypatch):
    _enable_pv_ai(monkeypatch)
    provider = FakeProvider("draft ", "narrative")
    service = _pv_service(provider)

    content = await _read_stream(
        service.stream("pv-chat", {"message": "summarize case"}, user_id=uuid4())
    )

    assert '"type": "token"' in content
    assert '"content": "draft "' in content
    assert '"type": "done"' in content
    assert provider.calls[0][0] == "pv-chat"


@pytest.mark.asyncio
async def test_pv_stream_emits_error_on_provider_failure(monkeypatch):
    _enable_pv_ai(monkeypatch)
    service = _pv_service(FailingProvider())

    content = await _read_stream(
        service.stream("pv-case-summary", {"message": "summ"}, user_id=uuid4())
    )

    assert "event: error" in content
    assert '"type": "error"' in content
    assert '"type": "done"' not in content


# --- Requirement 22.3: context minimization and scope denial ----------------


def test_pv_context_excludes_edc_and_ctms_payloads(monkeypatch):
    _enable_pv_ai(monkeypatch)
    study_id = uuid4()
    user = _scoped_user(study_id)
    service = _pv_service(FakeProvider())

    context = service.build_context(
        user,
        {
            "study_id": str(study_id),
            "message": "summarize the safety case",
            "clinical_data": {"secret": "value"},
            "operational_status": "Active",
            "edc_field_values": [{"value": "x"}],
            "field_values": [{"value": "y"}],
            "credentials": "never-send",
        },
    )

    assert context["message"] == "summarize the safety case"
    assert "clinical_data" not in context
    assert "operational_status" not in context
    assert "edc_field_values" not in context
    assert "field_values" not in context
    assert "credentials" not in context


def test_pv_build_context_rejects_out_of_scope_target(monkeypatch):
    _enable_pv_ai(monkeypatch)
    allowed_study = uuid4()
    denied_study = uuid4()
    service = _pv_service(FakeProvider())

    with pytest.raises(AuthorizationError):
        service.build_context(
            _scoped_user(allowed_study),
            {"study_id": str(denied_study), "message": "do not disclose data"},
        )


# --- Requirement 22.4: explicit human confirmation --------------------------


@pytest.mark.asyncio
async def test_pv_apply_requires_independent_confirmation():
    service = _pv_service(FakeProvider())
    applied: list = []

    with pytest.raises(DomainValidationError, match="Explicit human confirmation"):
        await service.apply_suggestion(
            {
                "target": {"id": str(uuid4()), "study_id": str(uuid4()),
                           "entity_type": "case_narrative"},
                "changes": {"text": "new narrative"},
            },
            confirmed=False,
            apply_change=lambda s: applied.append(s),
        )

    assert applied == []


@pytest.mark.asyncio
async def test_pv_apply_requires_owner_callback():
    service = _pv_service(FakeProvider())
    study_id = uuid4()
    user = _scoped_user(study_id, permissions=("safety_narrative.write",))

    with pytest.raises(DomainValidationError, match="owning-service callback"):
        await service.apply_suggestion(
            {
                "target": {"id": str(uuid4()), "study_id": str(study_id),
                           "entity_type": "case_narrative"},
                "changes": {"text": "new narrative"},
            },
            user=user,
            session=object(),
            confirmed=True,
            apply_change=None,
        )


# --- Requirement 22.5: audit origin for confirmed change --------------------


@pytest.mark.asyncio
async def test_pv_confirmed_change_is_scoped_applied_and_pv_audited(monkeypatch):
    study_id = uuid4()
    target_id = uuid4()
    user = _scoped_user(study_id, permissions=("safety_narrative.write",))
    service = _pv_service(FakeProvider())
    audit_calls: list = []

    async def record_mutation(session, **kwargs):
        audit_calls.append((session, kwargs))
        return SimpleNamespace(audit=None, outbox=None)

    monkeypatch.setattr(
        "app.services.ai_assistant_service.pv_atomicity_service.record_mutation",
        record_mutation,
    )

    async def apply_change(_suggestion):
        return {"narrative_id": str(target_id)}

    session = object()
    result = await service.apply_suggestion(
        {
            "target": {
                "id": str(target_id),
                "entity_type": "case_narrative",
                "study_id": str(study_id),
            },
            "changes": {"text": "AI-drafted narrative"},
            "reason": "Human reviewed the AI narrative",
        },
        user=user,
        session=session,
        confirmed=True,
        apply_change=apply_change,
    )

    assert result["status"] == "applied"
    assert result["result"] == {"narrative_id": str(target_id)}
    assert len(audit_calls) == 1
    session_arg, kwargs = audit_calls[0]
    assert session_arg is session
    assert kwargs["action"] == "ai_assisted_change"
    assert kwargs["entity_type"] == "case_narrative"
    assert kwargs["entity_id"] == target_id
    assert kwargs["study_id"] == study_id
    assert kwargs["actor_id"] == user.id


@pytest.mark.asyncio
async def test_pv_confirmed_change_denied_without_write_scope(monkeypatch):
    study_id = uuid4()
    # Read-only user: holds safety_case.read but no safety write permission.
    user = _scoped_user(study_id, permissions=("safety_case.read",))
    service = _pv_service(FakeProvider())

    async def apply_change(_suggestion):  # pragma: no cover - must not run
        raise AssertionError("apply_change must not run without write scope")

    with pytest.raises(AuthorizationError):
        await service.apply_suggestion(
            {
                "target": {
                    "id": str(uuid4()),
                    "entity_type": "case_narrative",
                    "study_id": str(study_id),
                },
                "changes": {"text": "should not persist"},
            },
            user=user,
            session=object(),
            confirmed=True,
            apply_change=apply_change,
        )


# --- Request schema validation ----------------------------------------------


def test_pv_ai_schemas_reject_empty_prompts():
    with pytest.raises(ValidationError):
        PVAIChatRequest(message="")
    with pytest.raises(ValidationError):
        PVAINarrativeDraftRequest(case_id=uuid4(), prompt="")


def test_pv_case_summary_requires_case_id():
    with pytest.raises(ValidationError):
        PVAICaseSummaryRequest()  # type: ignore[call-arg]
