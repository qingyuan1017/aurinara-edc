"""Property-based test for Designer-child single-version binding.

# Feature: designer-edc-refactor, Property 8: Designer child binds to exactly one design version

Property 8 (design.md): For all Designer child definitions (subject phase
definitions, edit-check rules, codelists, visit definitions (including
``visit_type='cycle'``), arms, CRF access, raw-data variable settings, coding
settings), each is associated with exactly one Design_Version.

This test asserts the binding invariant uniformly across *every* Designer child
model: once persisted, each child references exactly one Design_Version through
its binding foreign key (``design_version_id`` or ``study_version_id``), the FK
is non-null, and it points at the version the child was created under. Children
created under different versions stay independently bound, and the binding is
stable across a round-trip read.

The three primary children named by the task (subject phase definition →
``design_version_id`` R3.3, edit check → ``study_version_id`` R5.4, codelist →
``study_version_id`` R6.4) are exercised through their owning Designer services;
the remaining children (form, visit, cycle-as-visit, arm, SoA, CRF access,
raw-data variable, coding setting) are exercised through direct ORM persistence
so the single-version-binding invariant is checked for the full set of Designer
children enumerated by the property.

**Validates: Requirements 3.3, 5.4, 6.4**
"""

from __future__ import annotations

from uuid import uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.codelist import Codelist
from app.models.designer.coding_setting import CodingSetting
from app.models.designer.crf_access_definition import CrfAccessDefinition
from app.models.designer.edit_check import EditCheck
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.raw_data_variable_setting import RawDataVariableSetting
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import (
    Study,
    StudyStatus,
    StudyVersion,
    StudyVersionStatus,
)
from app.schemas.edc.form_metadata import CodelistCreate, CodelistItemCreate
from app.services.designer.codelist_service import CodelistService
from app.services.designer.edit_check_service import EditCheckService
from app.services.designer.subject_phase_service import SubjectPhaseService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A short, non-blank identifier usable as a name / code across every child.
_name_strategy = (
    st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        min_size=1,
        max_size=80,
    )
    .map(lambda s: s.strip())
    .filter(lambda s: 1 <= len(s) <= 80)
)

_order_strategy = st.integers(min_value=1, max_value=999)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version to own the children."""
    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Binding Study",
        status=StudyStatus.draft,
        created_by=uuid4(),
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


def _binding_fk_name(instance: object) -> str:
    """Return the single Design_Version binding FK column on a Designer child.

    Every Designer child binds through exactly one of these columns; exactly one
    of the two is expected to exist, which is itself part of the invariant.
    """
    columns = {col.key for col in inspect(type(instance)).columns}
    present = [name for name in ("design_version_id", "study_version_id") if name in columns]
    assert len(present) == 1, (
        f"{type(instance).__name__} must expose exactly one Design_Version "
        f"binding FK, found: {present}"
    )
    return present[0]


def _binding_value(instance: object):
    return getattr(instance, _binding_fk_name(instance))


async def _assert_bound_to(
    session: AsyncSession,
    model: type,
    instance_id,
    expected_version_id,
) -> None:
    """Re-read a persisted child and assert a stable, non-null, single binding."""
    stored = (
        await session.execute(select(model).where(model.id == instance_id))
    ).scalar_one()
    fk_value = _binding_value(stored)
    assert fk_value is not None
    assert fk_value == expected_version_id


# ---------------------------------------------------------------------------
# Property 8 — services-backed children (the task's three primary children)
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(name=_name_strategy, order=_order_strategy)
async def test_service_children_bind_to_exactly_one_version(name: str, order: int):
    """Phase (R3.3), edit check (R5.4) and codelist (R6.4) each bind to one version.

    Each child is created under one of two independent draft versions and, once
    persisted, references exactly that version through its single binding FK.

    **Validates: Requirements 3.3, 5.4, 6.4**
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            actor_id = uuid4()
            version_a = await _make_draft_version(session)
            version_b = await _make_draft_version(session)

            # --- Subject phase definition → design_version_id (R3.3) ---
            phase_service = SubjectPhaseService()
            phase_a = await phase_service.create_phase_definition(
                session,
                design_version_id=version_a.id,
                name=name,
                display_order=order,
                actor_id=actor_id,
            )
            phase_b = await phase_service.create_phase_definition(
                session,
                design_version_id=version_b.id,
                name=name,
                display_order=order,
                actor_id=actor_id,
            )
            assert phase_a.design_version_id == version_a.id
            assert phase_b.design_version_id == version_b.id
            assert phase_a.id != phase_b.id
            await _assert_bound_to(
                session, SubjectPhaseDefinition, phase_a.id, version_a.id
            )
            await _assert_bound_to(
                session, SubjectPhaseDefinition, phase_b.id, version_b.id
            )

            # --- Codelist → study_version_id (R6.4) ---
            codelist_service = CodelistService()
            payload = CodelistCreate(
                name=name,
                code=f"CL-{uuid4().hex[:8]}",
                items=[CodelistItemCreate(code="A", label="Item A", display_order=1)],
            )
            codelist_a = await codelist_service.create_codelist(
                session, version_a, payload, actor_id
            )
            codelist_b = await codelist_service.create_codelist(
                session,
                version_b,
                CodelistCreate(
                    name=name,
                    code=f"CL-{uuid4().hex[:8]}",
                    items=[
                        CodelistItemCreate(code="A", label="Item A", display_order=1)
                    ],
                ),
                actor_id,
            )
            assert codelist_a.study_version_id == version_a.id
            assert codelist_b.study_version_id == version_b.id
            assert codelist_a.id != codelist_b.id
            await _assert_bound_to(session, Codelist, codelist_a.id, version_a.id)
            await _assert_bound_to(session, Codelist, codelist_b.id, version_b.id)

            # --- Edit check → study_version_id (R5.4) ---
            edit_check_service = EditCheckService()
            rule = {"field": "AGE", "operator": ">", "value": 0}
            check_a = await edit_check_service.create_edit_check(
                session,
                version_a,
                {
                    "name": name,
                    "rule_json": rule,
                    "severity": "error",
                },
                actor_id,
            )
            check_b = await edit_check_service.create_edit_check(
                session,
                version_b,
                {
                    "name": name,
                    "rule_json": rule,
                    "severity": "error",
                },
                actor_id,
            )
            assert check_a.study_version_id == version_a.id
            assert check_b.study_version_id == version_b.id
            assert check_a.id != check_b.id
            await _assert_bound_to(session, EditCheck, check_a.id, version_a.id)
            await _assert_bound_to(session, EditCheck, check_b.id, version_b.id)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 8 — the full set of Designer children, persisted via the ORM
