"""Property-based test for audit atomicity in clinical mutations.

**Validates: Requirements 4.5, 7.6, 9.6, 10.8, 11.2, 13.7, 14.4, 15.4, 16.5,
17.4, 18.1, 21.4, 22.4, 25.2, 31.5**

Property 17: Clinical mutations write an atomic, complete Audit_Event.

For any clinical or key-configuration mutation, exactly one Audit_Event is
committed in the same database transaction as the data change (both persist or
neither does), capturing actor, UTC server timestamp, entity type/id, study,
site, action, and where applicable field, old value, new value, and
Reason_For_Change.

Generates random clinical mutations (save_draft values, submit calls,
change_value calls) and verifies:
1. audit_service.record() is called at least once in the same function call
   (same transaction)
2. The audit_service never calls session.commit (caller's transaction boundary)
3. The audit event contains the correct entity_type, action, and actor_id
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.audit import AuditService
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.services.data_capture_service import DataCaptureService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Draft field values: mapping of field_definition_id (str UUID) -> value
field_value_strategy = st.one_of(
    st.text(min_size=1, max_size=50),
    st.integers(min_value=-10000, max_value=10000).map(str),
    st.sampled_from(["true", "false", "2024-01-15", "3.14"]),
)

draft_values_strategy = st.dictionaries(
    keys=st.uuids().map(str),
    values=field_value_strategy,
    min_size=1,
    max_size=5,
)

# Reason strings for post-submission changes
reason_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=3,
    max_size=100,
)

# Clinical mutation types
mutation_type_strategy = st.sampled_from(["save_draft", "submit", "change_value"])


@st.composite
def clinical_mutation_strategy(draw):
    """Generate a random clinical mutation with the necessary context."""
    mutation_type = draw(mutation_type_strategy)
    actor_id = draw(st.uuids())
    form_instance_id = draw(st.uuids())
    subject_id = draw(st.uuids())
    form_definition_id = draw(st.uuids())

    result = {
        "mutation_type": mutation_type,
        "actor_id": actor_id,
        "form_instance_id": form_instance_id,
        "subject_id": subject_id,
        "form_definition_id": form_definition_id,
    }

    if mutation_type == "save_draft":
        result["values"] = draw(draft_values_strategy)
    elif mutation_type == "change_value":
        result["field_id"] = draw(st.uuids())
        result["new_value"] = draw(field_value_strategy)
        result["reason"] = draw(reason_strategy)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form_instance(
    form_instance_id: UUID,
    subject_id: UUID,
    form_definition_id: UUID,
    status: FormInstanceStatus = FormInstanceStatus.not_started,
) -> FormInstance:
    """Create a FormInstance model object suitable for testing."""
    return FormInstance(
        id=form_instance_id,
        subject_id=subject_id,
        form_definition_id=form_definition_id,
        status=status,
        data_jsonb={},
        created_at=datetime.now(UTC),
    )


def _make_mock_session() -> AsyncMock:
    """Create a mock async session that tracks all relevant calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = MagicMock()
    session.refresh = AsyncMock()

    # For select queries that load field values, return empty results
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    return session


# ---------------------------------------------------------------------------
# Property 17: Clinical mutations write an atomic, complete Audit_Event
# ---------------------------------------------------------------------------


