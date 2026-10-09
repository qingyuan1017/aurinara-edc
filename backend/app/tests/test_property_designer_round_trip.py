"""Property-based test for Designer definition persistence round-trip.

# Feature: designer-edc-refactor, Property 9: Designer definition persistence round-trip

**Validates: Requirements 4.1, 4.2, 4.4, 4.6, 4.7, 4.8**

Property 9 (design.md): _For all_ valid Designer_Definitions (schedule of
assessment mappings, visit definitions, cycle membership, CRF access matrices,
raw-data variable settings, coding settings), persisting then reading the
definition back through the Designer_Module yields values equal to those
submitted.

This file is the **broad** Property 9 round-trip across the Designer definition
kinds. The visit-definition / window-validity slice (R4.2, R4.3) is already
covered by ``test_property_visit_window.py`` (task 4.3), so this file stays
focused on the *other* definition kinds to avoid overlap:

  - R4.1: Schedule_Of_Assessment mappings via ``ScheduleOfAssessmentService``.
  - R4.4: Cycle_Definition + member Visit_Definitions via ``CycleService``.
  - R4.6: CRF_Access_Definition matrices via ``CrfAccessService``.
  - R4.7: Raw_Data_Variable_Setting via ``RawDataVariableService``.
  - R4.8: Coding_Setting via ``CodingSettingService``.

Each example persists a valid definition through its authoring service, then
reads it back through a **fresh** async session so the assertion reflects what
actually landed in the database (a true round-trip, not just the in-memory
instance). A fresh in-memory SQLite database per example keeps examples
independent, following ``test_subject_phase_service.py`` and
``test_property_visit_window.py``.
"""

from __future__ import annotations

import uuid

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.cycle_definition import CycleDefinition
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.schedule_of_assessment import (
    ScheduleOfAssessment,
    ScheduleOfAssessmentEntry,
)
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.services.designer.coding_setting_service import CodingSettingService
from app.services.designer.crf_access_service import CrfAccessService
from app.services.designer.cycle_service import CycleService
from app.services.designer.raw_data_variable_service import RawDataVariableService
from app.services.designer.schedule_of_assessment_service import (
    ScheduleEntryInput,
    ScheduleOfAssessmentService,
)

# ---------------------------------------------------------------------------
# Shared field strategies (constrained to each service's accepted input space)
# ---------------------------------------------------------------------------

# Printable text with no leading/trailing whitespace so a service that strips
# the value still round-trips to the exact submitted string. Boundary lengths
# are emphasised where the service enforces them.
_text_alphabet = st.characters(categories=("L", "N", "P"))


