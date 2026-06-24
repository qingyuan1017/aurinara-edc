"""Unit tests for the FormMetadataService.

Validates Requirements:
  - 9.1: create/update/delete/reorder form definitions on a draft version
          (blocked on a published version via guard_mutable).
  - 9.2: create/update/reorder sections and create/update/delete/reorder fields.
  - 9.3: all field control types are supported.
  - 9.4: all field attributes are persisted.
  - 9.5: code lists and code list items.
  - 9.6 / 5.2: every mutation writes an Audit_Event; published versions are immutable.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.models.form_metadata import (
    Codelist,
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.study import StudyVersion, StudyVersionStatus
from app.schemas.form_metadata import (
    CodelistCreate,
    CodelistItemCreate,
    ControlType,
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormDefinitionUpdate,
    FormSectionCreate,
    FormSectionUpdate,
)
from app.services.form_metadata_service import (
    FormMetadataService,
    form_metadata_service,
)

# Every control type listed in Requirement 9.3.
ALL_CONTROL_TYPES = list(ControlType)


@pytest.fixture
def service():
    return FormMetadataService()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _make_version(
    status: StudyVersionStatus = StudyVersionStatus.draft,
) -> StudyVersion:
    return StudyVersion(
        id=uuid.uuid4(),
        study_id=uuid.uuid4(),
        version_number="1.0",
        status=status,
        created_at=datetime.now(UTC),
    )


def _make_form(study_version_id: uuid.UUID | None = None) -> FormDefinition:
    return FormDefinition(
        id=uuid.uuid4(),
        study_version_id=study_version_id or uuid.uuid4(),
        name="Adverse Events",
        form_code="AE",
        display_order=0,
        is_repeating=True,
        created_at=datetime.now(UTC),
    )


def _make_section(form_definition_id: uuid.UUID | None = None) -> FormSection:
    return FormSection(
        id=uuid.uuid4(),
        form_definition_id=form_definition_id or uuid.uuid4(),
        name="General",
        display_order=0,
    )


def _make_field(form_section_id: uuid.UUID | None = None) -> FieldDefinition:
    return FieldDefinition(
        id=uuid.uuid4(),
        form_section_id=form_section_id or uuid.uuid4(),
        label="AE Term",
        variable_name="AETERM",
        control_type="text",
        data_type="string",
        is_required=True,
        display_order=0,
        is_read_only=False,
        is_calculated=False,
    )


def _make_codelist(study_version_id: uuid.UUID | None = None) -> Codelist:
    return Codelist(
        id=uuid.uuid4(),
        study_version_id=study_version_id or uuid.uuid4(),
        name="Severity",
        code="SEV",
    )


# ---------------------------------------------------------------------------
# Form definitions — Req 9.1
# ---------------------------------------------------------------------------


class TestCreateForm:
    async def test_create_form_persists(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        data = FormDefinitionCreate(
            name="Adverse Events", form_code="AE", display_order=0, is_repeating=True
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            form = await service.create_form(mock_session, version, data, actor_id)

        assert form.study_version_id == version.id
        assert form.name == "Adverse Events"
        assert form.form_code == "AE"
        assert form.is_repeating is True
        mock_session.add.assert_called_once()

    async def test_create_form_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        data = FormDefinitionCreate(name="AE", form_code="AE", display_order=0)

        with pytest.raises(BusinessRuleError):
            await service.create_form(mock_session, version, data, actor_id)

    async def test_create_form_writes_audit_event(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        data = FormDefinitionCreate(name="AE", form_code="AE", display_order=0)

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.create_form(mock_session, version, data, actor_id)

            mock_audit.record.assert_awaited_once()
            kwargs = mock_audit.record.call_args.kwargs
            assert kwargs["entity_type"] == "form_definition"
            assert kwargs["action"] == "create"
            assert kwargs["actor_id"] == actor_id
            assert kwargs["study_id"] == version.study_id


class TestUpdateForm:
    async def test_update_form_applies_changes(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        form = _make_form(version.id)
        data = FormDefinitionUpdate(name="AE (renamed)", display_order=3)

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.update_form(
                mock_session, version, form, data, actor_id
            )

        assert result.name == "AE (renamed)"
        assert result.display_order == 3
        assert result.form_code == "AE"  # unchanged
        mock_audit.record.assert_awaited_once()
        assert mock_audit.record.call_args.kwargs["action"] == "update"

    async def test_update_form_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        form = _make_form(version.id)

        with pytest.raises(BusinessRuleError):
            await service.update_form(
                mock_session, version, form, FormDefinitionUpdate(name="x"), actor_id
            )


class TestDeleteForm:
    async def test_delete_form(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        form = _make_form(version.id)

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.delete_form(mock_session, version, form, actor_id)

        mock_session.delete.assert_awaited_once_with(form)
        kwargs = mock_audit.record.call_args.kwargs
        assert kwargs["action"] == "delete"
        assert kwargs["entity_type"] == "form_definition"

    async def test_delete_form_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        form = _make_form(version.id)

        with pytest.raises(BusinessRuleError):
            await service.delete_form(mock_session, version, form, actor_id)


class TestReorderForms:
    async def test_reorder_assigns_display_order(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        f1 = _make_form(version.id)
        f2 = _make_form(version.id)
        f3 = _make_form(version.id)
        new_order = [f3.id, f1.id, f2.id]

        with (
            patch.object(
                service, "list_forms", AsyncMock(return_value=[f1, f2, f3])
            ),
            patch("app.services.form_metadata_service.audit_service") as mock_audit,
        ):
            mock_audit.record = AsyncMock()
            result = await service.reorder_forms(
                mock_session, version, new_order, actor_id
            )

        assert [f.id for f in result] == new_order
        assert f3.display_order == 0
        assert f1.display_order == 1
        assert f2.display_order == 2
        assert mock_audit.record.call_args.kwargs["action"] == "reorder"

    async def test_reorder_rejects_mismatched_ids(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        f1 = _make_form(version.id)
        f2 = _make_form(version.id)

        with (
            patch.object(service, "list_forms", AsyncMock(return_value=[f1, f2])),
            pytest.raises(ValidationError),
        ):
            await service.reorder_forms(
                mock_session, version, [f1.id, uuid.uuid4()], actor_id
            )

    async def test_reorder_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        with pytest.raises(BusinessRuleError):
            await service.reorder_forms(mock_session, version, [], actor_id)


# ---------------------------------------------------------------------------
# Sections — Req 9.2
# ---------------------------------------------------------------------------


class TestSections:
    async def test_create_section_persists(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        form = _make_form(version.id)
        data = FormSectionCreate(name="Demographics", display_order=1)

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            section = await service.create_section(
                mock_session, version, form, data, actor_id
            )

        assert section.form_definition_id == form.id
        assert section.name == "Demographics"
        kwargs = mock_audit.record.call_args.kwargs
        assert kwargs["entity_type"] == "form_section"
        assert kwargs["action"] == "create"

    async def test_create_section_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        form = _make_form(version.id)

        with pytest.raises(BusinessRuleError):
            await service.create_section(
                mock_session, version, form, FormSectionCreate(name="x", display_order=0), actor_id
            )

    async def test_update_section_applies_changes(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        section = _make_section()
        data = FormSectionUpdate(name="Renamed")

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.update_section(
                mock_session, version, section, data, actor_id
            )

        assert result.name == "Renamed"
        assert mock_audit.record.call_args.kwargs["action"] == "update"

    async def test_reorder_sections(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        form = _make_form(version.id)
        s1 = _make_section(form.id)
        s2 = _make_section(form.id)
        new_order = [s2.id, s1.id]

        with (
            patch.object(service, "list_sections", AsyncMock(return_value=[s1, s2])),
            patch("app.services.form_metadata_service.audit_service") as mock_audit,
        ):
            mock_audit.record = AsyncMock()
            result = await service.reorder_sections(
                mock_session, version, form, new_order, actor_id
            )

        assert [s.id for s in result] == new_order
        assert s2.display_order == 0
        assert s1.display_order == 1


# ---------------------------------------------------------------------------
# Fields — Req 9.2, 9.3, 9.4
# ---------------------------------------------------------------------------


class TestCreateField:
    async def test_create_field_persists_all_attributes(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        section = _make_section()
        codelist_id = uuid.uuid4()
        data = FieldDefinitionCreate(
            label="Weight",
            variable_name="WEIGHT",
            control_type=ControlType.decimal,
            data_type="decimal",
            display_order=2,
            is_required=True,
            codelist_id=codelist_id,
            default_value="0",
            help_text="Subject weight",
            unit="kg",
            min_value=Decimal("0.0"),
            max_value=Decimal("500.0"),
            max_length=10,
            decimal_precision=2,
            regex_validation=r"^\d+(\.\d+)?$",
            visibility_rule={"field": "ENROLLED", "operator": "==", "value": True},
            is_read_only=False,
            is_calculated=False,
            calculation_expression=None,
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            field = await service.create_field(
                mock_session, version, section, data, actor_id
            )

        assert field.form_section_id == section.id
        assert field.label == "Weight"
        assert field.variable_name == "WEIGHT"
        assert field.control_type == "decimal"
        assert field.data_type == "decimal"
        assert field.is_required is True
        assert field.codelist_id == codelist_id
        assert field.unit == "kg"
        assert field.min_value == Decimal("0.0")
        assert field.max_value == Decimal("500.0")
        assert field.max_length == 10
        assert field.decimal_precision == 2
        assert field.regex_validation == r"^\d+(\.\d+)?$"
        assert field.visibility_rule == {
            "field": "ENROLLED",
            "operator": "==",
            "value": True,
        }
        kwargs = mock_audit.record.call_args.kwargs
        assert kwargs["entity_type"] == "field_definition"
        assert kwargs["action"] == "create"

    @pytest.mark.parametrize("control_type", ALL_CONTROL_TYPES)
    async def test_create_field_supports_all_control_types(
        self, service, mock_session, actor_id, control_type
    ):
        version = _make_version(StudyVersionStatus.draft)
        section = _make_section()
        data = FieldDefinitionCreate(
            label="Field",
            variable_name="VAR",
            control_type=control_type,
            data_type="string",
            display_order=0,
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            field = await service.create_field(
                mock_session, version, section, data, actor_id
            )

        assert field.control_type == str(control_type)

    async def test_create_field_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        section = _make_section()
        data = FieldDefinitionCreate(
            label="x",
            variable_name="X",
            control_type=ControlType.text,
            data_type="string",
            display_order=0,
        )

        with pytest.raises(BusinessRuleError):
            await service.create_field(
                mock_session, version, section, data, actor_id
            )


class TestUpdateDeleteField:
    async def test_update_field_applies_changes(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        field = _make_field()
        data = FieldDefinitionUpdate(
            label="Updated Label", control_type=ControlType.textarea
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            result = await service.update_field(
                mock_session, version, field, data, actor_id
            )

        assert result.label == "Updated Label"
        assert result.control_type == "textarea"
        assert mock_audit.record.call_args.kwargs["action"] == "update"

    async def test_delete_field(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        field = _make_field()

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            await service.delete_field(mock_session, version, field, actor_id)

        mock_session.delete.assert_awaited_once_with(field)
        assert mock_audit.record.call_args.kwargs["action"] == "delete"

    async def test_reorder_fields(self, service, mock_session, actor_id):
        version = _make_version(StudyVersionStatus.draft)
        section = _make_section()
        f1 = _make_field(section.id)
        f2 = _make_field(section.id)
        new_order = [f2.id, f1.id]

        with (
            patch.object(service, "list_fields", AsyncMock(return_value=[f1, f2])),
            patch("app.services.form_metadata_service.audit_service") as mock_audit,
        ):
            mock_audit.record = AsyncMock()
            result = await service.reorder_fields(
                mock_session, version, section, new_order, actor_id
            )

        assert [f.id for f in result] == new_order
        assert f2.display_order == 0
        assert f1.display_order == 1


# ---------------------------------------------------------------------------
# Code lists — Req 9.5
# ---------------------------------------------------------------------------


class TestCodelists:
    async def test_create_codelist_with_items(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        data = CodelistCreate(
            name="Severity",
            code="SEV",
            items=[
                CodelistItemCreate(code="1", label="Mild", display_order=0),
                CodelistItemCreate(code="2", label="Moderate", display_order=1),
            ],
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            codelist = await service.create_codelist(
                mock_session, version, data, actor_id
            )

        assert codelist.study_version_id == version.id
        assert codelist.code == "SEV"
        # 1 codelist create + 2 item creates
        assert mock_audit.record.await_count == 3

    async def test_create_codelist_blocked_on_published(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.published)
        data = CodelistCreate(name="Severity", code="SEV")

        with pytest.raises(BusinessRuleError):
            await service.create_codelist(mock_session, version, data, actor_id)

    async def test_add_codelist_item_with_reference_ranges(
        self, service, mock_session, actor_id
    ):
        version = _make_version(StudyVersionStatus.draft)
        codelist = _make_codelist(version.id)
        data = CodelistItemCreate(
            code="HGB",
            label="Hemoglobin",
            display_order=0,
            normal_low=Decimal("12.0"),
            normal_high=Decimal("16.0"),
        )

        with patch("app.services.form_metadata_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()
            item = await service.add_codelist_item(
                mock_session, version, codelist, data, actor_id
            )

        assert item.codelist_id == codelist.id
        assert item.normal_low == Decimal("12.0")
        assert item.normal_high == Decimal("16.0")
        kwargs = mock_audit.record.call_args.kwargs
        assert kwargs["entity_type"] == "codelist_item"
        assert kwargs["action"] == "create"


# ---------------------------------------------------------------------------
# Getters
# ---------------------------------------------------------------------------


class TestGetters:
    async def test_get_form_returns(self, service, mock_session):
        expected = _make_form()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.get_form(mock_session, expected.id)
        assert result == expected

    async def test_get_form_raises_not_found(self, service, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_form(mock_session, uuid.uuid4())

    async def test_list_forms_returns_list(self, service, mock_session):
        forms = [_make_form(), _make_form()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = forms
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await service.list_forms(mock_session, uuid.uuid4())
        assert result == forms

    async def test_get_field_raises_not_found(self, service, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_field(mock_session, uuid.uuid4())

    async def test_get_codelist_raises_not_found(self, service, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await service.get_codelist(mock_session, uuid.uuid4())


class TestSingleton:
    def test_singleton_exists(self):
        assert form_metadata_service is not None
        assert isinstance(form_metadata_service, FormMetadataService)
