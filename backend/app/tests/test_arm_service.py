"""Example persistence tests for the ArmService.

Feature: designer-edc-refactor, Task 7.7

Validates Requirements:
  - 4.5: Persist an Arm_Definition within a Draft_Design and read it back.
"""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError, NotFoundError
from app.models.designer.arm_definition import ArmDefinition
from app.models.designer.schedule_of_assessment import ScheduleOfAssessment
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.services.designer.arm_service import ArmService


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
def service() -> ArmService:
    return ArmService()


async def _make_draft_version(session: AsyncSession) -> StudyVersion:
    """Create a Study and a draft Design_Version for the FK target."""
    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Arm Study",
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


class TestCreateArmDefinition:
    """ArmService.create_arm_definition()."""

    async def test_persists_and_reads_back_arm_definition(self, service, db_session):
        """A valid arm persists and its stored fields round-trip (R4.5)."""
        version = await _make_draft_version(db_session)
        actor_id = uuid4()

        arm = await service.create_arm_definition(
            db_session,
            design_version_id=version.id,
            name="Treatment Arm A",
            display_order=1,
            description="High-dose treatment group",
            actor_id=actor_id,
        )

        assert arm.id is not None
        assert arm.study_version_id == version.id
        assert arm.name == "Treatment Arm A"
        assert arm.display_order == 1
        assert arm.description == "High-dose treatment group"

        # Read the record back from the database and assert every stored field
        # round-trips correctly.
        stored = (
            await db_session.execute(
                select(ArmDefinition).where(ArmDefinition.id == arm.id)
            )
        ).scalar_one()
        assert stored.name == "Treatment Arm A"
        assert stored.display_order == 1
        assert stored.description == "High-dose treatment group"
        assert stored.study_version_id == version.id

    async def test_persists_arm_without_description(self, service, db_session):
        """Description is optional and stored as NULL when omitted (R4.5)."""
        version = await _make_draft_version(db_session)

        arm = await service.create_arm_definition(
            db_session,
            design_version_id=version.id,
            name="Placebo Arm",
            display_order=2,
        )

        stored = (
            await db_session.execute(
                select(ArmDefinition).where(ArmDefinition.id == arm.id)
            )
        ).scalar_one()
        assert stored.name == "Placebo Arm"
        assert stored.display_order == 2
        assert stored.description is None
        assert stored.study_version_id == version.id

    async def test_rejects_duplicate_name_returning_duplicate(self, service, db_session):
        """A duplicate name is rejected and the error names the duplicate (R4.5)."""
        version = await _make_draft_version(db_session)

        await service.create_arm_definition(
            db_session,
            design_version_id=version.id,
            name="Treatment Arm A",
            display_order=1,
        )

        with pytest.raises(ConflictError) as exc_info:
            await service.create_arm_definition(
                db_session,
                design_version_id=version.id,
                name="Treatment Arm A",
                display_order=2,
            )

        assert exc_info.value.details["duplicate_name"] == "Treatment Arm A"

        # Nothing extra was persisted — the conflicting arm is not stored.
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ArmDefinition)
                .where(ArmDefinition.study_version_id == version.id)
            )
        ).scalar_one()
        assert count == 1


class TestDeleteArmDefinition:
    """ArmService.delete_arm_definition()."""

    async def test_soft_deletes_arm_and_only_its_scoped_schedule(self, service, db_session):
        version = await _make_draft_version(db_session)
        arm = await service.create_arm_definition(
            db_session,
            design_version_id=version.id,
            name="Treatment Arm A",
            display_order=1,
        )
        common_schedule = ScheduleOfAssessment(
            design_version_id=version.id,
            arm_definition_id=None,
        )
        arm_schedule = ScheduleOfAssessment(
            design_version_id=version.id,
            arm_definition_id=arm.id,
        )
        db_session.add_all([common_schedule, arm_schedule])
        await db_session.flush()

        await service.delete_arm_definition(db_session, arm.id, actor_id=uuid4())

        assert arm.deleted_at is not None
        assert arm_schedule.deleted_at is not None
        assert common_schedule.deleted_at is None
        assert await service.list_arm_definitions(db_session, version.id) == []
        with pytest.raises(NotFoundError):
            await service.get_arm_definition(db_session, arm.id)

        replacement = await service.create_arm_definition(
            db_session,
            design_version_id=version.id,
            name="Treatment Arm A",
            display_order=1,
        )
        assert replacement.id != arm.id
