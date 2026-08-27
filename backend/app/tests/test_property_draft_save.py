"""Property-based test for draft save persistence and status transition.

**Validates: Requirements 10.1, 10.6**

Property 14: Draft save persists values and sets In Progress.

*For any* set of field values saved as a draft, the values are persisted
(via _upsert_field_value call) and the Form_Instance status becomes In Progress.
Frozen/Locked forms are rejected with a BusinessRuleError.

Uses mocked sessions following the same pattern as test_data_capture_service.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError
from app.models.form_data import FormInstance, FormInstanceStatus
from app.services.data_capture_service import DataCaptureService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating arbitrary field IDs (as UUID strings)
field_id_strategy = st.uuids().map(str)

# Strategy for generating arbitrary field values (non-empty strings)
field_value_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs", "P"), max_codepoint=0x024F),
    min_size=1,
    max_size=200,
)

# Strategy for generating a dict of field_id -> value (1 to 10 fields)
field_values_strategy = st.dictionaries(
    keys=field_id_strategy,
    values=field_value_strategy,
    min_size=1,
    max_size=10,
)

# Statuses that allow draft save (not Frozen or Locked)
saveable_status_strategy = st.sampled_from([
    FormInstanceStatus.not_started,
    FormInstanceStatus.in_progress,
])

# Statuses that reject draft save
locked_status_strategy = st.sampled_from([
    FormInstanceStatus.frozen,
    FormInstanceStatus.locked,
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form_instance(status: FormInstanceStatus) -> FormInstance:
    """Create a FormInstance with the given status."""
    return FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=status,
        data_jsonb=None,
        created_at=datetime.now(UTC),
    )


def _make_mock_session(num_fields: int):
    """Create a mock AsyncSession that supports save_draft operations.

    Returns (mock_session, upsert_call_tracker) where upsert_call_tracker
    records which field values were persisted.
    """
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    # For each field: _upsert_field_value does a select (returns None = new field)
    # After all fields: _sync_data_jsonb does a select (returns empty list)
    upsert_results = [MagicMock() for _ in range(num_fields)]
    for r in upsert_results:
        r.scalars.return_value.first.return_value = None

    sync_result = MagicMock()
    sync_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[*upsert_results, sync_result]
    )
    return mock_session


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestDraftSaveProperty:
    """Property-based tests for draft save persistence and status transition.

    **Validates: Requirements 10.1, 10.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        values=field_values_strategy,
        initial_status=saveable_status_strategy,
    )
    @pytest.mark.asyncio
    async def test_draft_save_sets_in_progress_and_persists_values(
        self, values: dict[str, str], initial_status: FormInstanceStatus
    ):
        """Draft save persists each field value and sets status to In Progress.

        **Validates: Requirements 10.1**

        For any set of field values and any saveable initial status:
          - After save_draft(), status is In Progress (or remains In Progress).
          - _upsert_field_value is called once per field in the values dict.
        """
        service = DataCaptureService()
        actor_id = uuid.uuid4()
        fi = _make_form_instance(status=initial_status)

        # Track calls to _upsert_field_value
        upsert_calls: list[tuple] = []
        original_upsert = service._upsert_field_value

        async def tracking_upsert(session, *, form_instance, field_definition_id, new_value, actor_id, reason):
            upsert_calls.append((str(field_definition_id), new_value))
            # Minimal mock: just return a MagicMock FieldValue
            return MagicMock()

        mock_session = _make_mock_session(len(values))

        with patch.object(service, "_upsert_field_value", side_effect=tracking_upsert), \
             patch.object(service, "_sync_data_jsonb", new_callable=AsyncMock):
            result = await service.save_draft(mock_session, fi, values, actor_id)

        # Property: status is In Progress after save_draft
        assert result.status == FormInstanceStatus.in_progress

        # Property: each field value was persisted via _upsert_field_value
        assert len(upsert_calls) == len(values)
        persisted_fields = {field_id for field_id, _ in upsert_calls}
        for field_id in values:
            assert field_id in persisted_fields

        # Property: each persisted value matches the input
        persisted_map = {field_id: val for field_id, val in upsert_calls}
        for field_id, expected_value in values.items():
            assert persisted_map[field_id] == expected_value

    @settings(max_examples=100, deadline=None)
    @given(
        values=field_values_strategy,
        locked_status=locked_status_strategy,
    )
    @pytest.mark.asyncio
    async def test_draft_save_rejects_frozen_or_locked(
        self, values: dict[str, str], locked_status: FormInstanceStatus
    ):
        """Draft save rejects Frozen/Locked forms with BusinessRuleError.

        **Validates: Requirements 10.6**

        For any set of field values and any locked status (Frozen or Locked):
          - save_draft() raises BusinessRuleError.
          - The form status remains unchanged.
        """
        service = DataCaptureService()
        actor_id = uuid.uuid4()
        fi = _make_form_instance(status=locked_status)
        original_status = fi.status

        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError):
            await service.save_draft(mock_session, fi, values, actor_id)

        # Property: status unchanged after rejection
        assert fi.status == original_status