# ---------------------------------------------------------------------------


def _build_children(version_id, name: str, order: int) -> list:
    """Construct one unpersisted instance of every Designer child type.

    This enumerates the complete Property-8 child set — subject phase, edit
    check, codelist, form, visit, cycle, arm, SoA, CRF access, raw-data
    variable, coding setting — each bound to ``version_id`` through its single
    binding FK.
    """
    return [
        SubjectPhaseDefinition(
            design_version_id=version_id, name=name, display_order=order
        ),
        EditCheck(
            study_version_id=version_id,
            name=name,
            rule_json={"field": "AGE", "operator": ">", "value": 0},
            severity="error",
        ),
        Codelist(study_version_id=version_id, name=name, code=f"CL-{uuid4().hex[:6]}"),
        FormDefinition(
            study_version_id=version_id,
            name=name,
            form_code=f"F{order:04d}",
            display_order=order,
        ),
        VisitDefinition(
            study_version_id=version_id,
            name=name,
            visit_number=order,
            visit_type="scheduled",
            display_order=order,
        ),
        VisitDefinition(
            study_version_id=version_id,
            name=f"{name}-cycle",
            visit_number=order + 10000,
            visit_type="cycle",
            display_order=order,
        ),
        ArmDefinition(
            study_version_id=version_id, name=name, display_order=order
        ),
        ScheduleOfAssessment(design_version_id=version_id),
        CrfAccessDefinition(
            design_version_id=version_id, role=name, can_read=True, can_write=False
        ),
        RawDataVariableSetting(
            design_version_id=version_id, name=name, data_type="text", attributes={}
        ),
        CodingSetting(
            design_version_id=version_id, dictionary_reference=name
        ),
    ]


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(name=_name_strategy, order=_order_strategy)
async def test_every_designer_child_binds_to_exactly_one_version(
    name: str, order: int
):
    """Every Designer child, once persisted, references exactly one version.

    For each child type the binding FK is non-null, points at the version it was
    created under, and children created under a second independent version stay
    bound to that second version — never to the first.

    **Validates: Requirements 3.3, 5.4, 6.4**
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            version_a = await _make_draft_version(session)
            version_b = await _make_draft_version(session)

            children_a = _build_children(version_a.id, name, order)
            children_b = _build_children(version_b.id, name, order)
            session.add_all(children_a + children_b)
            await session.flush()

            for child_a, child_b in zip(children_a, children_b, strict=True):
                model = type(child_a)

                # The binding FK is non-null and points at the owning version.
                assert _binding_value(child_a) == version_a.id
                assert _binding_value(child_b) == version_b.id

                # Independent binding: the two instances are distinct and each
                # references only its own version.
                assert child_a.id != child_b.id
                assert _binding_value(child_a) != _binding_value(child_b)

                # The binding is stable across a round-trip read (exactly one,
                # non-null, unchanged).
                await _assert_bound_to(session, model, child_a.id, version_a.id)
                await _assert_bound_to(session, model, child_b.id, version_b.id)
    finally:
        await engine.dispose()
