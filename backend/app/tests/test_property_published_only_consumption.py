"""Property-based test for one-directional, published-only consumption.

# Feature: designer-edc-refactor, Property 2: One-directional, published-only consumption

**Validates: Requirements 2.5, 2.6**

Property 2 (design.md): _For all_ reads performed by the EDC_Module through the
Design_Consumption_Contract, the result contains only Published_Design content
(never Draft_Design content) and is a read-only view that exposes no path to
mutate Designer state.

The read port under test is ``DesignConsumptionService`` in
``app.services.designer.design_consumption_service`` — the sole way the
EDC_Module reads a ``Published_Design``. Its two guarantees are exercised here:

  - **Published-only (R2.5).** A *draft* ``design_version_id`` is always
    rejected with :class:`ValidationError` and never leaks content; a missing id
    raises :class:`NotFoundError`. A *published* id returns content. The same
    randomly generated design is read in both states, so the only difference
    between "content returned" and "rejected" is the published flag.
  - **Read-only frozen views (R2.6).** Every object returned by every read
    method is a frozen Pydantic view from ``app.schemas.designer.views`` — never
    a mutable SQLAlchemy ORM entity — and attribute assignment on any returned
    view (or nested view) raises, so a consumer can never mutate Designer state
    through a consumed definition.

Following ``test_property_designer_round_trip.py`` and
``test_subject_phase_service.py``, each example builds a fresh in-memory SQLite
async database so examples stay independent, persists a randomly shaped design,
then reads it back through the consumption contract.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import NotFoundError, ValidationError
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
from app.schemas.designer.views import PublishedDesignView
from app.services.designer.design_consumption_service import (
    DesignConsumptionService,
)

# ---------------------------------------------------------------------------
# Strategies — a randomly shaped design (forms, visits, codelists, …)
# ---------------------------------------------------------------------------

_name_alphabet = st.characters(categories=("L", "N", "P"))


def _bounded_name(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    """Non-whitespace-padded names within an inclusive length window."""
    return st.text(
        alphabet=_name_alphabet, min_size=min_size, max_size=max_size
    ).filter(lambda value: value == value.strip() and len(value) >= min_size)


_variable_names = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)
_visit_types = st.sampled_from(["scheduled", "unscheduled", "screening"])


@st.composite
def _design_shape(draw: st.DrawFn) -> dict[str, object]:
    """A declarative description of a design's child definitions.

    The shape is independent of the publish state; the test applies the same
    shape to both a draft and a published version so the only variable is the
    status gate (R2.5).
    """
    form_count = draw(st.integers(min_value=0, max_value=3))
    forms: list[dict[str, object]] = []
    for _ in range(form_count):
        section_count = draw(st.integers(min_value=0, max_value=2))
        sections: list[dict[str, object]] = []
        for _ in range(section_count):
            field_count = draw(st.integers(min_value=0, max_value=3))
            sections.append(
                {
                    "name": draw(_bounded_name(1, 50)),
                    "fields": [
                        {
                            "label": draw(_bounded_name(1, 50)),
                            "variable_name": draw(_variable_names),
                            "control_type": draw(
                                st.sampled_from(["text", "integer", "dropdown"])
                            ),
                            "data_type": draw(
                                st.sampled_from(["string", "integer", "date"])
                            ),
                        }
                        for _ in range(field_count)
                    ],
                }
            )
        forms.append(
            {
                "name": draw(_bounded_name(1, 50)),
                "form_code": draw(_bounded_name(1, 10)),
                "is_repeating": draw(st.booleans()),
                "sections": sections,
            }
        )

    visit_count = draw(st.integers(min_value=0, max_value=4))
    visits = [
        {
            "name": draw(_bounded_name(1, 50)),
            "visit_number": draw(st.integers(min_value=1, max_value=9999)),
            "visit_type": draw(_visit_types),
        }
        for _ in range(visit_count)
    ]

    codelist_count = draw(st.integers(min_value=0, max_value=3))
    codelists = [
        {
            "name": draw(_bounded_name(1, 50)),
            "code": draw(_bounded_name(1, 10)),
            "items": [
                {
                    "code": draw(_bounded_name(1, 10)),
                    "label": draw(_bounded_name(1, 50)),
                }
                for _ in range(draw(st.integers(min_value=0, max_value=3)))
            ],
        }
        for _ in range(codelist_count)
    ]

    edit_check_count = draw(st.integers(min_value=0, max_value=3))
    edit_checks = [
        {
            "name": draw(_bounded_name(1, 50)),
            "severity": draw(
                st.sampled_from(["info", "warning", "error", "query"])
            ),
        }
        for _ in range(edit_check_count)
    ]

    phase_count = draw(st.integers(min_value=0, max_value=3))
    # Phase names are unique within a design version (DB unique constraint), so
    # prefix each with its index to keep generated designs valid.
    phases = [
        {
            "name": f"{index + 1}-{draw(_bounded_name(1, 50))}",
            "display_order": index + 1,
        }
        for index in range(phase_count)
    ]

    return {
        "forms": forms,
        "visits": visits,
        "codelists": codelists,
        "edit_checks": edit_checks,
        "phases": phases,
    }


# ---------------------------------------------------------------------------
# In-memory async session helpers
# ---------------------------------------------------------------------------


def _new_engine():
    """A fresh in-memory async engine (one per example keeps examples isolated)."""
    return create_async_engine("sqlite+aiosqlite:///:memory:")


async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _build_design(
    session: AsyncSession, shape: dict[str, object], *, status: StudyVersionStatus
) -> uuid.UUID:
    """Persist a Study + Design_Version in ``status`` populated from ``shape``.

    Returns the ``design_version_id`` the consumption contract will be read with.
    """
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Consumption Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=status,
    )
    session.add(version)
    await session.flush()
    version_id = version.id

    for order, form_spec in enumerate(shape["forms"], start=1):  # type: ignore[arg-type]
        form = FormDefinition(
            study_version_id=version_id,
            name=str(form_spec["name"]),
            form_code=str(form_spec["form_code"]),
            display_order=order,
            is_repeating=bool(form_spec["is_repeating"]),
        )
        session.add(form)
        await session.flush()
        for section_order, section_spec in enumerate(
            form_spec["sections"], start=1  # type: ignore[arg-type]
        ):
            section = FormSection(
                form_definition_id=form.id,
                name=str(section_spec["name"]),
                display_order=section_order,
            )
            session.add(section)
            await session.flush()
            for field_order, field_spec in enumerate(
                section_spec["fields"], start=1  # type: ignore[arg-type]
            ):
                session.add(
                    FieldDefinition(
                        form_section_id=section.id,
                        label=str(field_spec["label"]),
                        variable_name=str(field_spec["variable_name"]),
                        control_type=str(field_spec["control_type"]),
                        data_type=str(field_spec["data_type"]),
                        is_required=False,
                        display_order=field_order,
                    )
                )

    for order, visit_spec in enumerate(shape["visits"], start=1):  # type: ignore[arg-type]
        session.add(
            VisitDefinition(
                study_version_id=version_id,
                name=str(visit_spec["name"]),
                visit_number=int(visit_spec["visit_number"]),  # type: ignore[call-overload]
                visit_type=str(visit_spec["visit_type"]),
                display_order=order,
                is_required=True,
            )
        )

    for codelist_spec in shape["codelists"]:  # type: ignore[attr-defined]
        codelist = Codelist(
            study_version_id=version_id,
            name=str(codelist_spec["name"]),
            code=str(codelist_spec["code"]),
        )
        session.add(codelist)
        await session.flush()
        for item_order, item_spec in enumerate(
            codelist_spec["items"], start=1  # type: ignore[index]
        ):
            session.add(
                CodelistItem(
                    codelist_id=codelist.id,
                    code=str(item_spec["code"]),
                    label=str(item_spec["label"]),
                    display_order=item_order,
                )
            )

    for check_spec in shape["edit_checks"]:  # type: ignore[attr-defined]
        session.add(
            EditCheck(
                study_version_id=version_id,
                name=str(check_spec["name"]),
                rule_json={"field": "age", "operator": ">", "value": 0},
                severity=str(check_spec["severity"]),
                is_active=True,
            )
        )

    for phase_spec in shape["phases"]:  # type: ignore[attr-defined]
        session.add(
            SubjectPhaseDefinition(
                design_version_id=version_id,
                name=str(phase_spec["name"]),
                display_order=int(phase_spec["display_order"]),  # type: ignore[index]
            )
        )

    await session.flush()
    return version_id


# ---------------------------------------------------------------------------
# Read-only view assertions (R2.6)
# ---------------------------------------------------------------------------


def _assert_frozen_view(value: object) -> None:
    """Assert ``value`` is a frozen Pydantic view, never a mutable ORM entity.

    Checks three things: it is a ``BaseModel`` (a view, not an ORM entity), its
    config is ``frozen``, and attribute assignment actually raises so the
    consumer has no mutation path (R2.6). Nested views and tuples of views are
    walked recursively; tuples (never lists) carry nested collections so the
    whole aggregate is immutable end to end.
    """
    assert isinstance(value, BaseModel), (
        f"consumption read returned a non-view object: {type(value)!r}"
    )
    assert value.model_config.get("frozen") is True, (
        f"view {type(value).__name__} is not frozen"
    )

    # Attribute assignment on a frozen view must raise — no mutation path.
    field_names = list(type(value).model_fields)
    assert field_names, f"view {type(value).__name__} has no fields to probe"
    probe = field_names[0]
    with pytest.raises(PydanticValidationError):  # frozen set is rejected
        setattr(value, probe, getattr(value, probe))

    # Walk nested views / tuples-of-views for the same guarantees.
    for name in field_names:
        child = getattr(value, name)
        if isinstance(child, BaseModel):
            _assert_frozen_view(child)
        elif isinstance(child, tuple):
            for element in child:
                if isinstance(element, BaseModel):
                    _assert_frozen_view(element)
        else:
            # A view must never hand back a mutable collection as content.
            assert not isinstance(child, (list, dict, set)) or name in {
                "rule_json",
                "attributes",
                "visibility_rule",
            }, f"view {type(value).__name__}.{name} exposed a mutable {type(child)}"


# ---------------------------------------------------------------------------
# Property 2: published content is readable; draft content is never leaked
# ---------------------------------------------------------------------------


@given(shape=_design_shape())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_published_only_consumption(shape: dict[str, object]) -> None:
    """Published designs read as frozen views; drafts are always rejected.

    # Feature: designer-edc-refactor, Property 2: One-directional, published-only consumption

    **Validates: Requirements 2.5, 2.6**
    """
    service = DesignConsumptionService()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async with factory() as session:
            draft_id = await _build_design(
                session, shape, status=StudyVersionStatus.draft
            )
            published_id = await _build_design(
                session, shape, status=StudyVersionStatus.published
            )
            await session.commit()

        # Each read method is exercised against both states. For the published
        # id it must return content; for the draft id it must reject (R2.5).
        collection_reads = [
            service.list_forms,
            service.list_visit_definitions,
            service.list_arm_definitions,
            service.list_edit_check_rules,
            service.list_codelists,
            service.list_subject_phase_definitions,
            service.list_crf_access_definitions,
            service.list_raw_data_variable_settings,
            service.list_coding_settings,
            service.list_form_dependencies,
            service.list_visit_dependencies,
        ]

        async with factory() as read_session:
            # --- Published: content is returned as frozen views (R2.5, R2.6) ---
            design = await service.get_published_design(read_session, published_id)
            assert isinstance(design, PublishedDesignView)
            assert design.status == str(StudyVersionStatus.published)
            _assert_frozen_view(design)

            for read in collection_reads:
                views = await read(read_session, published_id)
                assert isinstance(views, list)
                for view in views:
                    _assert_frozen_view(view)

            soa = await service.get_schedule_of_assessment(
                read_session, published_id
            )
            _assert_frozen_view(soa)

            # permits_unscheduled_visits reads only published content and agrees
            # with the shape's declared visit types.
            permitted = await service.permits_unscheduled_visits(
                read_session, published_id
            )
            expected = any(
                v["visit_type"] == "unscheduled"
                for v in shape["visits"]  # type: ignore[union-attr]
            )
            assert permitted is expected

            # --- Draft: every read is rejected; no content ever crosses (R2.5) ---
            with pytest.raises(ValidationError):
                await service.get_published_design(read_session, draft_id)
            for read in collection_reads:
                with pytest.raises(ValidationError):
                    await read(read_session, draft_id)
            with pytest.raises(ValidationError):
                await service.get_schedule_of_assessment(read_session, draft_id)
            with pytest.raises(ValidationError):
                await service.permits_unscheduled_visits(read_session, draft_id)

            # --- Missing: a never-persisted id is not-found, not leaked ---------
            missing_id = uuid.uuid4()
            with pytest.raises(NotFoundError):
                await service.get_published_design(read_session, missing_id)
            for read in collection_reads:
                with pytest.raises(NotFoundError):
                    await read(read_session, missing_id)
    finally:
        await engine.dispose()
