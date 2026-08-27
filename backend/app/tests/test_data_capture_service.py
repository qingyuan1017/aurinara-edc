"""Unit tests for the DataCaptureService.

Validates Requirements:
  - 10.1: save_draft persists Field_Values and sets status In Progress.
  - 10.3: submit validates required/type/range/codelist.
  - 10.4: Submission failure preserves values and returns field-level errors.
  - 10.5: Post-submission changes require a Reason_For_Change.
  - 10.6: mark_not_applicable persists the not-applicable state.
  - 10.7: Frozen/Locked forms reject modifications.
  - 10.8: Audit_Event written in the same transaction.
  - 22.3: data_jsonb and field_values stay consistent.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.form_metadata import FieldDefinition
from app.services.data_capture_service import DataCaptureService, data_capture_service


@pytest.fixture
def service():
    """Fresh DataCaptureService instance for each test."""
    return DataCaptureService()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


@pytest.fixture
def form_definition_id():
    return uuid.uuid4()


@pytest.fixture
def field_def_id():
    return uuid.uuid4()


def _make_form_instance(
    status: FormInstanceStatus = FormInstanceStatus.not_started,
    form_definition_id: uuid.UUID | None = None,
) -> FormInstance:
    """Create a mock FormInstance."""
    fi = FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=form_definition_id or uuid.uuid4(),
        status=status,
        data_jsonb=None,
        created_at=datetime.now(UTC),
    )
    return fi


def _make_field_definition(
    field_id: uuid.UUID | None = None,
    *,
    is_required: bool = False,
    data_type: str = "string",
    min_value: Decimal | None = None,
    max_value: Decimal | None = None,
    codelist_id: uuid.UUID | None = None,
    regex_validation: str | None = None,
    is_read_only: bool = False,
    is_calculated: bool = False,
    variable_name: str = "test_field",
    label: str = "Test Field",
) -> FieldDefinition:
    """Create a FieldDefinition instance."""
    fd = FieldDefinition(
        id=field_id or uuid.uuid4(),
        form_section_id=uuid.uuid4(),
        label=label,
        variable_name=variable_name,
        control_type="text",
        data_type=data_type,
        is_required=is_required,
        min_value=min_value,
        max_value=max_value,
        codelist_id=codelist_id,
        regex_validation=regex_validation,
        is_read_only=is_read_only,
        is_calculated=is_calculated,
        display_order=0,
    )
    return fd


class TestLoad:
    """Tests for DataCaptureService.load()."""

    async def test_load_returns_form_instance(self, service):
        """load() returns the FormInstance when it exists."""
        fi = _make_form_instance()
        mock_session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = fi
        mock_session.execute = AsyncMock(return_value=result_mock)

        result = await service.load(mock_session, fi.id)
        assert result == fi

    async def test_load_raises_not_found(self, service):
        """load() raises NotFoundError when form instance doesn't exist."""
        mock_session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(NotFoundError):
            await service.load(mock_session, uuid.uuid4())


