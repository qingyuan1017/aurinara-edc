"""Property-based coverage for repeating-record lifecycle guarantees.

# Feature: clinical-edc-system, Property 21: Repeating-record sequence is monotonic and soft-delete round-trips
**Validates: Requirements 11.1, 11.3, 11.4**

The test uses real ``RepeatingRecordService`` calls against an in-memory SQLite
persistence layer. Each generated scenario adds several rows, soft-deletes one
of them, and restores it while checking sequence allocation, retention, and
clearance of deletion metadata.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.request_context import request_id_var
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.form_record import FormRecord
from app.models.identity import User, UserStatus
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.services.repeating_record_service import RepeatingRecordService

# Strategies

record_value_strategy = st.dictionaries(
    keys=st.sampled_from(["term", "dose", "ongoing"]),
    values=st.one_of(
        st.text(max_size=40),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
        st.none(),
    ),
    min_size=1,
    max_size=3,
)


@st.composite
def repeating_record_scenario(draw: st.DrawFn) -> tuple[list[dict], int]:
    """Generate rows and a valid row index to delete and restore."""
    values = draw(st.lists(record_value_strategy, min_size=1, max_size=8))
    deleted_index = draw(st.integers(min_value=0, max_value=len(values) - 1))
    return values, deleted_index


async def _create_engine_and_session():
    """Create the minimum SQLite schema needed by the record service."""
    import app.models  # noqa: F401  # Register all ORM relationships first.

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tables = [
        model.__table__
        for model in (
            User,
            Study,
            StudyVersion,
            Site,
            Subject,
            FormDefinition,
            FormInstance,
            FormRecord,
            AuditEvent,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: Base.metadata.create_all(
            sync_connection, tables=tables
        ))

    return engine, async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_repeating_form(session: AsyncSession) -> tuple[User, FormInstance]:
    """Create a real subject/form hierarchy for a repeating form instance."""
    actor = User(
        id=uuid.uuid4(),
        email=f"records-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("pw"),
        first_name="Record",
        last_name="Tester",
        status=UserStatus.active,
    )
    study = Study(
        id=uuid.uuid4(),
        study_code=f"REPEAT-{uuid.uuid4().hex[:8]}",
        title="Repeating Record Property Study",
        status=StudyStatus.active,
        created_by=actor.id,
        created_at=datetime.now(UTC),
    )
    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=actor.id,
        created_at=datetime.now(UTC),
    )
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number="001",
        name="Property Test Site",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    subject = Subject(
        id=uuid.uuid4(),
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="001-0001",
        status=SubjectStatus.screening,
        created_by=actor.id,
        created_at=datetime.now(UTC),
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version.id,
        name="Adverse Events",
        form_code="AE",
        display_order=1,
        is_repeating=True,
        created_at=datetime.now(UTC),
    )
    form_instance = FormInstance(
        id=uuid.uuid4(),
        subject_id=subject.id,
        form_definition_id=form_definition.id,
        status=FormInstanceStatus.in_progress,
        created_at=datetime.now(UTC),
        # Keep the audit scope available without an async lazy-load in the service.
        subject=subject,
        form_definition=form_definition,
    )
    session.add_all([actor, study, version, site, subject, form_definition, form_instance])
    await session.flush()
    return actor, form_instance


class TestRepeatingRecordProperty:
    """Property 21: monotonic sequences and soft-delete round trips."""

    @settings(max_examples=100, deadline=None)
    @given(scenario=repeating_record_scenario())
    @pytest.mark.asyncio
    async def test_sequence_allocation_and_soft_delete_restore_round_trip(
        self, scenario: tuple[list[dict], int]
    ):
        """Added rows increase strictly, and delete/restore preserves row state."""
        values, deleted_index = scenario
        request_context = request_id_var.set(str(uuid.uuid4()))
        engine = None
        try:
            engine, session_factory = await _create_engine_and_session()
            async with session_factory() as session:
                actor, form_instance = await _seed_repeating_form(session)
                service = RepeatingRecordService()
                records: list[FormRecord] = []

                for row_values in values:
                    record = await service.add_record(
                        session, form_instance, row_values, actor.id
                    )
                    # The service returns a new record before its relationship is
                    # populated; attach it for scoped delete/restore audit events.
                    record.form_instance = form_instance
                    records.append(record)

                sequence_numbers = [record.sequence_number for record in records]
                assert sequence_numbers == list(range(1, len(values) + 1))
                assert all(
                    left < right
                    for left, right in itertools.pairwise(sequence_numbers)
                )

                target = records[deleted_index]
                original_values = dict(target.data_jsonb or {})
                original_sequence = target.sequence_number
                reason = "Entered in error"

                await service.soft_delete(session, target, reason, actor.id)
                assert target.data_jsonb == original_values
                assert target.sequence_number == original_sequence
                assert target.deleted_at is not None
                assert target.deleted_by == actor.id
                assert target.deletion_reason == reason

                await service.restore(session, target, actor.id)
                assert target.data_jsonb == original_values
                assert target.sequence_number == original_sequence
                assert target.deleted_at is None
                assert target.deleted_by is None
                assert target.deletion_reason is None

                await session.commit()

            async with session_factory() as verification_session:
                persisted = (
                    await verification_session.execute(
                        select(
                            FormRecord.data_jsonb,
                            FormRecord.sequence_number,
                            FormRecord.deleted_at,
                            FormRecord.deleted_by,
                            FormRecord.deletion_reason,
                        ).where(FormRecord.id == records[deleted_index].id)
                    )
                ).one()
                assert persisted.data_jsonb == original_values
                assert persisted.sequence_number == original_sequence
                assert persisted.deleted_at is None
                assert persisted.deleted_by is None
                assert persisted.deletion_reason is None

                audit_actions = (
                    await verification_session.execute(
                        select(AuditEvent.action)
                        .where(AuditEvent.entity_id == records[deleted_index].id)
                        .order_by(AuditEvent.timestamp, AuditEvent.action)
                    )
                ).scalars().all()
                assert audit_actions == ["create", "delete", "restore"]
        finally:
            if engine is not None:
                await engine.dispose()
            request_id_var.reset(request_context)
