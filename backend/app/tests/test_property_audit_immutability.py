"""Property-based test for audit trail immutability.

**Validates: Requirements 18.2**

Property 18: The audit trail is immutable.

Generates arbitrary AuditEvent payloads and verifies the application-layer
immutability guarantee:
1. AuditService only exposes record(), search(), and export() — no update()
   or delete() methods exist.
2. AuditService.record() only uses session.add() and session.flush() — it
   never calls session.delete() or modifies existing event attributes.
3. Random audit payloads round-trip through record() without mutation support.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.audit import AuditService
from app.models.audit import AuditEvent

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Constrained strings for entity_type / action fields
entity_type_strategy = st.sampled_from([
    "subject",
    "form_instance",
    "form_record",
    "study",
    "site",
    "visit_instance",
    "field_value",
    "query",
    "export_job",
    "user",
    "role",
    "edit_check",
])

action_strategy = st.sampled_from([
    "create",
    "update",
    "delete",
    "submit",
    "sign",
    "lock",
    "freeze",
    "reopen",
    "review",
    "export",
    "upload",
    "download",
])

# Optional text fields (field_name, old_value, new_value, reason)
optional_text = st.one_of(st.none(), st.text(min_size=1, max_size=200))

# Optional UUIDs for scoping
optional_uuid = st.one_of(st.none(), st.uuids())

# IP addresses
ip_strategy = st.one_of(
    st.none(),
    st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
)

# User agent strings
user_agent_strategy = st.one_of(st.none(), st.text(min_size=1, max_size=100))


@st.composite
def audit_payload_strategy(draw):
    """Generate an arbitrary audit event payload."""
    return {
        "entity_type": draw(entity_type_strategy),
        "entity_id": draw(st.uuids()),
        "action": draw(action_strategy),
        "study_id": draw(optional_uuid),
        "site_id": draw(optional_uuid),
        "subject_id": draw(optional_uuid),
        "field_name": draw(optional_text),
        "old_value": draw(optional_text),
        "new_value": draw(optional_text),
        "reason": draw(optional_text),
        "actor_id": draw(st.uuids()),
        "actor_email": draw(st.one_of(st.none(), st.emails())),
        "request_id": str(draw(st.uuids())),
        "ip_address": draw(ip_strategy),
        "user_agent": draw(user_agent_strategy),
    }


# ---------------------------------------------------------------------------
# Property 18: The audit trail is immutable
# ---------------------------------------------------------------------------


class TestAuditImmutabilityProperties:
    """Property-based tests for audit trail immutability.

    **Validates: Requirements 18.2**
    """

    def test_no_update_method_on_service(self):
        """AuditService MUST NOT expose an update() method."""
        service = AuditService()
        assert not hasattr(service, "update"), (
            "AuditService must not have an 'update' method"
        )

    def test_no_delete_method_on_service(self):
        """AuditService MUST NOT expose a delete() method."""
        service = AuditService()
        assert not hasattr(service, "delete"), (
            "AuditService must not have a 'delete' method"
        )

    def test_no_remove_method_on_service(self):
        """AuditService MUST NOT expose a remove() method."""
        service = AuditService()
        assert not hasattr(service, "remove"), (
            "AuditService must not have a 'remove' method"
        )

    def test_no_modify_method_on_service(self):
        """AuditService MUST NOT expose a modify() method."""
        service = AuditService()
        assert not hasattr(service, "modify"), (
            "AuditService must not have a 'modify' method"
        )

    def test_only_allowed_public_methods(self):
        """AuditService public methods are strictly record, search, and export."""
        service = AuditService()
        allowed = {"record", "search", "export"}

        public_methods = {
            name
            for name, _ in inspect.getmembers(service, predicate=inspect.ismethod)
            if not name.startswith("_")
        }

        # Every public method must be in the allowed set
        disallowed = public_methods - allowed
        assert disallowed == set(), (
            f"AuditService has disallowed public methods: {disallowed}. "
            f"Only {allowed} are permitted for immutability."
        )

    def test_record_source_contains_no_session_delete(self):
        """The record() method source MUST NOT reference session.delete."""
        source = inspect.getsource(AuditService.record)
        assert "session.delete" not in source, (
            "AuditService.record() must never call session.delete()"
        )
        assert ".delete(" not in source, (
            "AuditService.record() must not call any delete method"
        )

    def test_record_source_contains_session_add(self):
        """The record() method source MUST use session.add() for appending."""
        source = inspect.getsource(AuditService.record)
        assert "session.add(" in source, (
            "AuditService.record() must use session.add() to persist events"
        )

    def test_record_source_contains_session_flush(self):
        """The record() method source MUST use session.flush() (not commit)."""
        source = inspect.getsource(AuditService.record)
        assert "session.flush()" in source or "await session.flush()" in source, (
            "AuditService.record() must flush within the caller's transaction"
        )

    def test_record_source_does_not_commit(self):
        """The record() method MUST NOT call session.commit() directly."""
        source = inspect.getsource(AuditService.record)
        assert "session.commit" not in source, (
            "AuditService.record() must not commit — the caller owns the transaction"
        )

    @settings(max_examples=100, deadline=None)
    @given(payload=audit_payload_strategy())
    async def test_record_only_calls_add_and_flush(self, payload):
        """For any audit payload, record() only calls session.add and session.flush.

        **Validates: Requirements 18.2**

        Verifies that:
        - session.add is called exactly once with the created event
        - session.flush is called exactly once
        - session.delete is NEVER called
        - session.execute is NEVER called (no raw UPDATE/DELETE)
        - session.commit is NEVER called
        """
        service = AuditService()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.delete = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("app.core.audit.get_actor", return_value=payload["actor_id"]):
            with patch("app.core.audit.get_request_id", return_value=payload["request_id"]):
                event = await service.record(
                    mock_session,
                    entity_type=payload["entity_type"],
                    entity_id=payload["entity_id"],
                    action=payload["action"],
                    study_id=payload["study_id"],
                    site_id=payload["site_id"],
                    subject_id=payload["subject_id"],
                    field_name=payload["field_name"],
                    old_value=payload["old_value"],
                    new_value=payload["new_value"],
                    reason=payload["reason"],
                    actor_id=payload["actor_id"],
                    actor_email=payload["actor_email"],
                    request_id=payload["request_id"],
                    ip_address=payload["ip_address"],
                    user_agent=payload["user_agent"],
                )

        # Append-only: add called exactly once
        mock_session.add.assert_called_once_with(event)
        # Flush for ID assignment, but no commit (caller's tx boundary)
        mock_session.flush.assert_awaited_once()
        # Immutability: delete/execute/commit NEVER called
        mock_session.delete.assert_not_called()
        mock_session.execute.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @settings(max_examples=100, deadline=None)
    @given(payload=audit_payload_strategy())
    async def test_record_returns_correct_event_data(self, payload):
        """For any audit payload, record() returns an AuditEvent with matching fields.

        **Validates: Requirements 18.2**

        Verifies that the returned event faithfully captures the input payload
        without any transformation that could indicate mutation support.
        """
        service = AuditService()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        with patch("app.core.audit.get_actor", return_value=payload["actor_id"]):
            with patch("app.core.audit.get_request_id", return_value=payload["request_id"]):
                event = await service.record(
                    mock_session,
                    entity_type=payload["entity_type"],
                    entity_id=payload["entity_id"],
                    action=payload["action"],
                    study_id=payload["study_id"],
                    site_id=payload["site_id"],
                    subject_id=payload["subject_id"],
                    field_name=payload["field_name"],
                    old_value=payload["old_value"],
                    new_value=payload["new_value"],
                    reason=payload["reason"],
                    actor_id=payload["actor_id"],
                    actor_email=payload["actor_email"],
                    request_id=payload["request_id"],
                    ip_address=payload["ip_address"],
                    user_agent=payload["user_agent"],
                )

        # The returned event is an AuditEvent instance
        assert isinstance(event, AuditEvent)
        # All fields match the input (write-once semantics)
        assert event.entity_type == payload["entity_type"]
        assert event.entity_id == payload["entity_id"]
        assert event.action == payload["action"]
        assert event.study_id == payload["study_id"]
        assert event.site_id == payload["site_id"]
        assert event.subject_id == payload["subject_id"]
        assert event.field_name == payload["field_name"]
        assert event.old_value == payload["old_value"]
        assert event.new_value == payload["new_value"]
        assert event.reason == payload["reason"]
        assert event.actor_id == payload["actor_id"]
        assert event.actor_email == payload["actor_email"]
        # request_id is stored as UUID; compare string representations
        assert str(event.request_id) == payload["request_id"]
        assert event.ip_address == payload["ip_address"]
        assert event.user_agent == payload["user_agent"]

    @settings(max_examples=100)
    @given(payload=audit_payload_strategy())
    def test_audit_event_model_has_no_mutable_helpers(self, payload):
        """AuditEvent model instances must not expose update/save/delete helpers.

        **Validates: Requirements 18.2**

        For any generated payload, an AuditEvent instance must lack methods
        that could mutate persisted audit data.
        """
        event = AuditEvent(
            entity_type=payload["entity_type"],
            entity_id=payload["entity_id"],
            action=payload["action"],
            study_id=payload["study_id"],
            site_id=payload["site_id"],
            subject_id=payload["subject_id"],
            field_name=payload["field_name"],
            old_value=payload["old_value"],
            new_value=payload["new_value"],
            reason=payload["reason"],
            actor_id=payload["actor_id"],
            actor_email=payload["actor_email"],
            request_id=payload["request_id"] or str(uuid.uuid4()),
            ip_address=payload["ip_address"],
            user_agent=payload["user_agent"],
        )

        # Model must not have custom update/delete/save methods
        # (SQLAlchemy models don't have these by default, but we verify
        # no one has added them to AuditEvent)
        assert not hasattr(event, "update"), (
            "AuditEvent must not have an 'update' method"
        )
        assert not hasattr(event, "delete"), (
            "AuditEvent must not have a 'delete' method"
        )
        assert not hasattr(event, "save"), (
            "AuditEvent must not have a 'save' method — use session.add() only"
        )
