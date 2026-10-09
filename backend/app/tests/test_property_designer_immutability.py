"""Property-based test for published-design immutability.

# Feature: designer-edc-refactor, Property 3: Published-design immutability

**Validates: Requirements 2.4**

Property 3 (design.md): _For all_ Published_Designs and all mutation attempts
targeting a published Design_Version or any of its child Designer_Definitions,
the modification is rejected and the targeted value is unchanged.

The immutability guard is ``StudyVersionService.guard_mutable`` in
``app.services.designer.study_version_service``. It is called by every Designer
child service before any mutation to a Design_Version child
Designer_Definition:

  - ``form_metadata_service``   — forms, sections, fields, code lists
  - ``visit_definition_service`` — visit definitions
  - ``edit_check_service``      — edit-check rules
  - ``codelist_service``        — code lists

This suite drives a representative mutation on each of those services across
randomly generated inputs and asserts that, when the owning Design_Version is a
Published_Design:

  1. the mutation raises :class:`BusinessRuleError` (the modification is
     rejected), and
  2. the targeted value is left unchanged — no row is added, flushed, or
     deleted through the session, and the version's own fields are untouched.

For a Draft_Design the same mutation passes the guard (it does not raise
``BusinessRuleError``), confirming the rejection is specific to the published
state and not a blanket block.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.form_metadata import (
    ControlType,
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FormDefinitionCreate,
    FormDefinitionUpdate,
    FormSectionCreate,
    FormSectionUpdate,
)
from app.schemas.designer.visit import VisitDefinitionCreate
from app.schemas.edc.edit_check import EditCheckCreate, EditCheckUpdate
from app.schemas.edc.form_metadata import CodelistCreate, CodelistItemCreate
from app.services.designer.codelist_service import CodelistService
from app.services.designer.edit_check_service import EditCheckService
from app.services.designer.form_metadata_service import FormMetadataService
from app.services.designer.study_version_service import StudyVersionService
from app.services.designer.visit_definition_service import VisitDefinitionService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

version_status_strategy = st.sampled_from(
    [StudyVersionStatus.draft, StudyVersionStatus.published]
)

# Short, non-blank text usable for names/labels (letters, numbers, spaces).
text_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

code_strategy = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
).filter(lambda s: s.strip())

display_order_strategy = st.integers(min_value=0, max_value=1000)

variable_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)

control_type_strategy = st.sampled_from(list(ControlType))

data_type_strategy = st.sampled_from(
    ["string", "integer", "decimal", "date", "boolean"]
)

visit_number_strategy = st.integers(min_value=1, max_value=9999)

visit_type_strategy = st.sampled_from(["scheduled", "unscheduled", "screening"])

severity_strategy = st.sampled_from(["info", "warning", "error", "query"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_version(status: StudyVersionStatus) -> MagicMock:
    """Build a minimal Design_Version mock in the given status.

    A spec'd mock is used so attribute mutation is still observable: the test
    snapshots the version's fields before the mutation attempt and asserts they
    are unchanged afterward (the "targeted value is unchanged" half of P3).
    """
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    version.version_number = "1.0"
    version.status = status
    published = status == StudyVersionStatus.published
    version.published_at = datetime.now(UTC) if published else None
    version.published_by = uuid.uuid4() if published else None
    return version


def _make_child(**attrs) -> MagicMock:
    """Build a minimal child Designer_Definition mock (form/section/field…)."""
    child = MagicMock()
    child.id = uuid.uuid4()
    for key, value in attrs.items():
        setattr(child, key, value)
    return child


def _make_session() -> AsyncMock:
    """An AsyncMock session with a synchronous ``.add`` like SQLAlchemy.

    ``execute`` returns the most-recently-added instance so that the "re-load
    with relationships" step inside the draft (allowed) path serializes without
    emitting a real lazy load.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    def _execute(*_args, **_kwargs):
        result = MagicMock()
        added = session.add.call_args[0][0] if session.add.call_args else None
        result.scalars.return_value.one.return_value = added
        result.scalars.return_value.first.return_value = added
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.flush = AsyncMock()
    return session


def _assert_version_unchanged(version: MagicMock, snapshot: dict) -> None:
    """Assert the Design_Version's own fields were not mutated (P3)."""
    assert version.status == snapshot["status"]
    assert version.published_at == snapshot["published_at"]
    assert version.published_by == snapshot["published_by"]
    assert version.version_number == snapshot["version_number"]


