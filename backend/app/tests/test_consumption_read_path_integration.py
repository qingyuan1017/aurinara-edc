"""Integration test for the design-dependent study-info read-path.

# Feature: designer-edc-refactor, Task 11.4

**Validates: Requirements 8.14**

R8.14: THE EDC_Module SHALL read all design-dependent configuration in the
``Study_Info_Area`` from the bound ``Published_Design`` through the
``Design_Consumption_Contract``.

The contract is realised by :class:`DesignConsumptionService`
(``app.services.designer.design_consumption_service``, singleton
``design_consumption_service``). This integration test proves two things end to
end against a real (in-memory SQLite) published design:

1.  **The read-path routes through the contract.** Design-dependent study-info
    reads (forms, fields, visits, codelists, the aggregate published design, the
    "latest published design", and the ``permits_unscheduled_visits`` capability
    flag) go through ``design_consumption_service`` and return the published
    content as *frozen views* — Pydantic view models from
    ``app.schemas.designer.views``, never mutable ORM entities.

2.  **The read-path never touches a designer write path.** Reading creates or
    modifies no Designer_Definition rows: every designer table's row count and
    the stored values of a sampled definition are identical before and after a
    full read, and the consumption port exposes no mutating method
    (create/update/delete/publish/amend/save). A *draft* version is rejected,
    reinforcing one-directional, read-only, published-only consumption.

Seeding/engine patterns follow ``test_property_published_only_consumption.py``,
``test_edit_check_routes.py`` and ``test_subject_phase_service.py``.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ValidationError
from app.models.designer.codelist import Codelist, CodelistItem
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_metadata import (
    FieldDefinition,
    FormDefinition,
    FormSection,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.schemas.designer.views import (
    CodelistView,
    FormDefinitionView,
    PublishedDesignView,
    VisitDefinitionView,
)
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
    design_consumption_service,
)

# ---------------------------------------------------------------------------
# Designer tables whose row counts must be unchanged by any read (write-path
# detection). These are the design-time definition sets the consumption
# contract reads from.
# ---------------------------------------------------------------------------

_DESIGNER_MODELS = (
    StudyVersion,
    FormDefinition,
    FormSection,
    FieldDefinition,
    VisitDefinition,
    Codelist,
    CodelistItem,
    EditCheck,
    SubjectPhaseDefinition,
)

# Verb prefixes that would indicate a mutation (write-path) surface. The
# consumption port exposes only read verbs (get_/list_/permits_), so any public
# method beginning with a mutating verb would be a write path. Matching the
# leading verb (rather than any substring) avoids false hits like the "publish"
# inside the read-only ``get_published_design``.
_MUTATION_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "publish_",
    "amend_",
    "save_",
    "insert_",
    "persist_",
    "add_",
    "remove_",
    "set_",
    "write_",
    "upsert_",
)

# The only verbs a read-only consumption port should expose.
_READ_PREFIXES = ("get_", "list_", "permits_")


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import app.models  # noqa: F401  (register every ORM table)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(async_engine):
    return async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _build_published_design(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Seed a Study + a *published* Design_Version with design-time content.

    Returns the study id and the published ``design_version_id`` the EDC
    study-info read-path will consume.
    """
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Consumption Read-Path Study",
        status=StudyStatus.active,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
    )
    session.add(version)
    await session.flush()

    # --- Forms + sections + fields ---------------------------------------
    form = FormDefinition(
        study_version_id=version.id,
        name="Demographics",
        form_code="DM",
        display_order=1,
        is_repeating=False,
    )
    session.add(form)
    await session.flush()
    section = FormSection(
        form_definition_id=form.id,
        name="Basics",
        display_order=1,
    )
    session.add(section)
    await session.flush()
    session.add(
        FieldDefinition(
            form_section_id=section.id,
            label="Age",
            variable_name="age",
            control_type="integer",
            data_type="integer",
            is_required=True,
            display_order=1,
        )
    )

    # --- Visits (one scheduled, one unscheduled so the flag is True) ------
    session.add(
        VisitDefinition(
            study_version_id=version.id,
            name="Screening",
            visit_number=1,
            visit_type="scheduled",
            display_order=1,
            is_required=True,
        )
    )
    session.add(
        VisitDefinition(
            study_version_id=version.id,
            name="Unscheduled",
            visit_number=2,
            visit_type="unscheduled",
            display_order=2,
            is_required=False,
        )
    )

    # --- Codelist + items -------------------------------------------------
    codelist = Codelist(
        study_version_id=version.id,
        name="Gender",
        code="GENDER",
    )
    session.add(codelist)
    await session.flush()
    session.add_all(
        [
            CodelistItem(
                codelist_id=codelist.id, code="M", label="Male", display_order=1
            ),
            CodelistItem(
                codelist_id=codelist.id, code="F", label="Female", display_order=2
            ),
        ]
    )

    await session.commit()
    return {"study_id": study.id, "design_version_id": version.id}


