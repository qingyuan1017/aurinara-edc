"""Property-based test for submission validation.

**Validates: Requirements 10.3, 10.4**

Property 15: Submission validates atomically and preserves data on failure.

Generates random form instances with random field definitions (required/optional,
various data types with range constraints), generates random field values (some
valid, some invalid for their types), and asserts that submit():
  - Raises ValidationError when required fields are empty OR types/ranges are invalid
  - On failure: preserves the form status (doesn't advance to Submitted)
  - On success: sets status to Submitted

Uses mocked sessions with patches on _get_field_definitions and _get_field_value_map.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ValidationError
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition
from app.services.data_capture_service import DataCaptureService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Supported data types for field definitions
DATA_TYPES = ["string", "integer", "decimal", "date", "boolean"]


@st.composite
def field_definition_strategy(draw: st.DrawFn) -> FieldDefinition:
    """Generate a random FieldDefinition with plausible attributes."""
    data_type = draw(st.sampled_from(DATA_TYPES))
    is_required = draw(st.booleans())

    # Range constraints only for numeric types
    min_value = None
    max_value = None
    if data_type in ("integer", "decimal"):
        has_range = draw(st.booleans())
        if has_range:
            min_val = draw(st.integers(min_value=-1000, max_value=500))
            max_val = draw(st.integers(min_value=min_val + 1, max_value=1000))
            min_value = Decimal(str(min_val))
            max_value = Decimal(str(max_val))

    return FieldDefinition(
        id=uuid.uuid4(),
        form_section_id=uuid.uuid4(),
        label=f"Field_{draw(st.integers(min_value=1, max_value=9999))}",
        variable_name=f"var_{draw(st.integers(min_value=1, max_value=9999))}",
        control_type="text",
        data_type=data_type,
        is_required=is_required,
        min_value=min_value,
        max_value=max_value,
        codelist_id=None,
        regex_validation=None,
        is_read_only=False,
        is_calculated=False,
        display_order=0,
    )


def _valid_value_for_type(data_type: str, field_def: FieldDefinition) -> st.SearchStrategy[str]:
    """Strategy producing a value that is valid for the given data_type and range."""
    if data_type == "string":
        return st.text(
            alphabet=st.characters(categories=("L", "N"), max_codepoint=0x007E),
            min_size=1,
            max_size=50,
        )
    elif data_type == "integer":
        min_v = int(field_def.min_value) if field_def.min_value is not None else -1000
        max_v = int(field_def.max_value) if field_def.max_value is not None else 1000
        return st.integers(min_value=min_v, max_value=max_v).map(str)
    elif data_type == "decimal":
        min_v = float(field_def.min_value) if field_def.min_value is not None else -1000.0
        max_v = float(field_def.max_value) if field_def.max_value is not None else 1000.0
        return st.floats(
            min_value=min_v, max_value=max_v, allow_nan=False, allow_infinity=False
        ).map(lambda x: f"{x:.2f}")
    elif data_type == "date":
        return st.dates().map(lambda d: d.strftime("%Y-%m-%d"))
    elif data_type == "boolean":
        return st.sampled_from(["true", "false", "1", "0", "yes", "no"])
    return st.just("valid_string")


def _invalid_value_for_type(data_type: str, field_def: FieldDefinition) -> st.SearchStrategy[str]:
    """Strategy producing a value that is INVALID for the given data_type or range."""
    if data_type == "integer":
        # Mix of non-numeric strings and out-of-range values
        non_numeric = st.sampled_from(["abc", "12.5", "not_int", "", "  "])
        if field_def.max_value is not None:
            out_of_range = st.just(str(int(field_def.max_value) + 100))
            return st.one_of(non_numeric, out_of_range)
        return non_numeric
    elif data_type == "decimal":
        non_numeric = st.sampled_from(["abc", "not_decimal", "12.3.4", ""])
        if field_def.max_value is not None:
            out_of_range = st.just(str(float(field_def.max_value) + 100.0))
            return st.one_of(non_numeric, out_of_range)
        return non_numeric
    elif data_type == "date":
        return st.sampled_from(["not-a-date", "2024-13-01", "32-01-2024", "abcdef"])
    elif data_type == "boolean":
        return st.sampled_from(["maybe", "unknown", "2", "abc", ""])
    # For string type, an empty string on a required field is "invalid" in
    # the sense that it triggers the required check
    return st.just("")


@st.composite
def field_value_strategy(
    draw: st.DrawFn, field_def: FieldDefinition, *, make_valid: bool
) -> FieldValue | None:
    """Generate a FieldValue that is either valid or invalid for the given definition.

    Returns None to simulate a missing field value (for required-field testing).
    """
    if not make_valid:
        # Decide whether to return None (missing) or an invalid value
        if field_def.is_required and draw(st.booleans()):
            return None  # Missing required field
        # Generate an invalid value for the type
        value = draw(_invalid_value_for_type(field_def.data_type, field_def))
        if not value.strip():
            # Empty/whitespace for required field
            if field_def.is_required:
                return None
            # For optional fields, empty is acceptable (skip validation)
            value = draw(_invalid_value_for_type(field_def.data_type, field_def))
    else:
        value = draw(_valid_value_for_type(field_def.data_type, field_def))

    return FieldValue(
        id=uuid.uuid4(),
        form_instance_id=uuid.uuid4(),  # Will be replaced in test
        field_definition_id=field_def.id,
        value=value,
        is_not_applicable=False,
        created_at=datetime.now(UTC),
    )


@st.composite
def submission_scenario_strategy(draw: st.DrawFn):
    """Generate a complete submission scenario: field definitions + field values.

    Returns (field_definitions, field_value_map, should_pass).
    """
    # Generate 1-8 field definitions
    num_fields = draw(st.integers(min_value=1, max_value=8))
    field_defs = [draw(field_definition_strategy()) for _ in range(num_fields)]

    # Decide whether this scenario should be all-valid or contain at least one invalid
    all_valid = draw(st.booleans())

    field_value_map: dict[uuid.UUID, FieldValue] = {}
    has_error = False

    for i, fd in enumerate(field_defs):
        if all_valid:
            # All values valid
            fv = draw(field_value_strategy(fd, make_valid=True))
            if fv is not None:
                field_value_map[fd.id] = fv
            elif fd.is_required:
                # For required fields we must provide a valid value
                fv_inner = draw(field_value_strategy(fd, make_valid=True))
                if fv_inner is not None:
                    field_value_map[fd.id] = fv_inner
                # If still None, this would be an error
        else:
            # Mix: make at least the first field invalid
            if i == 0:
                fv = draw(field_value_strategy(fd, make_valid=False))
                if fv is None and fd.is_required:
                    has_error = True
                elif fv is not None:
                    field_value_map[fd.id] = fv
                    # Check if the value itself is problematic
                    has_error = True
                else:
                    # fv is None and field is optional — not an error
                    # Force an error on required field instead
                    pass
            else:
                # Rest can be valid or invalid
                make_this_valid = draw(st.booleans())
                fv = draw(field_value_strategy(fd, make_valid=make_this_valid))
                if fv is not None:
                    field_value_map[fd.id] = fv
                elif fd.is_required and not make_this_valid:
                    has_error = True

    # Determine expected outcome
    # Re-evaluate whether errors exist using the same logic the service uses
    expected_errors = _compute_expected_errors(field_defs, field_value_map)
    should_pass = len(expected_errors) == 0

    return field_defs, field_value_map, should_pass


def _compute_expected_errors(
    field_defs: list[FieldDefinition],
    field_value_map: dict[uuid.UUID, FieldValue],
) -> list[str]:
    """Replicate the service's validation logic to predict expected errors."""
    errors: list[str] = []

    for fd in field_defs:
        if fd.is_read_only or fd.is_calculated:
            continue

        fv = field_value_map.get(fd.id)
        value = fv.value if fv else None
        is_na = fv.is_not_applicable if fv else False

        # Required check
        if (
            fd.is_required
            and not is_na
            and (value is None or (isinstance(value, str) and not value.strip()))
        ):
            errors.append(f"required:{fd.id}")
            continue

        # Skip if no value or NA
        if is_na or value is None or (isinstance(value, str) and not value.strip()):
            continue

        # Data type check
        data_type = fd.data_type.lower()
        if data_type == "integer":
            try:
                int(value)
            except (ValueError, TypeError):
                errors.append(f"data_type:{fd.id}")
                continue
        elif data_type in ("decimal", "float"):
            try:
                Decimal(value)
            except Exception:
                errors.append(f"data_type:{fd.id}")
                continue
        elif data_type == "date":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                errors.append(f"data_type:{fd.id}")
                continue
        elif data_type == "boolean":
            if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
                errors.append(f"data_type:{fd.id}")
                continue

        # Range check (numeric types only)
        if fd.min_value is not None or fd.max_value is not None:
            try:
                numeric_value = Decimal(value)
                if fd.min_value is not None and numeric_value < fd.min_value:
                    errors.append(f"range:{fd.id}")
                elif fd.max_value is not None and numeric_value > fd.max_value:
                    errors.append(f"range:{fd.id}")
            except Exception:
                pass  # Type check already caught this

    return errors


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestSubmissionValidationProperty:
    """Property-based tests for submission validation atomicity.

    **Validates: Requirements 10.3, 10.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(scenario=submission_scenario_strategy())
    @pytest.mark.asyncio
    async def test_submission_validates_atomically(self, scenario):
        """submit() validates atomically and preserves data on failure.

        **Validates: Requirements 10.3, 10.4**

        For any randomly generated form with field definitions and values:
          - If validation should fail (required fields missing or type/range invalid):
            submit() raises ValidationError AND the form status is NOT advanced.
          - If validation passes: submit() sets status to Submitted.
        """
        field_defs, field_value_map, should_pass = scenario

        # Create a form instance in In Progress state
        form_instance = FormInstance(
            id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            form_definition_id=uuid.uuid4(),
            status=FormInstanceStatus.in_progress,
            data_jsonb=None,
            created_at=datetime.now(UTC),
        )

        original_status = form_instance.status
        actor_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        service = DataCaptureService()

        with patch.object(
            service, "_get_field_definitions", return_value=field_defs
        ), patch.object(
            service, "_get_field_value_map", return_value=field_value_map
        ), patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()

            if should_pass:
                # Expect success: status advances to Submitted
                result = await service.submit(mock_session, form_instance, actor_id)
                assert result.status == FormInstanceStatus.submitted
                assert result.submitted_at is not None
                assert result.submitted_by == actor_id
            else:
                # Expect failure: ValidationError raised, status preserved
                with pytest.raises(ValidationError) as exc_info:
                    await service.submit(mock_session, form_instance, actor_id)

                # Status must NOT have advanced (Req 10.4)
                assert form_instance.status == original_status
                assert form_instance.status != FormInstanceStatus.submitted

                # Field-level errors must be present
                assert "field_errors" in exc_info.value.details
                assert len(exc_info.value.details["field_errors"]) > 0
