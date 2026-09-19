"""Property-based coverage for AI human-confirmation and write gating.

# Feature: clinical-edc-system, Property 37: AI data changes require human confirmation
**Validates: Requirements 31.4, 31.5**

For every generated data-changing suggestion, the service must require an
independent confirmation signal, an authenticated user, an in-scope target,
and a clinical write permission. Only the successful path may invoke the
change callback and emit the AI-assisted audit event.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import AuthenticationError, AuthorizationError, ValidationError
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.services.ai_assistant_service import AIAssistantService

_WRITE_PERMISSIONS = ("form.enter", "form.submit", "subject.update")
_OPERATION_KIND = st.sampled_from(
    ("unconfirmed", "unauthenticated", "no_session", "out_of_scope", "read_only", "success")
)
_SCOPE_KIND = st.sampled_from(("system", "study", "site"))
_CHANGE_VALUE = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000, max_value=1_000),
    st.text(max_size=40),
)


@st.composite
def ai_confirmation_scenario(draw):
    """Generate one AI data-change attempt and its expected service outcome."""
    operation = draw(_OPERATION_KIND)
    scope_kind = draw(_SCOPE_KIND)
    study_id = draw(st.uuids())
    site_id = draw(st.uuids())
    wrong_study_id = draw(st.uuids().filter(lambda value: value != study_id))
    wrong_site_id = draw(st.uuids().filter(lambda value: value != site_id))
    target_id = draw(st.uuids())
    field_id = draw(st.uuids())
    value = draw(_CHANGE_VALUE)

    if operation == "out_of_scope":
        # Keep a real write grant, but point it at a different study/site.
        grant_study = wrong_study_id
        grant_site = wrong_site_id if scope_kind == "site" else None
    elif scope_kind == "system":
        grant_study = None
        grant_site = None
    elif scope_kind == "study":
        grant_study = study_id
        grant_site = None
    else:
        grant_study = study_id
        grant_site = site_id

    if operation == "read_only":
        permissions = ("form.read",)
    else:
        permissions = (_WRITE_PERMISSIONS[draw(st.integers(min_value=0, max_value=2))],)

    user = None
    if operation != "unauthenticated":
        user = SimpleNamespace(
            id=draw(st.uuids()),
            authorization_scope=AuthorizationScope(
                grants=[
                    PermissionGrant(
                        permission_code=permission,
                        study_id=grant_study,
                        site_id=grant_site,
                    )
                    for permission in permissions
                ]
            ),
        )

    return {
        "operation": operation,
        "study_id": study_id,
        "site_id": site_id,
        "target_id": target_id,
        "field_id": field_id,
        "value": value,
        "user": user,
        "session": None if operation == "no_session" else object(),
        "confirmed": operation not in {"unconfirmed"},
    }


def _suggestion(scenario: dict[str, object]) -> dict[str, object]:
    """Build a model suggestion whose data-changing intent cannot be ambiguous."""
    return {
        "target": {
            "id": str(scenario["target_id"]),
            "entity_type": "form_instance",
            "study_id": str(scenario["study_id"]),
            "site_id": str(scenario["site_id"]),
        },
        "data_changes": {
            str(scenario["field_id"]): scenario["value"],
        },
        "reason": "Human reviewed generated suggestion",
    }


# Feature: clinical-edc-system, Property 37: AI data changes require human confirmation
@settings(max_examples=100, deadline=None)
@given(scenario=ai_confirmation_scenario())
@pytest.mark.asyncio
async def test_ai_data_changes_require_confirmation_and_authorized_audited_write(scenario):
    """AI changes apply only through the confirmed, scoped, write-capable path.

    **Validates: Requirements 31.4, 31.5**
    """
    service = AIAssistantService()
    suggestion = _suggestion(scenario)
    apply_calls: list[dict[str, object]] = []
    audit = AsyncMock()

    async def apply_change(received: dict[str, object]):
        apply_calls.append(received)
        return {"changed": True}

    with patch("app.services.ai_assistant_service.audit_service.record", audit):
        operation = scenario["operation"]
        if operation == "success":
            result = await service.apply_suggestion(
                suggestion,
                user=scenario["user"],
                session=scenario["session"],
                confirmed=scenario["confirmed"],
                apply_change=apply_change,
            )

            assert result["status"] == "applied"
            assert apply_calls == [suggestion]
            audit.assert_awaited_once()
            audit_kwargs = audit.await_args.kwargs
            assert audit_kwargs["action"] == "ai_assisted_change"
            assert audit_kwargs["entity_id"] == scenario["target_id"]
            assert audit_kwargs["study_id"] == scenario["study_id"]
            assert audit_kwargs["site_id"] == scenario["site_id"]
            assert audit_kwargs["actor_id"] == scenario["user"].id
            return

        expected_error = {
            "unconfirmed": ValidationError,
            "unauthenticated": AuthenticationError,
            "no_session": ValidationError,
            "out_of_scope": AuthorizationError,
            "read_only": AuthorizationError,
        }[operation]
        with pytest.raises(expected_error):
            await service.apply_suggestion(
                suggestion,
                user=scenario["user"],
                session=scenario["session"],
                confirmed=scenario["confirmed"],
                apply_change=apply_change,
            )

    assert apply_calls == []
    audit.assert_not_awaited()