class TestSaveDraft:
    """Tests for DataCaptureService.save_draft() (Req 10.1)."""

    async def test_sets_status_to_in_progress(self, service, actor_id, field_def_id):
        """save_draft sets status from Not Started to In Progress (Req 10.1)."""
        fi = _make_form_instance(status=FormInstanceStatus.not_started)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        # _upsert_field_value looks up existing FieldValue (returns None = create)
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        # _sync_data_jsonb loads all field values
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[result_mock, sync_result]
        )

        with patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.save_draft(
                mock_session, fi, {str(field_def_id): "value1"}, actor_id
            )

        assert result.status == FormInstanceStatus.in_progress

    async def test_rejects_frozen_form(self, service, actor_id, field_def_id):
        """save_draft rejects a Frozen form (Req 10.7)."""
        fi = _make_form_instance(status=FormInstanceStatus.frozen)
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError, match="Frozen"):
            await service.save_draft(
                mock_session, fi, {str(field_def_id): "value"}, actor_id
            )

    async def test_rejects_locked_form(self, service, actor_id, field_def_id):
        """save_draft rejects a Locked form (Req 10.7)."""
        fi = _make_form_instance(status=FormInstanceStatus.locked)
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError, match="Locked"):
            await service.save_draft(
                mock_session, fi, {str(field_def_id): "value"}, actor_id
            )

    async def test_writes_audit_event(self, service, actor_id, field_def_id):
        """save_draft writes an Audit_Event for each created field (Req 10.8)."""
        fi = _make_form_instance(status=FormInstanceStatus.not_started)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = None
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = []

        mock_session.execute = AsyncMock(
            side_effect=[result_mock, sync_result]
        )

        with patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            await service.save_draft(
                mock_session, fi, {str(field_def_id): "value1"}, actor_id
            )

            # Audit was called for the field value creation
            mock_audit.record.assert_awaited_once()
            call_kwargs = mock_audit.record.call_args.kwargs
            assert call_kwargs["action"] == "create"
            assert call_kwargs["entity_type"] == "field_value"
            assert call_kwargs["new_value"] == "value1"


class TestSubmit:
    """Tests for DataCaptureService.submit() (Req 10.3, 10.4)."""

    async def test_submit_succeeds_with_valid_data(self, service, actor_id):
        """submit sets status to Submitted when all validations pass (Req 10.3)."""
        fi = _make_form_instance(status=FormInstanceStatus.in_progress)
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        field_def = _make_field_definition(is_required=True, data_type="string")

        # Mock _get_field_definitions
        with patch.object(
            service, "_get_field_definitions", return_value=[field_def]
        ), patch.object(
            service, "_get_field_value_map",
            return_value={
                field_def.id: FieldValue(
                    id=uuid.uuid4(),
                    form_instance_id=fi.id,
                    field_definition_id=field_def.id,
                    value="Hello",
                    is_not_applicable=False,
                    created_at=datetime.now(UTC),
                )
            },
        ), patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.submit(mock_session, fi, actor_id)

        assert result.status == FormInstanceStatus.submitted
        assert result.submitted_by == actor_id
        assert result.submitted_at is not None

    async def test_submit_fails_missing_required_field(self, service, actor_id):
        """submit raises ValidationError with field errors when required field is empty (Req 10.4)."""
        fi = _make_form_instance(status=FormInstanceStatus.in_progress)
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        field_def = _make_field_definition(
            is_required=True, data_type="string", variable_name="weight"
        )

        with patch.object(
            service, "_get_field_definitions", return_value=[field_def]
        ), patch.object(
            service, "_get_field_value_map", return_value={}
        ), patch(
            "app.services.data_capture_service.audit_service"
        ), pytest.raises(ValidationError) as exc_info:
            await service.submit(mock_session, fi, actor_id)

        # Values are preserved (status unchanged)
        assert fi.status == FormInstanceStatus.in_progress
        assert "field_errors" in exc_info.value.details

    async def test_submit_fails_invalid_data_type(self, service, actor_id):
        """submit validates data types (Req 10.3)."""
        fi = _make_form_instance(status=FormInstanceStatus.in_progress)
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        field_def = _make_field_definition(data_type="integer")

        with patch.object(
            service, "_get_field_definitions", return_value=[field_def]
        ), patch.object(
            service, "_get_field_value_map",
            return_value={
                field_def.id: FieldValue(
                    id=uuid.uuid4(),
                    form_instance_id=fi.id,
                    field_definition_id=field_def.id,
                    value="not_a_number",
                    is_not_applicable=False,
                    created_at=datetime.now(UTC),
                )
            },
        ), patch(
            "app.services.data_capture_service.audit_service"
        ), pytest.raises(ValidationError) as exc_info:
            await service.submit(mock_session, fi, actor_id)

        errors = exc_info.value.details["field_errors"]
        assert any(e["error"] == "data_type" for e in errors)

    async def test_submit_fails_out_of_range(self, service, actor_id):
        """submit validates numeric range (Req 10.3)."""
        fi = _make_form_instance(status=FormInstanceStatus.in_progress)
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()

        field_def = _make_field_definition(
            data_type="decimal",
            min_value=Decimal("0"),
            max_value=Decimal("100"),
        )

        with patch.object(
            service, "_get_field_definitions", return_value=[field_def]
        ), patch.object(
            service, "_get_field_value_map",
            return_value={
                field_def.id: FieldValue(
                    id=uuid.uuid4(),
                    form_instance_id=fi.id,
                    field_definition_id=field_def.id,
                    value="150",
                    is_not_applicable=False,
                    created_at=datetime.now(UTC),
                )
            },
        ), patch(
            "app.services.data_capture_service.audit_service"
        ), pytest.raises(ValidationError) as exc_info:
            await service.submit(mock_session, fi, actor_id)

        errors = exc_info.value.details["field_errors"]
        assert any(e["error"] == "range" for e in errors)

    async def test_submit_rejects_frozen(self, service, actor_id):
        """submit rejects Frozen forms (Req 10.7)."""
        fi = _make_form_instance(status=FormInstanceStatus.frozen)
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError, match="Frozen"):
            await service.submit(mock_session, fi, actor_id)


