"""Focused tests for the Designer domain-model refactor.

Covers the new/changed Designer behaviors introduced when cycles folded into
visits and the arm/visit mapping, raw-data label/suffix, CRF blinding, and
form/visit dependency capabilities were added:

  - visit_definition_service: cycle visit + repeat/cycle metadata; reject repeat
    fields on a non-cycle visit; reject inverted repeat bounds.
  - arm_service: attach member visits; reject missing / cross-version visit ids;
    dedupe duplicates; list arms with member ids.
  - crf_access_service: blinded / unblind_role; reject unblind_role without
    blinded.
  - raw_data_variable_service: persist label/suffix; strip-empty to None.
  - form_dependency_service / visit_dependency_service: happy path, self-guard,
    duplicate guard, cross-version guard.

Each example runs against a fresh in-memory SQLite database (mirroring
``test_property_designer_round_trip.py``), so the assertions reflect what landed
in the database through the real service contracts.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.form_metadata import FormDefinition
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.models.designer.visit import VisitDefinition
from app.models.edc.study import Study, StudyStatus
from app.schemas.designer.visit import VisitDefinitionCreate
from app.services.designer.arm_service import ArmService
from app.services.designer.crf_access_service import CrfAccessService
from app.services.designer.form_dependency_service import FormDependencyService
from app.services.designer.raw_data_variable_service import RawDataVariableService
from app.services.designer.visit_definition_service import VisitDefinitionService
from app.services.designer.visit_dependency_service import VisitDependencyService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _make_version(session: AsyncSession) -> StudyVersion:
    study = Study(
        study_code=f"STUDY-{uuid.uuid4().hex[:8]}",
        title="Domain Model Study",
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
    session: AsyncSession,
    version_id: uuid.UUID,
    visit_number: int,
    *,
    visit_type: str = "scheduled",
) -> VisitDefinition:
    visit = VisitDefinition(
        study_version_id=version_id,
        name=f"Visit {visit_number}",
        visit_number=visit_number,
        visit_type=visit_type,
        display_order=visit_number,
        is_required=True,
    )
    session.add(visit)
    await session.flush()
    return visit


# ---------------------------------------------------------------------------
# visit_definition_service — cycle visit metadata
# ---------------------------------------------------------------------------


async def test_cycle_visit_persists_cycle_metadata():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            cycle = await VisitDefinitionService().define_visit(
                session,
                version=version,
                data=VisitDefinitionCreate(
                    name="Treatment Cycle",
                    visit_number=1,
                    visit_type="cycle",
                    display_order=1,
                    repeat_min=1,
                    repeat_max=6,
                    cycle_length=28,
                ),
                actor_id=uuid.uuid4(),
            )
            assert cycle.visit_type == "cycle"
            assert cycle.repeat_min == 1
            assert cycle.repeat_max == 6
            assert cycle.cycle_length == 28
    finally:
        await engine.dispose()


async def test_repeat_fields_rejected_on_non_cycle_visit():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await VisitDefinitionService().define_visit(
                    session,
                    version=version,
                    data=VisitDefinitionCreate(
                        name="Plain",
                        visit_number=1,
                        visit_type="scheduled",
                        display_order=1,
                        repeat_min=1,
                    ),
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "visit_type"
    finally:
        await engine.dispose()


async def test_inverted_repeat_bounds_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await VisitDefinitionService().define_visit(
                    session,
                    version=version,
                    data=VisitDefinitionCreate(
                        name="Cycle",
                        visit_number=1,
                        visit_type="cycle",
                        display_order=1,
                        repeat_min=5,
                        repeat_max=2,
                    ),
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "repeat_min"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# arm_service — arm/visit mapping and same-version guard
# ---------------------------------------------------------------------------


async def test_arm_attaches_member_visits_and_dedupes():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            v1 = await _make_visit(session, version.id, 1)
            v2 = await _make_visit(session, version.id, 2, visit_type="cycle")
            arm = await ArmService().create_arm_definition(
                session,
                design_version_id=version.id,
                name="Arm A",
                display_order=1,
                visit_definition_ids=[v1.id, v2.id, v1.id],  # duplicate v1
                actor_id=uuid.uuid4(),
            )
            assert {v.id for v in arm.visits} == {v1.id, v2.id}

            arms = await ArmService().list_arm_definitions(session, version.id)
            assert len(arms) == 1
            assert {v.id for v in arms[0].visits} == {v1.id, v2.id}
    finally:
        await engine.dispose()


async def test_arm_rejects_missing_visit_id():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await ArmService().create_arm_definition(
                    session,
                    design_version_id=version.id,
                    name="Arm A",
                    display_order=1,
                    visit_definition_ids=[uuid.uuid4()],
                    actor_id=uuid.uuid4(),
                )
            assert "missing_visit_definition_ids" in exc.value.details
    finally:
        await engine.dispose()


async def test_arm_rejects_cross_version_visit():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version_a = await _make_version(session)
            version_b = await _make_version(session)
            other_visit = await _make_visit(session, version_b.id, 1)
            with pytest.raises(ValidationError) as exc:
                await ArmService().create_arm_definition(
                    session,
                    design_version_id=version_a.id,
                    name="Arm A",
                    display_order=1,
                    visit_definition_ids=[other_visit.id],
                    actor_id=uuid.uuid4(),
                )
            assert str(other_visit.id) in exc.value.details["cross_version_visit_ids"]
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# crf_access_service — blinding
# ---------------------------------------------------------------------------


async def test_crf_blinded_with_unblind_role():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            access = await CrfAccessService().create_access_definition(
                session,
                design_version_id=version.id,
                role="Investigator",
                can_read=True,
                can_write=False,
                blinded=True,
                unblind_role="Unblinded Pharmacist",
                actor_id=uuid.uuid4(),
            )
            assert access.blinded is True
            assert access.unblind_role == "Unblinded Pharmacist"
    finally:
        await engine.dispose()


async def test_crf_unblind_role_without_blinded_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            with pytest.raises(ValidationError) as exc:
                await CrfAccessService().create_access_definition(
                    session,
                    design_version_id=version.id,
                    role="Investigator",
                    can_read=True,
                    can_write=False,
                    blinded=False,
                    unblind_role="Pharmacist",
                    actor_id=uuid.uuid4(),
                )
            assert exc.value.details["field"] == "unblind_role"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# raw_data_variable_service — label / suffix
# ---------------------------------------------------------------------------


async def test_raw_data_label_and_suffix_persist_and_strip():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            setting = await RawDataVariableService().create_variable_setting(
                session,
                design_version_id=version.id,
                name="AGE",
                data_type="integer",
                label="  Age in years  ",
                suffix="   ",  # whitespace-only -> None
                actor_id=uuid.uuid4(),
            )
            assert setting.label == "Age in years"
            assert setting.suffix is None
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# dependency services — happy path + guards
# ---------------------------------------------------------------------------


async def _make_form(session: AsyncSession, version_id: uuid.UUID, order: int) -> FormDefinition:
    form = FormDefinition(
        study_version_id=version_id,
        name=f"Form {order}",
        form_code=f"F{order:04d}",
        display_order=order,
    )
    session.add(form)
    await session.flush()
    return form


async def test_form_dependency_happy_path_and_guards():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            f1 = await _make_form(session, version.id, 1)
            f2 = await _make_form(session, version.id, 2)
            service = FormDependencyService()

            dep = await service.create_dependency(
                session,
                form_definition_id=f1.id,
                depends_on_form_definition_id=f2.id,
                actor_id=uuid.uuid4(),
            )
            assert dep.dependency_type == "prerequisite"

            # Self-dependency rejected.
            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=f1.id,
                )

            # Duplicate rejected.
            with pytest.raises(ConflictError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=f2.id,
                )

            # Missing form rejected.
            with pytest.raises(NotFoundError):
                await service.create_dependency(
                    session,
                    form_definition_id=f1.id,
                    depends_on_form_definition_id=uuid.uuid4(),
                )
    finally:
        await engine.dispose()


async def test_visit_dependency_cross_version_rejected():
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version_a = await _make_version(session)
            version_b = await _make_version(session)
            va = await _make_visit(session, version_a.id, 1)
            vb = await _make_visit(session, version_b.id, 1)
            service = VisitDependencyService()

            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    visit_definition_id=va.id,
                    depends_on_visit_definition_id=vb.id,
                )

            # Self-dependency rejected.
            with pytest.raises(ValidationError):
                await service.create_dependency(
                    session,
                    visit_definition_id=va.id,
                    depends_on_visit_definition_id=va.id,
                )
    finally:
        await engine.dispose()


async def test_arm_visits_cascade_delete_on_visit_removal():
    """Deleting a member visit prunes the arm_definition_visits edge (ON DELETE
    CASCADE), so the arm no longer lists it."""
    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            version = await _make_version(session)
            v1 = await _make_visit(session, version.id, 1)
            arm = await ArmService().create_arm_definition(
                session,
                design_version_id=version.id,
                name="Arm A",
                display_order=1,
                visit_definition_ids=[v1.id],
                actor_id=uuid.uuid4(),
            )
            arm_id = arm.id
            await session.commit()

        async with factory() as session:
            v1_db = await session.get(VisitDefinition, v1.id)
            await session.delete(v1_db)
            await session.commit()

        async with factory() as read:
            result = await read.execute(select(ArmDefinition).where(ArmDefinition.id == arm_id))
            arm_db = result.scalars().one()
            assert [v.id for v in arm_db.visits] == []
    finally:
        await engine.dispose()
