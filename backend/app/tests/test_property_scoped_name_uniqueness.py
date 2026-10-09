"""Property-based test for scoped name uniqueness within a draft design.

# Feature: designer-edc-refactor, Property 7: Name uniqueness within a draft design

Property 7 (design.md): For all draft Design_Versions and all named
Designer_Definitions requiring uniqueness (subject phase definitions,
codelists), two definitions with the same name cannot both persist; the second
is rejected, the first is unchanged, and the error identifies the duplicate
name.

This test exercises BOTH named Designer_Definitions that require in-version
uniqueness:
  - Codelists via ``CodelistService.create_codelist``
  - Subject phase definitions via ``SubjectPhaseService.create_phase_definition``

**Validates: Requirements 3.1, 3.2, 6.1, 6.2**

Requirements anchored:
  - 3.1 / 6.1: A uniquely-named definition within the Draft_Design is persisted.
  - 3.2 / 6.2: A duplicate name within the Draft_Design is rejected, nothing
    extra is persisted, and the error identifies the duplicate name. The same
    name is allowed in a different design version (uniqueness is version-scoped).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.models.designer.codelist import Codelist
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.edc.study import (
    Study,
    StudyStatus,
    StudyVersion,
    StudyVersionStatus,
)
from app.schemas.edc.form_metadata import CodelistCreate, CodelistItemCreate
from app.services.designer.codelist_service import CodelistService
from app.services.designer.subject_phase_service import SubjectPhaseService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Names constrained to the shared input space of both services: 1-100 chars,
# non-blank after trimming (both services strip and enforce a 1-char minimum).
_name_strategy = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    min_size=1,
    max_size=100,
).map(lambda s: s.strip()).filter(lambda s: 1 <= len(s) <= 100)


# ---------------------------------------------------------------------------
# Per-example persistence helpers (fresh in-memory DB per example)
# ---------------------------------------------------------------------------


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version to own the definitions."""
    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Uniqueness Study",
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


def _codelist_payload(name: str) -> CodelistCreate:
    """A minimal valid codelist payload (1 item satisfies the 1-1000 bound)."""
    return CodelistCreate(
        name=name,
        code=f"CL-{uuid4().hex[:8]}",
        items=[
            CodelistItemCreate(
                code="A",
                label="Item A",
                display_order=1,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Property 7
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(name=_name_strategy)
async def test_codelist_name_uniqueness_within_draft_design(name: str):
    """Codelists: a duplicate name is rejected; the same name is OK elsewhere.

    **Validates: Requirements 6.1, 6.2**
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            service = CodelistService()
            actor_id = uuid4()

            version_a = await _make_draft_version(session)
            version_b = await _make_draft_version(session)

            # First definition with the name persists (R6.1).
            first = await service.create_codelist(
                session, version_a, _codelist_payload(name), actor_id
            )
            assert first.id is not None
            assert first.name == name.strip()

            # A second definition with the same (case-insensitive) name in the
            # same Draft_Design is rejected and names the duplicate (R6.2).
            with pytest.raises(ConflictError) as exc_info:
                await service.create_codelist(
                    session, version_a, _codelist_payload(name), actor_id
                )
            assert exc_info.value.details["duplicate_name"] == name.strip()

            # Nothing extra persisted: exactly one codelist in version A (R6.2).
            count_a = (
                await session.execute(
                    select(func.count())
                    .select_from(Codelist)
                    .where(Codelist.study_version_id == version_a.id)
                )
            ).scalar_one()
            assert count_a == 1

            # The first definition is unchanged.
            stored_first = (
                await session.execute(
                    select(Codelist).where(Codelist.id == first.id)
                )
            ).scalar_one()
            assert stored_first.name == name.strip()

            # The same name is allowed in a different Design_Version (scoping).
            other = await service.create_codelist(
                session, version_b, _codelist_payload(name), actor_id
            )
            assert other.id != first.id
            assert other.study_version_id == version_b.id
    finally:
        await engine.dispose()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(name=_name_strategy)
async def test_subject_phase_name_uniqueness_within_draft_design(name: str):
    """Subject phases: a duplicate name is rejected; same name OK elsewhere.

    **Validates: Requirements 3.1, 3.2**
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            service = SubjectPhaseService()
            actor_id = uuid4()

            version_a = await _make_draft_version(session)
            version_b = await _make_draft_version(session)

            # First definition with the name persists (R3.1).
            first = await service.create_phase_definition(
                session,
                design_version_id=version_a.id,
                name=name,
                display_order=1,
                actor_id=actor_id,
            )
            assert first.id is not None
            assert first.name == name.strip()

            # A second definition with the same (case-insensitive) name in the
            # same Design_Version is rejected and names the duplicate (R3.2).
            with pytest.raises(ConflictError) as exc_info:
                await service.create_phase_definition(
                    session,
                    design_version_id=version_a.id,
                    name=name,
                    display_order=2,
                    actor_id=actor_id,
                )
            assert exc_info.value.details["duplicate_name"] == name.strip()

            # Nothing extra persisted: exactly one phase in version A (R3.2).
            count_a = (
                await session.execute(
                    select(func.count())
                    .select_from(SubjectPhaseDefinition)
                    .where(SubjectPhaseDefinition.design_version_id == version_a.id)
                )
            ).scalar_one()
            assert count_a == 1

            # The first definition is unchanged.
            stored_first = (
                await session.execute(
                    select(SubjectPhaseDefinition).where(
                        SubjectPhaseDefinition.id == first.id
                    )
                )
            ).scalar_one()
            assert stored_first.name == name.strip()

            # The same name is allowed in a different Design_Version (scoping).
            other = await service.create_phase_definition(
                session,
                design_version_id=version_b.id,
                name=name,
                display_order=1,
                actor_id=actor_id,
            )
            assert other.id != first.id
            assert other.design_version_id == version_b.id
    finally:
        await engine.dispose()