class TestChangeValue:
    """Tests for DataCaptureService.change_value() (Req 10.5, 10.7)."""

    async def test_requires_reason_after_submission(self, service, actor_id, field_def_id):
        """change_value raises ValidationError without reason post-submission (Req 10.5)."""
        fi = _make_form_instance(status=FormInstanceStatus.submitted)
        mock_session = AsyncMock()

        with pytest.raises(ValidationError, match="Reason_For_Change"):
            await service.change_value(
                mock_session, fi, field_def_id, "new_val", None, actor_id
            )

    async def test_accepts_reason_after_submission(self, service, actor_id, field_def_id):
        """change_value succeeds with a reason post-submission (Req 10.5)."""
        fi = _make_form_instance(status=FormInstanceStatus.submitted)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        # Lookup returns existing field value
        existing_fv = FieldValue(
            id=uuid.uuid4(),
            form_instance_id=fi.id,
            field_definition_id=field_def_id,
            value="old_val",
            is_not_applicable=False,
            created_at=datetime.now(UTC),
        )
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = existing_fv
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = [existing_fv]

        mock_session.execute = AsyncMock(
            side_effect=[result_mock, sync_result]
        )

        with patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.change_value(
                mock_session, fi, field_def_id, "new_val",
                "Data entry error", actor_id
            )

        assert result == fi
        # Audit should include reason
        call_kwargs = mock_audit.record.call_args.kwargs
        assert call_kwargs["reason"] == "Data entry error"

    async def test_rejects_locked_form(self, service, actor_id, field_def_id):
        """change_value rejects Locked forms (Req 10.7)."""
        fi = _make_form_instance(status=FormInstanceStatus.locked)
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError, match="Locked"):
            await service.change_value(
                mock_session, fi, field_def_id, "x", "reason", actor_id
            )


class TestMarkNotApplicable:
    """Tests for DataCaptureService.mark_not_applicable() (Req 10.6)."""

    async def test_marks_field_not_applicable(self, service, actor_id, field_def_id):
        """mark_not_applicable sets is_not_applicable=True (Req 10.6)."""
        fi = _make_form_instance(status=FormInstanceStatus.in_progress)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        existing_fv = FieldValue(
            id=uuid.uuid4(),
            form_instance_id=fi.id,
            field_definition_id=field_def_id,
            value="some_value",
            is_not_applicable=False,
            created_at=datetime.now(UTC),
        )
        # get_or_create returns existing
        get_result = MagicMock()
        get_result.scalars.return_value.first.return_value = existing_fv
        # sync loads field values
        sync_result = MagicMock()
        sync_result.scalars.return_value.all.return_value = [existing_fv]

        mock_session.execute = AsyncMock(
            side_effect=[get_result, sync_result]
        )

        with patch(
            "app.services.data_capture_service.audit_service"
        ) as mock_audit:
            mock_audit.record = AsyncMock()
            await service.mark_not_applicable(
                mock_session, fi, field_def_id, actor_id
            )

        assert existing_fv.is_not_applicable is True
        mock_audit.record.assert_awaited_once()

    async def test_rejects_frozen_form(self, service, actor_id, field_def_id):
        """mark_not_applicable rejects Frozen forms (Req 10.7)."""
        fi = _make_form_instance(status=FormInstanceStatus.frozen)
        mock_session = AsyncMock()

        with pytest.raises(BusinessRuleError, match="Frozen"):
            await service.mark_not_applicable(
                mock_session, fi, field_def_id, actor_id
            )


