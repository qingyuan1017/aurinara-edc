"""Tests for shared module-scoped optional AI controls."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.ctms import Module
from app.core.exceptions import ServiceUnavailableError
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.ai_platform_service import AIPlatformService


def test_ctms_context_minimization_excludes_clinical_payloads() -> None:
    context = AIPlatformService.minimize_context(
        {
            "study_id": str(uuid4()),
            "operational_status": "Active",
            "clinical_data": {"secret": "value"},
            "clinical_quality_signal": {"count": 2},
            "credentials": "never-send",
        },
        module=Module.CTMS,
    )

    assert context["operational_status"] == "Active"
    assert "clinical_data" not in context
    assert "clinical_quality_signal" not in context
    assert "credentials" not in context


def test_ctms_ai_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_platform_service.get_settings",
        lambda: Settings(ai_assistant_enabled=True, ctms_ai_enabled=False),
    )

    with pytest.raises(ServiceUnavailableError):
        AIPlatformService().ensure_enabled(Module.CTMS)


@pytest.mark.asyncio
async def test_confirmed_action_audits_before_owner_callback(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ai_platform_service.get_settings",
        lambda: Settings(ai_assistant_enabled=True, ctms_ai_enabled=True),
    )
    study_id = uuid4()
    actor = SimpleNamespace(id=uuid4())
    scope = AuthorizationScope(
        grants=[
            PermissionGrant(
                permission_code="ctms.operational-data-read",
                study_id=study_id,
            )
        ]
    )
    sequence: list[str] = []

    async def audit(record):
        sequence.append(record["action"])

    async def owner_callback(action):
        assert sequence == ["ai_action_confirmed"]
        return {"accepted": True}

    result = await AIPlatformService().apply_confirmed_action(
        module=Module.CTMS,
        scope=scope,
        permission="ctms.operational-data-read",
        study_id=study_id,
        site_id=None,
        confirmed=True,
        actor=actor,
        action={"operation": "preview"},
        apply_change=owner_callback,
        audit=audit,
    )

    assert result == {"status": "applied", "module": "CTMS", "result": {"accepted": True}}