async def _designer_row_counts(session: AsyncSession) -> dict[str, int]:
    """Snapshot the row count of every designer definition table."""
    counts: dict[str, int] = {}
    for model in _DESIGNER_MODELS:
        total = (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()
        counts[model.__name__] = total
    return counts


def _assert_frozen_view(value: object) -> None:
    """Assert ``value`` is a frozen view model, never a mutable ORM entity."""
    assert isinstance(value, BaseModel), (
        f"read-path returned a non-view object: {type(value)!r}"
    )
    assert value.model_config.get("frozen") is True, (
        f"view {type(value).__name__} is not frozen"
    )
    field_names = list(type(value).model_fields)
    assert field_names, f"view {type(value).__name__} has no fields"
    probe = field_names[0]
    with pytest.raises(PydanticValidationError):
        setattr(value, probe, getattr(value, probe))


class TestConsumptionReadPathIntegration:
    """R8.14: study-info reads route through the read-only consumption port."""

    async def test_study_info_reads_route_through_consumption_contract(
        self, session_factory
    ):
        """The read-path returns published content as frozen views (R8.14)."""
        async with session_factory() as seed:
            ids = await _build_published_design(seed)
        design_version_id = ids["design_version_id"]
        study_id = ids["study_id"]

        async with session_factory() as read_session:
            # Aggregate published design — the whole Study_Info source of truth.
            design = await design_consumption_service.get_published_design(
                read_session, design_version_id
            )
            assert isinstance(design, PublishedDesignView)
            assert design.design_version_id == design_version_id
            assert design.study_id == study_id
            assert design.status == str(StudyVersionStatus.published)
            _assert_frozen_view(design)

            # Forms + their flattened fields.
            forms = await design_consumption_service.list_forms(
                read_session, design_version_id
            )
            assert [f.name for f in forms] == ["Demographics"]
            assert all(isinstance(f, FormDefinitionView) for f in forms)
            _assert_frozen_view(forms[0])
            fields = await design_consumption_service.get_form_fields(
                read_session, design_version_id, forms[0].id
            )
            assert [field.variable_name for field in fields] == ["age"]

            # Visit definitions.
            visits = await design_consumption_service.list_visit_definitions(
                read_session, design_version_id
            )
            assert {v.name for v in visits} == {"Screening", "Unscheduled"}
            assert all(isinstance(v, VisitDefinitionView) for v in visits)

            # Codelists + items.
            codelists = await design_consumption_service.list_codelists(
                read_session, design_version_id
            )
            assert [c.name for c in codelists] == ["Gender"]
            assert isinstance(codelists[0], CodelistView)
            assert {item.code for item in codelists[0].items} == {"M", "F"}

            # Capability flag read from published content (R7.5 path, R8.14).
            assert (
                await design_consumption_service.permits_unscheduled_visits(
                    read_session, design_version_id
                )
                is True
            )

            # "Latest published design" resolves by study id to the same view.
            latest = (
                await design_consumption_service.get_latest_published_design(
                    read_session, study_id
                )
            )
            assert latest is not None
            assert latest.design_version_id == design_version_id

    async def test_read_path_never_touches_a_designer_write_path(
        self, session_factory
    ):
        """Reading creates/modifies no designer rows and offers no write API.

        A robust, implementation-agnostic check that the EDC read-path is
        strictly one-directional (R8.14): count every designer definition table
        and sample a definition's stored values before and after a full read,
        then assert nothing changed. Also assert the consumption port exposes no
        mutating method, so there is no write path to touch.
        """
        async with session_factory() as seed:
            ids = await _build_published_design(seed)
        design_version_id = ids["design_version_id"]
        study_id = ids["study_id"]

        # Snapshot designer state before any read.
        async with session_factory() as before_session:
            counts_before = await _designer_row_counts(before_session)
            sampled_form_before = (
                await before_session.execute(
                    select(FormDefinition).where(
                        FormDefinition.study_version_id == design_version_id
                    )
                )
            ).scalars().first()
            form_name_before = sampled_form_before.name
            form_code_before = sampled_form_before.form_code

        # Exercise the whole study-info read-path through the contract.
        async with session_factory() as read_session:
            await design_consumption_service.get_published_design(
                read_session, design_version_id
            )
            await design_consumption_service.get_latest_published_design(
                read_session, study_id
            )
            await design_consumption_service.list_forms(
                read_session, design_version_id
            )
            await design_consumption_service.list_visit_definitions(
                read_session, design_version_id
            )
            await design_consumption_service.list_cycle_definitions(
                read_session, design_version_id
            )
            await design_consumption_service.list_arm_definitions(
                read_session, design_version_id
            )
            await design_consumption_service.list_edit_check_rules(
                read_session, design_version_id
            )
            await design_consumption_service.list_codelists(
                read_session, design_version_id
            )
            await design_consumption_service.list_subject_phase_definitions(
                read_session, design_version_id
            )
            await design_consumption_service.get_schedule_of_assessment(
                read_session, design_version_id
            )
            await design_consumption_service.list_crf_access_definitions(
                read_session, design_version_id
            )
            await design_consumption_service.list_raw_data_variable_settings(
                read_session, design_version_id
            )
            await design_consumption_service.list_coding_settings(
                read_session, design_version_id
            )
            await design_consumption_service.permits_unscheduled_visits(
                read_session, design_version_id
            )
            # A read never commits anything; be explicit the read session is clean.
            assert not read_session.new
            assert not read_session.dirty
            assert not read_session.deleted

        # Snapshot designer state after the full read.
        async with session_factory() as after_session:
            counts_after = await _designer_row_counts(after_session)
            sampled_form_after = (
                await after_session.execute(
                    select(FormDefinition).where(
                        FormDefinition.study_version_id == design_version_id
                    )
                )
            ).scalars().first()

        # No designer rows were created, deleted, or modified by the read-path.
        assert counts_after == counts_before
        assert sampled_form_after.name == form_name_before
        assert sampled_form_after.form_code == form_code_before

        # The consumption port exposes no mutating (write-path) method.
        public_methods = [
            name
            for name in dir(DesignConsumptionService)
            if not name.startswith("_") and callable(getattr(DesignConsumptionService, name))
        ]
        assert public_methods, "consumption port exposed no methods"
        for name in public_methods:
            lowered = name.lower()
            assert not lowered.startswith(_MUTATION_PREFIXES), (
                f"consumption port exposes a write-path method: {name!r}"
            )
            # Every exposed verb is a read verb — there is no non-read surface.
            assert lowered.startswith(_READ_PREFIXES), (
                f"consumption port exposes a non-read method: {name!r}"
            )

    async def test_draft_version_is_rejected_published_only(self, session_factory):
        """A draft Design_Version is never readable through the contract (R8.14).

        One-directional consumption is published-only: pointing the study-info
        read-path at a *draft* version rejects it rather than leaking draft
        content, so the EDC_Module reads only from a bound Published_Design.
        """
        async with session_factory() as seed:
            study = Study(
                study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
                title="Draft Only Study",
                status=StudyStatus.draft,
                created_by=uuid.uuid4(),
            )
            seed.add(study)
            await seed.flush()
            draft = StudyVersion(
                study_id=study.id,
                version_number="1.0",
                status=StudyVersionStatus.draft,
            )
            seed.add(draft)
            await seed.flush()
            draft_id = draft.id
            study_id = study.id
            await seed.commit()

        async with session_factory() as read_session:
            with pytest.raises(ValidationError):
                await design_consumption_service.get_published_design(
                    read_session, draft_id
                )
            with pytest.raises(ValidationError):
                await design_consumption_service.list_forms(
                    read_session, draft_id
                )
            # The study has no published version, so "latest published" is None.
            assert (
                await design_consumption_service.get_latest_published_design(
                    read_session, study_id
                )
                is None
            )