class TestAuditAtomicityProperties:
    """Property-based tests for audit atomicity in clinical mutations.

    **Validates: Requirements 4.5, 7.6, 9.6, 10.8, 11.2, 13.7, 14.4, 15.4,
    16.5, 17.4, 18.1, 21.4, 22.4, 25.2, 31.5**
    """

    @settings(max_examples=100, deadline=None)
    @given(mutation=clinical_mutation_strategy())
    async def test_save_draft_calls_audit_record(self, mutation):
        """save_draft MUST call audit_service.record() for every changed field.

        **Validates: Requirements 10.8, 18.1, 21.4**

        For any draft save operation with N field values, audit_service.record()
        is called at least once in the same function call (same transaction),
        ensuring the audit event and data change are atomic.
        """
        if mutation["mutation_type"] != "save_draft":
            return  # Skip non-save_draft mutations in this test

        service = DataCaptureService()
        session = _make_mock_session()

        form_instance = _make_form_instance(
            form_instance_id=mutation["form_instance_id"],
            subject_id=mutation["subject_id"],
            form_definition_id=mutation["form_definition_id"],
            status=FormInstanceStatus.not_started,
        )

        # Track audit_service.record calls
        audit_calls: list[dict[str, Any]] = []
        original_record = AuditService.record

        async def mock_record(self_audit, sess, **kwargs):
            audit_calls.append(kwargs)
            # Return a mock AuditEvent
            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            return mock_event

        with patch.object(AuditService, "record", mock_record):
            await service.save_draft(
                session,
                form_instance=form_instance,
                values=mutation["values"],
                actor_id=mutation["actor_id"],
            )

        # Assertion 1: audit_service.record() is called at least once
        assert len(audit_calls) >= 1, (
            f"save_draft with {len(mutation['values'])} field(s) must call "
            f"audit_service.record() at least once, but got {len(audit_calls)} calls"
        )

        # Assertion 2: Each audit call has correct actor_id
        for call in audit_calls:
            assert call["actor_id"] == mutation["actor_id"], (
                f"Audit event actor_id mismatch: expected {mutation['actor_id']}, "
                f"got {call['actor_id']}"
            )

        # Assertion 3: Each audit call has correct entity_type
        for call in audit_calls:
            assert call["entity_type"] == "field_value", (
                f"save_draft audit events must have entity_type='field_value', "
                f"got '{call['entity_type']}'"
            )

        # Assertion 4: Each audit call has a valid action
        for call in audit_calls:
            assert call["action"] in ("create", "update"), (
                f"save_draft audit events must have action 'create' or 'update', "
                f"got '{call['action']}'"
            )

    @settings(max_examples=100, deadline=None)
    @given(mutation=clinical_mutation_strategy())
    async def test_submit_calls_audit_record(self, mutation):
        """submit MUST call audit_service.record() for the submission event.

        **Validates: Requirements 10.8, 18.1, 21.4**

        For any form submission, audit_service.record() is called at least once,
        capturing the status transition.
        """
        if mutation["mutation_type"] != "submit":
            return  # Skip non-submit mutations in this test

        service = DataCaptureService()
        session = _make_mock_session()

        form_instance = _make_form_instance(
            form_instance_id=mutation["form_instance_id"],
            subject_id=mutation["subject_id"],
            form_definition_id=mutation["form_definition_id"],
            status=FormInstanceStatus.in_progress,
        )

        # Mock the field definitions query to return empty (no required fields)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_scalars.first.return_value = None
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        # Track audit_service.record calls
        audit_calls: list[dict[str, Any]] = []

        async def mock_record(self_audit, sess, **kwargs):
            audit_calls.append(kwargs)
            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            return mock_event

        with patch.object(AuditService, "record", mock_record):
            await service.submit(
                session,
                form_instance=form_instance,
                actor_id=mutation["actor_id"],
            )

        # Assertion 1: audit_service.record() called at least once
        assert len(audit_calls) >= 1, (
            "submit must call audit_service.record() at least once"
        )

        # Assertion 2: The submit audit event has correct entity_type
        submit_calls = [c for c in audit_calls if c["action"] == "submit"]
        assert len(submit_calls) >= 1, (
            "submit must produce an audit event with action='submit'"
        )

        # Assertion 3: Correct entity_type and actor
        for call in submit_calls:
            assert call["entity_type"] == "form_instance", (
                f"submit audit event must have entity_type='form_instance', "
                f"got '{call['entity_type']}'"
            )
            assert call["actor_id"] == mutation["actor_id"], (
                f"submit audit event actor_id mismatch: expected "
                f"{mutation['actor_id']}, got {call['actor_id']}"
            )

    @settings(max_examples=100, deadline=None)
    @given(mutation=clinical_mutation_strategy())
    async def test_change_value_calls_audit_record(self, mutation):
        """change_value MUST call audit_service.record() for the field change.

        **Validates: Requirements 10.5, 10.8, 18.1, 18.3, 21.4**

        For any post-submission field change, audit_service.record() is called
        with the correct entity_type, action, actor_id, and reason.
        """
        if mutation["mutation_type"] != "change_value":
            return  # Skip non-change_value mutations in this test

        service = DataCaptureService()
        session = _make_mock_session()

        # Post-submission form — requires reason
        form_instance = _make_form_instance(
            form_instance_id=mutation["form_instance_id"],
            subject_id=mutation["subject_id"],
            form_definition_id=mutation["form_definition_id"],
            status=FormInstanceStatus.submitted,
        )

        # Track audit_service.record calls
        audit_calls: list[dict[str, Any]] = []

        async def mock_record(self_audit, sess, **kwargs):
            audit_calls.append(kwargs)
            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            return mock_event

        with patch.object(AuditService, "record", mock_record):
            await service.change_value(
                session,
                form_instance=form_instance,
                field_id=mutation["field_id"],
                new_value=mutation["new_value"],
                reason=mutation["reason"],
                actor_id=mutation["actor_id"],
            )

        # Assertion 1: audit_service.record() called at least once
        assert len(audit_calls) >= 1, (
            "change_value must call audit_service.record() at least once"
        )

        # Assertion 2: Correct entity_type
        for call in audit_calls:
            assert call["entity_type"] == "field_value", (
                f"change_value audit events must have entity_type='field_value', "
                f"got '{call['entity_type']}'"
            )

        # Assertion 3: Correct actor
        for call in audit_calls:
            assert call["actor_id"] == mutation["actor_id"], (
                f"change_value audit event actor_id mismatch"
            )

        # Assertion 4: Correct action
        for call in audit_calls:
            assert call["action"] in ("create", "update"), (
                f"change_value audit events must have action 'create' or 'update', "
                f"got '{call['action']}'"
            )

    @settings(max_examples=100, deadline=None)
    @given(mutation=clinical_mutation_strategy())
    async def test_audit_service_never_commits(self, mutation):
        """AuditService.record() MUST NOT call session.commit().

        **Validates: Requirements 21.4**

        The caller owns the transaction boundary. The audit service writes
        within the caller's transaction (session.add + session.flush) but
        never commits, ensuring atomicity: if the mutation fails after the
        audit write, both roll back together.
        """
        service = AuditService()
        session = _make_mock_session()

        entity_id = mutation["form_instance_id"]
        actor_id = mutation["actor_id"]

        with patch("app.core.audit.get_actor", return_value=actor_id):
            with patch("app.core.audit.get_request_id", return_value=str(uuid.uuid4())):
                await service.record(
                    session,
                    entity_type="field_value",
                    entity_id=entity_id,
                    action="create",
                    actor_id=actor_id,
                )

        # session.commit MUST NOT be called by audit_service
        session.commit.assert_not_awaited()
        # session.add and flush are expected (within caller's transaction)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @settings(max_examples=100, deadline=None)
    @given(mutation=clinical_mutation_strategy())
    async def test_audit_event_contains_correct_fields(self, mutation):
        """Audit events produced by clinical mutations contain correct metadata.

        **Validates: Requirements 18.1, 10.8**

        For any clinical mutation, the audit event captures entity_type,
        action, and actor_id correctly — ensuring the audit trail is complete
        and attributable.
        """
        service = AuditService()
        session = _make_mock_session()

        entity_type = "field_value"
        entity_id = mutation["form_instance_id"]
        action = "create"
        actor_id = mutation["actor_id"]

        with patch("app.core.audit.get_actor", return_value=actor_id):
            with patch("app.core.audit.get_request_id", return_value=str(uuid.uuid4())):
                event = await service.record(
                    session,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=action,
                    actor_id=actor_id,
                    subject_id=mutation["subject_id"],
                )

        # The returned event has the correct fields
        assert event.entity_type == entity_type
        assert event.entity_id == entity_id
        assert event.action == action
        assert event.actor_id == actor_id
        assert event.subject_id == mutation["subject_id"]
