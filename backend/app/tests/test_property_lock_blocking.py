"""Property-based integration test for hierarchy-aware lock blocking.

# Feature: clinical-edc-system, Property 28: Modification is blocked under any frozen or locked ancestor
**Validates: Requirements 10.7, 16.1, 16.2, 16.3, 27.5**

For every node in the clinical hierarchy (field -> form -> visit -> subject ->
site -> study), and for either active control type (freeze or lock), the real
LockService must cause the real DataCaptureService to reject a field change.
The test uses a persisted SQLite hierarchy and does not replace either service's
lock integration with a mock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import BusinessRuleError
from app.models.form_data import FieldValue, FormInstance
from app.models.form_metadata import FieldDefinition, FormDefinition, FormSection
from app.models.identity import User, UserStatus
from app.models.lock import FreezeLockObjectType, FreezeLockType
from app.models.site import Site
from app.models.study import Study, StudyVersion
from app.models.subject import Subject
from app.models.visit import VisitInstance
from app.services.data_capture_service import DataCaptureService
from app.services.lock_service import LockService

ancestor_type_st = st.sampled_from(
    [
        FreezeLockObjectType.field,
        FreezeLockObjectType.form,
        FreezeLockObjectType.visit,
        FreezeLockObjectType.subject,
        FreezeLockObjectType.site,
        FreezeLockObjectType.study,
    ]
)
lock_type_st = st.sampled_from([FreezeLockType.freeze, FreezeLockType.lock])


@pytest.fixture
async def session_factory():
    """Create a complete SQLite schema for the real service integration."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _clinical_graph(session):
    """Persist one field-to-study graph and return its nodes plus the actor."""
    now = datetime.now(UTC)
    actor = User(
        id=uuid.uuid4(),
        email=f"lock-{uuid.uuid4()}@example.test",
        first_name="Lock",
        last_name="Tester",
        status=UserStatus.active,
    )
    study = Study(
        id=uuid.uuid4(),
        study_code=f"LOCK-{uuid.uuid4().hex[:12]}",
        title="Lock property study",
        created_by=actor.id,
        created_at=now,
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="001",
        name="Property Site",
        created_at=now,
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        created_at=now,
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number=f"SUBJ-{uuid.uuid4().hex[:12]}",
        created_by=actor.id,
        created_at=now,
    )
    visit = VisitInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        name="Visit 1",
        created_at=now,
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Clinical Form",
        form_code="CF",
        display_order=1,
        created_at=now,
    )
    section = FormSection(
        id=uuid.uuid4(),
        form_definition_id=form_definition.id,
        name="Section 1",
        display_order=1,
    )
    field = FieldDefinition(
        id=uuid.uuid4(),
        form_section_id=section.id,
        label="Value",
        variable_name="value",
        control_type="text",
        data_type="string",
        display_order=1,
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        visit_instance_id=visit.id,
        form_definition_id=form_definition.id,
        created_at=now,
    )

    session.add_all(
        [
            actor,
            study,
            site,
            version,
            subject,
            visit,
            form_definition,
            section,
            field,
            form_instance,
        ]
    )
    await session.flush()
    return {
        "actor": actor,
        "study": study,
        "site": site,
        "subject": subject,
        "visit": visit,
        "form": form_instance,
        "field": field,
    }


class TestAncestorLockBlockingProperty:
    """Property 28 integration checks for both control types and all levels."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(ancestor_type=ancestor_type_st, lock_type=lock_type_st)
    @pytest.mark.asyncio
    async def test_active_ancestor_freeze_or_lock_blocks_data_change(
        self,
        session_factory,
        ancestor_type: FreezeLockObjectType,
        lock_type: FreezeLockType,
    ):
        """Any active freeze/lock in field→study blocks DataCaptureService changes.

        **Validates: Requirements 10.7, 16.1, 16.2, 16.3, 27.5**
        """
        async with session_factory() as session:
            graph = await _clinical_graph(session)
            targets = {
                FreezeLockObjectType.field: graph["field"].id,
                FreezeLockObjectType.form: graph["form"].id,
                FreezeLockObjectType.visit: graph["visit"].id,
                FreezeLockObjectType.subject: graph["subject"].id,
                FreezeLockObjectType.site: graph["site"].id,
                FreezeLockObjectType.study: graph["study"].id,
            }
            lock_service = LockService()
            data_capture_service = DataCaptureService()

            if lock_type is FreezeLockType.freeze:
                await lock_service.freeze(
                    session,
                    actor_id=graph["actor"].id,
                    object_type=ancestor_type,
                    object_id=targets[ancestor_type],
                )
            else:
                await lock_service.lock(
                    session,
                    actor_id=graph["actor"].id,
                    object_type=ancestor_type,
                    object_id=targets[ancestor_type],
                )

            with pytest.raises(BusinessRuleError, match="frozen or locked"):
                await data_capture_service.change_value(
                    session,
                    graph["form"],
                    graph["field"].id,
                    "new value",
                    "Property test correction",
                    graph["actor"].id,
                )

            field_value_result = await session.execute(
                select(FieldValue).where(
                    FieldValue.form_instance_id == graph["form"].id,
                    FieldValue.field_definition_id == graph["field"].id,
                )
            )
            assert field_value_result.scalars().first() is None
