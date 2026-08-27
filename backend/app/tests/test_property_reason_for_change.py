"""Property-based test for post-submission reason requirement.

**Validates: Requirements 10.5, 18.3**

Property 16: Post-submission changes require a reason.

Generates random form instance statuses (Submitted, Reviewed, Frozen, Locked, Signed)
and random field changes. Asserts that change_value():
  - Raises ValidationError when the form is post-submission and NO reason is provided
    (or reason is empty/whitespace).
  - Succeeds when a non-empty reason IS provided (for non-frozen/locked forms).
  - Raises BusinessRuleError for Frozen/Locked regardless of reason.

Uses mocked sessions. Runs at least 100 iterations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError, ValidationError
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.services.data_capture_service import DataCaptureService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Post-submission statuses that still allow modification (with a reason).
_MODIFIABLE_POST_SUBMISSION = [
    FormInstanceStatus.submitted,
    FormInstanceStatus.reviewed,
    FormInstanceStatus.signed,
]

# Frozen/Locked statuses that block any modification.
_LOCKED_STATUSES = [
    FormInstanceStatus.frozen,
    FormInstanceStatus.locked,
]

# All post-submission statuses.
_ALL_POST_SUBMISSION = _MODIFIABLE_POST_SUBMISSION + _LOCKED_STATUSES

# Strategy for modifiable post-submission statuses.
modifiable_post_submission_status_st = st.sampled_from(_MODIFIABLE_POST_SUBMISSION)

# Strategy for frozen/locked statuses.
locked_status_st = st.sampled_from(_LOCKED_STATUSES)

# Strategy for all post-submission statuses.
all_post_submission_status_st = st.sampled_from(_ALL_POST_SUBMISSION)

# Strategy for empty/whitespace reasons (None, empty string, whitespace-only).
empty_reason_st = st.one_of(
    st.none(),
    st.just(""),
    st.text(
        alphabet=st.sampled_from([" ", "\t", "\n", "\r"]),
        min_size=1,
        max_size=10,
    ),
)

# Strategy for valid non-empty reasons.
valid_reason_st = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs"), max_codepoint=0x024F),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip() != "")

# Strategy for random field values (any printable string).
field_value_st = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Zs"), max_codepoint=0x024F),
    min_size=0,
    max_size=100,
)


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


def _make_mock_session_for_success(form_instance_id: uuid.UUID, field_id: uuid.UUID):
    """Create a mock session that supports a successful change_value call."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    # First execute: _upsert_field_value lookup returns existing FieldValue
    existing_fv = FieldValue(
        id=uuid.uuid4(),
        form_instance_id=form_instance_id,
        field_definition_id=field_id,
        value="old_value",
        is_not_applicable=False,
        created_at=datetime.now(UTC),
    )
    upsert_result = MagicMock()
    upsert_result.scalars.return_value.first.return_value = existing_fv

    # Second execute: _sync_data_jsonb returns all field values
    sync_result = MagicMock()
    sync_result.scalars.return_value.all.return_value = [existing_fv]

    mock_session.execute = AsyncMock(side_effect=[upsert_result, sync_result])
    return mock_session


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestPostSubmissionReasonProperty:
    """Property-based tests for post-submission reason enforcement.

    **Validates: Requirements 10.5, 18.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        status=modifiable_post_submission_status_st,
        empty_reason=empty_reason_st,
        new_value=field_value_st,
    )
    @pytest.mark.asyncio
    async def test_raises_validation_error_when_no_reason_post_submission(
        self,
        status: FormInstanceStatus,
        empty_reason: str | None,
        new_value: str,
    ):
        """change_value raises ValidationError when post-submission and no reason provided.

        **Validates: Requirements 10.5**

        For any modifiable post-submission status (Submitted, Reviewed, Signed):
          - If reason is None, empty, or whitespace-only,
            change_value MUST raise ValidationError.
        """
        service = DataCaptureService()
        fi = _make_form_instance(status)
        field_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        mock_session = AsyncMock()

        with pytest.raises(ValidationError, match="Reason_For_Change"):
            await service.change_value(
                mock_session, fi, field_id, new_value, empty_reason, actor_id
            )

    @settings(max_examples=100, deadline=None)
    @given(
        status=modifiable_post_submission_status_st,
        reason=valid_reason_st,
        new_value=field_value_st,
    )
    @pytest.mark.asyncio
    async def test_succeeds_with_valid_reason_post_submission(
        self,
        status: FormInstanceStatus,
        reason: str,
        new_value: str,
    ):
        """change_value succeeds when a non-empty reason is provided post-submission.

        **Validates: Requirements 10.5, 18.3**

        For any modifiable post-submission status (Submitted, Reviewed, Signed):
          - If a non-empty, non-whitespace reason is provided,
            change_value MUST succeed (return the FormInstance).
        """
        service = DataCaptureService()
        fi = _make_form_instance(status)
        field_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        mock_session = _make_mock_session_for_success(fi.id, field_id)

        with patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.change_value(
                mock_session, fi, field_id, new_value, reason, actor_id
            )

        assert result is fi

    @settings(max_examples=100, deadline=None)
    @given(
        status=locked_status_st,
        reason=st.one_of(empty_reason_st, valid_reason_st),
        new_value=field_value_st,
    )
    @pytest.mark.asyncio
    async def test_raises_business_rule_error_for_frozen_locked(
        self,
        status: FormInstanceStatus,
        reason: str | None,
        new_value: str,
    ):
        """change_value raises BusinessRuleError for Frozen/Locked regardless of reason.

        **Validates: Requirements 10.5, 18.3**

        For Frozen or Locked statuses:
          - change_value MUST raise BusinessRuleError regardless of whether
            a reason is provided.
        """
        service = DataCaptureService()
        fi = _make_form_instance(status)
        field_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError):
            await service.change_value(
                mock_session, fi, field_id, new_value, reason, actor_id
            )