class TestValidation:
    """Tests for internal validation logic."""

    def test_validate_data_type_integer_valid(self, service):
        """Integer validation passes for valid integers."""
        fd = _make_field_definition(data_type="integer")
        assert service._validate_data_type(fd, "42") is None

    def test_validate_data_type_integer_invalid(self, service):
        """Integer validation fails for non-integer strings."""
        fd = _make_field_definition(data_type="integer")
        assert service._validate_data_type(fd, "abc") is not None

    def test_validate_data_type_decimal_valid(self, service):
        """Decimal validation passes for valid decimals."""
        fd = _make_field_definition(data_type="decimal")
        assert service._validate_data_type(fd, "3.14") is None

    def test_validate_data_type_decimal_invalid(self, service):
        """Decimal validation fails for non-numeric strings."""
        fd = _make_field_definition(data_type="decimal")
        assert service._validate_data_type(fd, "not_decimal") is not None

    def test_validate_data_type_date_valid(self, service):
        """Date validation passes for YYYY-MM-DD."""
        fd = _make_field_definition(data_type="date")
        assert service._validate_data_type(fd, "2024-01-15") is None

    def test_validate_data_type_date_invalid(self, service):
        """Date validation fails for invalid dates."""
        fd = _make_field_definition(data_type="date")
        assert service._validate_data_type(fd, "15-01-2024") is not None

    def test_validate_data_type_boolean_valid(self, service):
        """Boolean validation passes for valid boolean strings."""
        fd = _make_field_definition(data_type="boolean")
        assert service._validate_data_type(fd, "true") is None
        assert service._validate_data_type(fd, "False") is None

    def test_validate_data_type_boolean_invalid(self, service):
        """Boolean validation fails for non-boolean strings."""
        fd = _make_field_definition(data_type="boolean")
        assert service._validate_data_type(fd, "maybe") is not None

    def test_validate_range_within(self, service):
        """Range validation passes for values within bounds."""
        fd = _make_field_definition(
            data_type="decimal", min_value=Decimal("0"), max_value=Decimal("100")
        )
        assert service._validate_range(fd, "50") is None

    def test_validate_range_below_min(self, service):
        """Range validation fails for values below minimum."""
        fd = _make_field_definition(
            data_type="decimal", min_value=Decimal("10"), max_value=Decimal("100")
        )
        assert service._validate_range(fd, "5") is not None

    def test_validate_range_above_max(self, service):
        """Range validation fails for values above maximum."""
        fd = _make_field_definition(
            data_type="decimal", min_value=Decimal("0"), max_value=Decimal("100")
        )
        assert service._validate_range(fd, "150") is not None

    def test_validate_regex_valid(self, service):
        """Regex validation passes for matching patterns."""
        fd = _make_field_definition(regex_validation=r"[A-Z]{2}\d{4}")
        assert service._validate_regex(fd, "AB1234") is None

    def test_validate_regex_invalid(self, service):
        """Regex validation fails for non-matching values."""
        fd = _make_field_definition(regex_validation=r"[A-Z]{2}\d{4}")
        assert service._validate_regex(fd, "123") is not None


class TestSingleton:
    def test_singleton_exists(self):
        assert data_capture_service is not None
        assert isinstance(data_capture_service, DataCaptureService)