def _bounded_name(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    """Non-whitespace-padded names within an inclusive length window."""
    return st.text(
        alphabet=_text_alphabet, min_size=min_size, max_size=max_size
    ).filter(lambda value: value == value.strip() and len(value) >= min_size)


_display_orders = st.integers(min_value=1, max_value=999)
_booleans = st.booleans()


# ---------------------------------------------------------------------------
# In-memory async session helpers
# ---------------------------------------------------------------------------


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version to own the definitions."""
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Designer Round-Trip Study",
        status=StudyStatus.draft,
        created_by=uuid.uuid4(),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    session.add(version)
    await session.flush()
    return version


async def _make_visit(
    session: AsyncSession, version_id: uuid.UUID, visit_number: int
) -> VisitDefinition:
    """Create a minimal Visit_Definition to serve as cycle/SoA membership."""
    visit = VisitDefinition(
        study_version_id=version_id,
        name=f"Visit {visit_number}",
        visit_number=visit_number,
        visit_type="scheduled",
        display_order=visit_number,
        is_required=True,
    )
    session.add(visit)
    await session.flush()
    return visit


def _new_engine():
    """A fresh in-memory async engine (one per example keeps examples isolated)."""
    return create_async_engine("sqlite+aiosqlite:///:memory:")


async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# R4.4 — Cycle_Definition + member Visit_Definitions round-trip
# ---------------------------------------------------------------------------


@given(
    name=_bounded_name(1, 100),
    display_order=_display_orders,
    visit_count=st.integers(min_value=0, max_value=4),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_cycle_definition_round_trip(
    name: str, display_order: int, visit_count: int
) -> None:
    """A Cycle_Definition and its member visits round-trip unchanged (R4.4)."""
    service = CycleService()
    actor_id = uuid.uuid4()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id
            visit_ids = [
                (await _make_visit(session, version_id, i + 1)).id
                for i in range(visit_count)
            ]

            cycle = await service.create_cycle_definition(
                session,
                design_version_id=version_id,
                name=name,
                display_order=display_order,
                visit_definition_ids=visit_ids,
                actor_id=actor_id,
            )
            cycle_id = cycle.id
            await session.commit()

        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(CycleDefinition).where(CycleDefinition.id == cycle_id)
                )
            ).scalar_one()
            assert stored.study_version_id == version_id
            assert stored.name == name
            assert stored.display_order == display_order
            assert {visit.id for visit in stored.visits} == set(visit_ids)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# R4.6 — CRF_Access_Definition round-trip
# ---------------------------------------------------------------------------


@given(
    role=_bounded_name(1, 100),
    can_read=_booleans,
    can_write=_booleans,
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_crf_access_definition_round_trip(
    role: str, can_read: bool, can_write: bool
) -> None:
    """A CRF_Access_Definition's role and read/write flags round-trip (R4.6)."""
    service = CrfAccessService()
    actor_id = uuid.uuid4()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id

            access = await service.create_access_definition(
                session,
                design_version_id=version_id,
                role=role,
                can_read=can_read,
                can_write=can_write,
                actor_id=actor_id,
            )
            access_id = access.id
            await session.commit()

        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(CrfAccessDefinition).where(
                        CrfAccessDefinition.id == access_id
                    )
                )
            ).scalar_one()
            assert stored.design_version_id == version_id
            assert stored.role == role
            assert stored.can_read == can_read
            assert stored.can_write == can_write
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# R4.7 — Raw_Data_Variable_Setting round-trip
# ---------------------------------------------------------------------------

# JSON-serialisable attribute values the SQLite JSON column stores verbatim.
_attribute_values = st.one_of(
    st.text(alphabet=_text_alphabet, max_size=20),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.booleans(),
)
_attributes = st.dictionaries(
    keys=st.text(alphabet=_text_alphabet, min_size=1, max_size=20),
    values=_attribute_values,
    max_size=5,
)


@given(
    name=_bounded_name(1, 255),
    data_type=_bounded_name(1, 50),
    attributes=_attributes,
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_raw_data_variable_setting_round_trip(
    name: str, data_type: str, attributes: dict[str, object]
) -> None:
    """A Raw_Data_Variable_Setting's name/type/attributes round-trip (R4.7)."""
    service = RawDataVariableService()
    actor_id = uuid.uuid4()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id

            setting = await service.create_variable_setting(
                session,
                design_version_id=version_id,
                name=name,
                data_type=data_type,
                attributes=attributes,
                actor_id=actor_id,
            )
            setting_id = setting.id
            await session.commit()

        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(RawDataVariableSetting).where(
                        RawDataVariableSetting.id == setting_id
                    )
                )
            ).scalar_one()
            assert stored.design_version_id == version_id
            assert stored.name == name
            assert stored.data_type == data_type
            assert stored.attributes == attributes
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# R4.8 — Coding_Setting round-trip
# ---------------------------------------------------------------------------


