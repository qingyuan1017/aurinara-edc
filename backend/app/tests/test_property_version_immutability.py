"""Property-based tests for published-version immutability.

**Validates: Requirements 5.2, 9.1, 9.2, 12.6**

Property 10: Published study versions are immutable.

Uses Hypothesis to verify that:
1. guard_mutable() raises BusinessRuleError if and only if the version status is "published"
2. All metadata-modifying service methods (define_visit, create_form, create_section,
   create_field) call guard_mutable and are blocked on published versions
3. Draft versions allow all modifications (guard_mutable does not raise)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.core.exceptions import BusinessRuleError
from app.models.study import StudyVersion, StudyVersionStatus
from app.schemas.form_metadata import (
    FieldDefinitionCreate,
    FormDefinitionCreate,
    FormSectionCreate,
)
from app.schemas.visit import VisitDefinitionCreate
from app.services.form_metadata_service import FormMetadataService
from app.services.study_version_service import StudyVersionService
from app.services.visit_service import VisitService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

version_status_strategy = st.sampled_from([StudyVersionStatus.draft, StudyVersionStatus.published])

form_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

form_code_strategy = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
).filter(lambda s: s.strip())

display_order_strategy = st.integers(min_value=0, max_value=1000)

visit_number_strategy = st.integers(min_value=1, max_value=100)

visit_type_strategy = st.sampled_from(["scheduled", "unscheduled", "screening"])

variable_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)

control_type_strategy = st.sampled_from([
    "text", "textarea", "integer", "decimal", "date",
    "dropdown", "radio", "checkbox",
])

data_type_strategy = st.sampled_from(["string", "integer", "decimal", "date", "boolean"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_version(status: StudyVersionStatus) -> MagicMock:
    """Create a minimal StudyVersion mock with the given status."""
    version = MagicMock(spec=StudyVersion)
    version.id = uuid.uuid4()
    version.study_id = uuid.uuid4()
    version.version_number = "1.0"
    version.status = status
    version.published_at = datetime.now(UTC) if status == StudyVersionStatus.published else None
    version.published_by = uuid.uuid4() if status == StudyVersionStatus.published else None
    return version


def _make_form_definition():
    """Create a minimal FormDefinition mock for testing."""
    form = MagicMock()
    form.id = uuid.uuid4()
    return form


def _make_form_section():
    """Create a minimal FormSection mock for testing."""
    section = MagicMock()
    section.id = uuid.uuid4()
    return section


def _make_session():
    """Create an AsyncMock session with sync .add() to avoid coroutine warnings."""
    session = AsyncMock()
    session.add = MagicMock()  # session.add is sync in SQLAlchemy
    return session


# ---------------------------------------------------------------------------
# Property 10: Published study versions are immutable
# ---------------------------------------------------------------------------


class TestGuardMutableProperty:
    """Property-based tests for guard_mutable behavior.

    **Validates: Requirements 5.2, 9.1, 9.2, 12.6**
    """

    @settings(max_examples=200)
    @given(status=version_status_strategy)
    def test_guard_mutable_raises_iff_published(self, status: StudyVersionStatus):
        """guard_mutable raises BusinessRuleError if and only if the version is published."""
        service = StudyVersionService()
        version = _make_version(status)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                service.guard_mutable(version)
        else:
            # Must NOT raise for draft
            service.guard_mutable(version)

    @settings(max_examples=200)
    @given(status=version_status_strategy)
    def test_draft_versions_allow_all_modifications(self, status: StudyVersionStatus):
        """Draft versions pass guard_mutable without raising; published never pass."""
        service = StudyVersionService()
        version = _make_version(status)

        raised = False
        try:
            service.guard_mutable(version)
        except BusinessRuleError:
            raised = True

        if status == StudyVersionStatus.draft:
            assert not raised, "Draft versions must allow modifications"
        else:
            assert raised, "Published versions must block modifications"


class TestFormMetadataImmutabilityProperty:
    """Property-based tests for form_metadata_service enforcing immutability.

    **Validates: Requirements 5.2, 9.1, 9.2**
    """

    @settings(max_examples=100)
    @given(
        status=version_status_strategy,
        name=form_name_strategy,
        form_code=form_code_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_form_blocked_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        form_code: str,
        display_order: int,
    ):
        """create_form calls guard_mutable and is blocked on published versions."""
        service = FormMetadataService()
        version = _make_version(status)
        actor_id = uuid.uuid4()
        session = _make_session()

        data = FormDefinitionCreate(
            name=name,
            form_code=form_code,
            display_order=display_order,
            is_repeating=False,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_form(session, version, data, actor_id)
        else:
            # For draft, the DB flush/audit calls will happen — mock them
            with patch("app.services.form_metadata_service.audit_service") as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_form(session, version, data, actor_id)

    @settings(max_examples=100)
    @given(
        status=version_status_strategy,
        name=form_name_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_section_blocked_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        display_order: int,
    ):
        """create_section calls guard_mutable and is blocked on published versions."""
        service = FormMetadataService()
        version = _make_version(status)
        actor_id = uuid.uuid4()
        session = _make_session()
        form = _make_form_definition()

        data = FormSectionCreate(name=name, display_order=display_order)

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_section(session, version, form, data, actor_id)
        else:
            with patch("app.services.form_metadata_service.audit_service") as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_section(session, version, form, data, actor_id)

    @settings(max_examples=100)
    @given(
        status=version_status_strategy,
        label=form_name_strategy,
        variable_name=variable_name_strategy,
        control_type=control_type_strategy,
        data_type=data_type_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_create_field_blocked_on_published(
        self,
        status: StudyVersionStatus,
        label: str,
        variable_name: str,
        control_type: str,
        data_type: str,
        display_order: int,
    ):
        """create_field calls guard_mutable and is blocked on published versions."""
        service = FormMetadataService()
        version = _make_version(status)
        actor_id = uuid.uuid4()
        session = _make_session()
        section = _make_form_section()

        data = FieldDefinitionCreate(
            label=label,
            variable_name=variable_name,
            control_type=control_type,
            data_type=data_type,
            display_order=display_order,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.create_field(session, version, section, data, actor_id)
        else:
            with patch("app.services.form_metadata_service.audit_service") as mock_audit:
                mock_audit.record = AsyncMock()
                await service.create_field(session, version, section, data, actor_id)


class TestVisitServiceImmutabilityProperty:
    """Property-based tests for visit_service enforcing immutability.

    **Validates: Requirements 5.2, 12.6**
    """

    @settings(max_examples=100)
    @given(
        status=version_status_strategy,
        name=form_name_strategy,
        visit_number=visit_number_strategy,
        visit_type=visit_type_strategy,
        display_order=display_order_strategy,
    )
    @pytest.mark.asyncio
    async def test_define_visit_blocked_on_published(
        self,
        status: StudyVersionStatus,
        name: str,
        visit_number: int,
        visit_type: str,
        display_order: int,
    ):
        """define_visit calls guard_mutable and is blocked on published versions."""
        service = VisitService()
        version = _make_version(status)
        actor_id = uuid.uuid4()
        session = _make_session()

        data = VisitDefinitionCreate(
            name=name,
            visit_number=visit_number,
            visit_type=visit_type,
            display_order=display_order,
            is_required=True,
        )

        if status == StudyVersionStatus.published:
            with pytest.raises(BusinessRuleError):
                await service.define_visit(session, version, data, actor_id)
        else:
            with patch("app.services.visit_service.audit_service") as mock_audit:
                mock_audit.record = AsyncMock()
                await service.define_visit(session, version, data, actor_id)