def _assert_no_writes(session: AsyncMock) -> None:
    """Assert no row was added, flushed, or deleted through the session (P3)."""
    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.delete.assert_not_called()


def _snapshot(version: MagicMock) -> dict:
    return {
        "status": version.status,
        "published_at": version.published_at,
        "published_by": version.published_by,
        "version_number": version.version_number,
    }


# ---------------------------------------------------------------------------
# Property 3: Published-design immutability
# ---------------------------------------------------------------------------


class TestPublishedDesignImmutabilityProperty:
    """Property 3 — mutations on a Published_Design are rejected and inert.

    # Feature: designer-edc-refactor, Property 3: Published-design immutability

    **Validates: Requirements 2.4**
    """

    # -- guard_mutable itself ------------------------------------------------

    @settings(max_examples=200, deadline=None)
    @given(status=version_status_strategy)
    def test_guard_mutable_rejects_exactly_published(
        self, status: StudyVersionStatus
    ):
        """guard_mutable raises iff the version is a Published_Design (R2.4)."""
        service = StudyVersionService()
        version = _make_version(status)
        snapshot = _snapshot(version)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                service.guard_mutable(version)
        else:
            service.guard_mutable(version)  # must not raise for a Draft_Design

        _assert_version_unchanged(version, snapshot)

    # -- form_metadata_service: create form ---------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        name=text_strategy,
        form_code=code_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_form_rejected_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        form_code: str,
        display_order: int,
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        data = FormDefinitionCreate(
            name=name,
            form_code=form_code,
            display_order=display_order,
            is_repeating=False,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_form(session, version, data, uuid.uuid4())
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_form(session, version, data, uuid.uuid4())

    # -- form_metadata_service: update form (edit an existing child) ---------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        new_name=text_strategy,
    )
    @pytest.mark.asyncio
    async def test_update_form_rejected_on_published(
        self, status: StudyVersionStatus, new_name: str
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        form = _make_child(name="original", form_code="DM", display_order=0)
        data = FormDefinitionUpdate(name=new_name)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.update_form(session, version, form, data, uuid.uuid4())
            # The targeted child's value is unchanged (R2.4).
            assert form.name == "original"
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.update_form(session, version, form, data, uuid.uuid4())
            assert form.name == new_name

    # -- form_metadata_service: delete form ----------------------------------

    @settings(max_examples=100, deadline=None)
    @given(status=version_status_strategy)
    @pytest.mark.asyncio
    async def test_delete_form_rejected_on_published(
        self, status: StudyVersionStatus
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        form = _make_child(name="DM", form_code="DM")

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.delete_form(session, version, form, uuid.uuid4())
            session.delete.assert_not_called()
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.delete_form(session, version, form, uuid.uuid4())
            session.delete.assert_awaited()

    # -- form_metadata_service: create section -------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        name=text_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_section_rejected_on_published(
        self, status: StudyVersionStatus, name: str, display_order: int
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        form = _make_child()
        data = FormSectionCreate(name=name, display_order=display_order)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_section(
                    session, version, form, data, uuid.uuid4()
                )
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_section(
                    session, version, form, data, uuid.uuid4()
                )

    # -- form_metadata_service: update section -------------------------------

    @settings(max_examples=100, deadline=None)
    @given(status=version_status_strategy, new_name=text_strategy)
    @pytest.mark.asyncio
    async def test_update_section_rejected_on_published(
        self, status: StudyVersionStatus, new_name: str
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        section = _make_child(name="original", display_order=0)
        data = FormSectionUpdate(name=new_name)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.update_section(
                    session, version, section, data, uuid.uuid4()
                )
            assert section.name == "original"
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.update_section(
                    session, version, section, data, uuid.uuid4()
                )
            assert section.name == new_name

    # -- form_metadata_service: create field ---------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        label=text_strategy,
        variable_name=variable_name_strategy,
        control_type=control_type_strategy,
        data_type=data_type_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_field_rejected_on_published(
        self,
        status: StudyVersionStatus,
        label: str,
        variable_name: str,
        control_type: ControlType,
        data_type: str,
        display_order: int,
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        section = _make_child()
        data = FieldDefinitionCreate(
            label=label,
            variable_name=variable_name,
            control_type=control_type,
            data_type=data_type,
            display_order=display_order,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_field(
                    session, version, section, data, uuid.uuid4()
                )
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_field(
                    session, version, section, data, uuid.uuid4()
                )

    # -- form_metadata_service: update field ---------------------------------

    @settings(max_examples=100, deadline=None)
    @given(status=version_status_strategy, new_label=text_strategy)
    @pytest.mark.asyncio
    async def test_update_field_rejected_on_published(
        self, status: StudyVersionStatus, new_label: str
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        field = _make_child(label="original", variable_name="age")
        data = FieldDefinitionUpdate(label=new_label)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.update_field(
                    session, version, field, data, uuid.uuid4()
                )
            assert field.label == "original"
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.update_field(
                    session, version, field, data, uuid.uuid4()
                )
            assert field.label == new_label

    # -- form_metadata_service: create code list -----------------------------

    @settings(max_examples=100, deadline=None)
    @given(status=version_status_strategy, name=text_strategy, code=code_strategy)
    @pytest.mark.asyncio
    async def test_create_codelist_via_form_service_rejected_on_published(
        self, status: StudyVersionStatus, name: str, code: str
    ):
        service = FormMetadataService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        data = CodelistCreate(name=name, code=code, items=[])

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_codelist(session, version, data, uuid.uuid4())
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.form_metadata_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_codelist(session, version, data, uuid.uuid4())

    # -- visit_definition_service: define visit ------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        name=text_strategy,
        visit_number=visit_number_strategy,
        visit_type=visit_type_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_define_visit_rejected_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        visit_number: int,
        visit_type: str,
        display_order: int,
    ):
        service = VisitDefinitionService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        data = VisitDefinitionCreate(
            name=name,
            visit_number=visit_number,
            visit_type=visit_type,
            display_order=display_order,
            is_required=True,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.define_visit(session, version, data, uuid.uuid4())
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.visit_definition_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.define_visit(session, version, data, uuid.uuid4())

    # -- codelist_service: create codelist -----------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        name=text_strategy,
        code=code_strategy,
        item_code=code_strategy,
        item_label=text_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_codelist_rejected_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        code: str,
        item_code: str,
        item_label: str,
    ):
        service = CodelistService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        data = CodelistCreate(
            name=name,
            code=code,
            items=[
                CodelistItemCreate(code=item_code, label=item_label, display_order=0)
            ],
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_codelist(session, version, data, uuid.uuid4())
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.codelist_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_codelist(session, version, data, uuid.uuid4())

    # -- edit_check_service: create edit check -------------------------------

    @settings(max_examples=100, deadline=None)
    @given(
        status=version_status_strategy,
        name=text_strategy,
        severity=severity_strategy,
        threshold=st.integers(min_value=0, max_value=120),
    )
    @pytest.mark.asyncio
    async def test_create_edit_check_rejected_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        severity: str,
        threshold: int,
    ):
        service = EditCheckService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        data = EditCheckCreate(
            name=name,
            rule_json={"field": "age", "operator": ">", "value": threshold},
            severity=severity,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_edit_check(session, version, data, uuid.uuid4())
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.edit_check_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                with patch.object(
                    service.repository, "add", AsyncMock()
                ):
                    await service.create_edit_check(
                        session, version, data, uuid.uuid4()
                    )

    # -- edit_check_service: update edit check -------------------------------

    @settings(max_examples=100, deadline=None)
    @given(status=version_status_strategy, new_name=text_strategy)
    @pytest.mark.asyncio
    async def test_update_edit_check_rejected_on_published(
        self, status: StudyVersionStatus, new_name: str
    ):
        service = EditCheckService()
        version = _make_version(status)
        session = _make_session()
        snapshot = _snapshot(version)
        edit_check = _make_child(
            name="original",
            rule_json={"field": "age", "operator": ">", "value": 18},
            severity="warning",
            is_active=True,
        )
        data = EditCheckUpdate(name=new_name)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.update_edit_check(
                    session, version, edit_check, data, uuid.uuid4()
                )
            assert edit_check.name == "original"
            _assert_no_writes(session)
            _assert_version_unchanged(version, snapshot)
        else:
            with patch(
                "app.services.designer.edit_check_service.audit_service"
            ) as mock_audit:
                mock_audit.record = AsyncMock()
                with patch.object(service.repository, "flush", AsyncMock()):
                    await service.update_edit_check(
                        session, version, edit_check, data, uuid.uuid4()
                    )
            assert edit_check.name == new_name
