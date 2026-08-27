"""Property-based test for hybrid storage consistency.

**Validates: Requirements 22.3**

Property 31: Hybrid storage stays consistent.

*For any* set of saved field values, the values in `form_instances.data_jsonb`
and the corresponding normalized `field_values` rows represent the same data
after every save. Specifically, after save_draft():
  - data_jsonb contains exactly the same keys as the field_values rows
  - For each field_value row, data_jsonb[field_definition_id] == field_value.value

Uses mocked sessions. The mock session is configured so that the
_sync_data_jsonb query returns FieldValue objects matching what was persisted
during the save_draft call, allowing us to verify consistency end-to-end.
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

# Strategy for generating field IDs as UUID strings
field_id_strategy = st.uuids().map(str)

# Strategy for generating field values — representative clinical data
field_value_strategy = st.one_of(
    st.text(
        alphabet=st.characters(categories=("L", "N", "Zs", "P"), max_codepoint=0x024F),
        min_size=1,
        max_size=200,
    ),
    st.integers(min_value=-99999, max_value=99999).map(str),
    st.sampled_from(["true", "false", "2024-03-15", "98.6", "120/80"]),
)

# Strategy for generating a dict of field_id -> value (1 to 15 fields)
field_values_strategy = st.dictionaries(
    keys=field_id_strategy,
    values=field_value_strategy,
    min_size=1,
    max_size=15,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form_instance() -> FormInstance:
    """Create a FormInstance in not_started status for testing."""
    return FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=FormInstanceStatus.not_started,
        data_jsonb=None,
        created_at=datetime.now(UTC),
    )


def _make_field_value(
    form_instance_id: UUID,
    field_definition_id: UUID,
    value: str | None,
) -> FieldValue:
    """Create a FieldValue object matching what would be persisted."""
    fv = FieldValue(
        id=uuid.uuid4(),
        form_instance_id=form_instance_id,
        field_definition_id=field_definition_id,
        value=value,
        is_not_applicable=False,
        created_at=datetime.now(UTC),
    )
    return fv


def _make_mock_session(
    form_instance_id: UUID,
    values: dict[str, str],
) -> AsyncMock:
    """Create a mock session that simulates save_draft behavior.

    The session mock handles:
      - N execute calls for _upsert_field_value (one per field, returns None = new)
      - 1 execute call for _sync_data_jsonb (returns FieldValue objects built
        from the persisted values)
      - flush calls (no-op)

    This lets the real _sync_data_jsonb logic run and rebuild data_jsonb from
    the "persisted" field values.
    """
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    num_fields = len(values)

    # Build FieldValue objects that _sync_data_jsonb will receive
    persisted_field_values = []
    for field_id_str, val in values.items():
        fv = _make_field_value(
            form_instance_id=form_instance_id,
            field_definition_id=UUID(field_id_str),
            value=str(val) if val is not None else None,
        )
        persisted_field_values.append(fv)

    # Responses for upsert queries: each returns None (new field value)
    upsert_results = []
    for _ in range(num_fields):
        r = MagicMock()
        r.scalars.return_value.first.return_value = None
        upsert_results.append(r)

    # Response for _sync_data_jsonb query: returns all persisted field values
    sync_result = MagicMock()
    sync_result.scalars.return_value.all.return_value = persisted_field_values

    mock_session.execute = AsyncMock(
        side_effect=[*upsert_results, sync_result]
    )

    return mock_session


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestHybridStorageConsistencyProperty:
    """Property-based tests for hybrid storage consistency.

    **Validates: Requirements 22.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(values=field_values_strategy)
    @pytest.mark.asyncio
    async def test_data_jsonb_matches_field_values_after_save_draft(
        self, values: dict[str, str]
    ):
        """After save_draft, data_jsonb matches the persisted field_values.

        **Validates: Requirements 22.3**

        For any set of field values:
          - data_jsonb has exactly the same keys as the field_values rows
          - For each key, data_jsonb[key] == field_value.value
          - No extra or missing keys exist in data_jsonb
        """
        service = DataCaptureService()
        actor_id = uuid.uuid4()
        fi = _make_form_instance()

        mock_session = _make_mock_session(fi.id, values)

        # Mock audit_service.record to avoid side effects
        async def mock_record(self_audit, sess, **kwargs):
            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            return mock_event

        with patch.object(AuditService, "record", mock_record):
            result = await service.save_draft(mock_session, fi, values, actor_id)

        # Property 1: data_jsonb contains exactly the same keys as field_values
        assert result.data_jsonb is not None, "data_jsonb must not be None after save"
        jsonb_keys = set(result.data_jsonb.keys())
        expected_keys = set(values.keys())
        assert jsonb_keys == expected_keys, (
            f"data_jsonb keys {jsonb_keys} != field_values keys {expected_keys}"
        )

        # Property 2: For each field, data_jsonb[field_id] == field_value.value
        for field_id_str, original_value in values.items():
            expected_serialized = str(original_value) if original_value is not None else None
            actual = result.data_jsonb[field_id_str]
            assert actual == expected_serialized, (
                f"data_jsonb[{field_id_str}] = {actual!r}, "
                f"expected {expected_serialized!r}"
            )
