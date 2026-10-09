"""Unit + persistence tests for the SubjectPhaseService.

Feature: designer-edc-refactor, Task 7.1

Validates Requirements:
  - 3.1: Persist a Subject_Phase_Definition with a 1-100 char name and a
         1-999 display order inside a design version.
  - 3.2: Reject a duplicate name within the design version, persist nothing, and
         return an error identifying the duplicate name.
  - 3.3: Each Subject_Phase_Definition binds to exactly one Design_Version.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, ValidationError
from app.models.designer.subject_phase_definition import SubjectPhaseDefinition
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.services.designer.subject_phase_service import SubjectPhaseService


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def service() -> SubjectPhaseService:
    return SubjectPhaseService()


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version for the FK target."""
    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Phase Study",
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


class TestCreatePhaseDefinition:
    """SubjectPhaseService.create_phase_definition()."""

    async def test_persists_phase_definition(self, service, db_session):
        """A valid phase is persisted bound to its design version (R3.1, R3.3)."""
        version = await _make_draft_version(db_session)
        actor_id = uuid4()

        phase = await service.create_phase_definition(
            db_session,
            design_version_id=version.id,
            name="Screening",
            display_order=1,
            actor_id=actor_id,
        )

        assert phase.id is not None
        assert phase.design_version_id == version.id
        assert phase.name == "Screening"
        assert phase.display_order == 1

        stored = (
            await db_session.execute(
                select(SubjectPhaseDefinition).where(
                    SubjectPhaseDefinition.id == phase.id
                )
            )
        ).scalar_one()
        assert stored.name == "Screening"

    async def test_rejects_duplicate_name_returning_duplicate(self, service, db_session):
        """A duplicate name is rejected and the error names the duplicate (R3.2)."""
        version = await _make_draft_version(db_session)

        await service.create_phase_definition(
            db_session,
            design_version_id=version.id,
            name="Treatment",
            display_order=1,
        )

        with pytest.raises(ConflictError) as exc_info:
            await service.create_phase_definition(
                db_session,
                design_version_id=version.id,
                name="Treatment",
                display_order=2,
            )

        assert exc_info.value.details["duplicate_name"] == "Treatment"

        # Nothing extra was persisted (R3.2 — persist nothing on conflict).
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(SubjectPhaseDefinition)
                .where(SubjectPhaseDefinition.design_version_id == version.id)
            )
        ).scalar_one()
        assert count == 1

    async def test_duplicate_check_is_case_insensitive(self, service, db_session):
        """Names differing only in case collide within one design version."""
        version = await _make_draft_version(db_session)

        await service.create_phase_definition(
            db_session,
            design_version_id=version.id,
            name="Follow-up",
            display_order=1,
        )

        with pytest.raises(ConflictError):
            await service.create_phase_definition(
                db_session,
                design_version_id=version.id,
                name="follow-up",
                display_order=2,
            )

    async def test_same_name_allowed_in_different_versions(self, service, db_session):
        """Uniqueness is scoped to a single design version (R3.3)."""
        version_a = await _make_draft_version(db_session)
        version_b = await _make_draft_version(db_session)

        phase_a = await service.create_phase_definition(
            db_session,
            design_version_id=version_a.id,
            name="Screening",
            display_order=1,
        )
        phase_b = await service.create_phase_definition(
            db_session,
            design_version_id=version_b.id,
            name="Screening",
            display_order=1,
        )

        assert phase_a.design_version_id == version_a.id
        assert phase_b.design_version_id == version_b.id

    @pytest.mark.parametrize("name", ["", "x" * 101])
    async def test_rejects_out_of_range_name(self, service, db_session, name):
        """Names shorter than 1 or longer than 100 chars are rejected (R3.1)."""
        version = await _make_draft_version(db_session)

        with pytest.raises(ValidationError):
            await service.create_phase_definition(
                db_session,
                design_version_id=version.id,
                name=name,
                display_order=1,
            )

    @pytest.mark.parametrize("display_order", [0, 1000])
    async def test_rejects_out_of_range_display_order(
        self, service, db_session, display_order
    ):
        """Display order outside 1-999 is rejected (R3.1)."""
        version = await _make_draft_version(db_session)

        with pytest.raises(ValidationError):
            await service.create_phase_definition(
                db_session,
                design_version_id=version.id,
                name="Phase",
                display_order=display_order,
            )

    @pytest.mark.parametrize("display_order", [1, 999])
    async def test_accepts_display_order_bounds(
        self, service, db_session, display_order
    ):
        """Display order at the 1 and 999 bounds is accepted (R3.1)."""
        version = await _make_draft_version(db_session)

        phase = await service.create_phase_definition(
            db_session,
            design_version_id=version.id,
            name=f"Phase-{display_order}",
            display_order=display_order,
        )
        assert phase.display_order == display_order