@given(
    dictionary_reference=_bounded_name(1, 255),
    coding_rule=st.one_of(st.none(), st.text(alphabet=_text_alphabet, max_size=200)),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_coding_setting_round_trip(
    dictionary_reference: str, coding_rule: str | None
) -> None:
    """A Coding_Setting's dictionary reference and rule round-trip (R4.8)."""
    service = CodingSettingService()
    actor_id = uuid.uuid4()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id

            setting = await service.create_coding_setting(
                session,
                design_version_id=version_id,
                dictionary_reference=dictionary_reference,
                coding_rule=coding_rule,
                actor_id=actor_id,
            )
            setting_id = setting.id
            await session.commit()

        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(CodingSetting).where(CodingSetting.id == setting_id)
                )
            ).scalar_one()
            assert stored.design_version_id == version_id
            assert stored.dictionary_reference == dictionary_reference
            assert stored.coding_rule == coding_rule
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# R4.1 — Schedule_Of_Assessment mappings round-trip
# ---------------------------------------------------------------------------


@st.composite
def _schedule_entries(draw: st.DrawFn) -> list[dict[str, object]]:
    """A list of valid SoA entry descriptors (what/when identity satisfied).

    Each entry maps a named procedure (the what) to a visit and/or a cycle (the
    when). Visit/cycle presence is referenced by index into membership created
    in the test body so the nullable FKs resolve against real rows.
    """
    count = draw(st.integers(min_value=1, max_value=4))
    entries: list[dict[str, object]] = []
    for index in range(count):
        procedure_name = draw(_bounded_name(1, 255))
        # Always include a visit (the when); optionally also a cycle.
        include_cycle = draw(st.booleans())
        entries.append(
            {
                "procedure_name": procedure_name,
                "include_cycle": include_cycle,
                "display_order": index + 1,
            }
        )
    return entries


@given(entry_specs=_schedule_entries())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_schedule_of_assessment_round_trip(
    entry_specs: list[dict[str, object]],
) -> None:
    """A Schedule_Of_Assessment and its entries round-trip unchanged (R4.1)."""
    service = ScheduleOfAssessmentService()
    actor_id = uuid.uuid4()

    engine = _new_engine()
    try:
        await _create_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version = await _make_draft_version(session)
            version_id = version.id

            # Create one visit and one cycle for the entries to reference so the
            # nullable visit/cycle FKs resolve against real rows.
            visit = await _make_visit(session, version_id, 1)
            cycle = CycleDefinition(
                study_version_id=version_id, name="Cycle 1", display_order=1
            )
            session.add(cycle)
            await session.flush()

            inputs = [
                ScheduleEntryInput(
                    procedure_name=str(spec["procedure_name"]),
                    visit_definition_id=visit.id,
                    cycle_definition_id=(
                        cycle.id if spec["include_cycle"] else None
                    ),
                    display_order=int(spec["display_order"]),
                )
                for spec in entry_specs
            ]

            soa = await service.create_schedule_of_assessment(
                session,
                design_version_id=version_id,
                entries=inputs,
                actor_id=actor_id,
            )
            soa_id = soa.id
            await session.commit()

        # Expected (procedure_name, visit_id, cycle_id, display_order) tuples.
        expected = {
            (
                str(spec["procedure_name"]),
                visit.id,
                cycle.id if spec["include_cycle"] else None,
                int(spec["display_order"]),
            )
            for spec in entry_specs
        }

        async with factory() as read_session:
            stored = (
                await read_session.execute(
                    select(ScheduleOfAssessment).where(
                        ScheduleOfAssessment.id == soa_id
                    )
                )
            ).scalar_one()
            assert stored.design_version_id == version_id

            stored_entries = (
                await read_session.execute(
                    select(ScheduleOfAssessmentEntry).where(
                        ScheduleOfAssessmentEntry.schedule_of_assessment_id == soa_id
                    )
                )
            ).scalars().all()

            actual = {
                (
                    entry.procedure_name,
                    entry.visit_definition_id,
                    entry.cycle_definition_id,
                    entry.display_order,
                )
                for entry in stored_entries
            }
            assert actual == expected
            # Every entry carries a form XOR procedure identity (R4.1 — procedure).
            for entry in stored_entries:
                assert entry.form_definition_id is None
                assert entry.procedure_name is not None
    finally:
        await engine.dispose()
