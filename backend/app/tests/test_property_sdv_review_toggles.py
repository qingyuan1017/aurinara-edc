"""Property-based coverage for SDV and clinical-review status tracking.

# Feature: clinical-edc-system, Property 27: SDV and review toggles round-trip and counts are accurate
**Validates: Requirements 14.1, 14.2, 14.3, 15.1, 15.2, 15.3**

Each generated collection creates real ORM targets, exercises both services'
set/clear operations, and verifies the scoped progress queries against the
requested final status tally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_metadata import FormDefinition
from app.models.identity import User, UserStatus
from app.models.sdv import SDVScopeType
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.services.review_service import ReviewService
from app.services.sdv_service import SDVService


@pytest.fixture
async def db_session():
    """Provide an isolated SQLite session for the generated clinical targets."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(final_statuses=st.lists(st.booleans(), min_size=1, max_size=8))
@pytest.mark.asyncio
async def test_sdv_and_review_toggle_round_trips_and_progress_counts(
    db_session: AsyncSession,
    final_statuses: list[bool],
):
    """SDV/review set-clear cycles preserve metadata and report exact tallies."""
    actor_id = uuid.uuid4()
    now = datetime.now(UTC)
    study_id = uuid.uuid4()
    site_id = uuid.uuid4()
    version_id = uuid.uuid4()

    actor = User(
        id=actor_id,
        email=f"actor-{actor_id}@example.test",
        first_name="Property",
        last_name="Actor",
        status=UserStatus.active,
        mfa_enabled=False,
        created_at=now,
    )
    study = Study(
        id=study_id,
        study_code=f"PROP-{study_id}",
        title="Property Study",
        status=StudyStatus.active,
        created_by=actor_id,
        created_at=now,
    )
    version = StudyVersion(
        id=version_id,
        study_id=study_id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=now,
        published_by=actor_id,
        created_at=now,
    )
    site = Site(
        id=site_id,
        study_id=study_id,
        site_number="101",
        name="Property Site",
        status=SiteStatus.active,
        created_at=now,
    )
    form_definition = FormDefinition(
        id=uuid.uuid4(),
        study_version_id=version_id,
        name="Property Form",
        form_code="PROP",
        display_order=1,
        is_repeating=False,
        created_at=now,
    )
    subjects = [
        Subject(
            id=uuid.uuid4(),
            study_id=study_id,
            site_id=site_id,
            study_version_id=version_id,
            subject_number=f"101-{index:04d}",
            status=SubjectStatus.enrolled,
            created_by=actor_id,
            created_at=now,
        )
        for index in range(len(final_statuses))
    ]
    forms = [
        FormInstance(
            id=uuid.uuid4(),
            subject_id=subject.id,
            form_definition_id=form_definition.id,
            status=FormInstanceStatus.submitted,
            created_at=now,
        )
        for subject in subjects
    ]
    db_session.add_all([actor, study, version, site, form_definition, *subjects, *forms])
    await db_session.flush()

    sdv = SDVService()
    review = ReviewService()

    # Every target must support a true -> false round trip. Re-apply the
    # generated final state afterward so progress can be checked independently.
    for subject, form, expected_verified in zip(
        subjects, forms, final_statuses, strict=True
    ):
        sdv_verified = await sdv.set_sdv(
            db_session, SDVScopeType.subject, subject, actor_id=actor_id
        )
        assert sdv_verified.is_verified is True
        assert sdv_verified.verified_by == actor_id
        assert sdv_verified.verified_at is not None

        sdv_cleared = await sdv.clear_sdv(
            db_session, SDVScopeType.subject, subject, actor_id=actor_id
        )
        assert sdv_cleared.is_verified is False
        assert sdv_cleared.verified_by is None
        assert sdv_cleared.verified_at is None

        review_marked = await review.mark_reviewed(
            db_session, form, actor_id=actor_id
        )
        assert review_marked.is_reviewed is True
        assert review_marked.reviewed_by == actor_id
        assert review_marked.reviewed_at is not None

        review_cleared = await review.clear_review(
            db_session, form, actor_id=actor_id
        )
        assert review_cleared.is_reviewed is False
        assert review_cleared.reviewed_by is None
        assert review_cleared.reviewed_at is None

        if expected_verified:
            await sdv.set_sdv(db_session, SDVScopeType.subject, subject, actor_id=actor_id)
            await review.mark_reviewed(db_session, form, actor_id=actor_id)

    expected_verified_count = sum(final_statuses)
    expected_not_verified_count = len(final_statuses) - expected_verified_count

    assert await sdv.progress(
        db_session,
        study_id=study_id,
        scope_type=SDVScopeType.subject,
    ) == {
        "verified": expected_verified_count,
        "not_verified": expected_not_verified_count,
    }
    assert await review.progress(db_session, study_id=study_id) == {
        "reviewed": expected_verified_count,
        "not_reviewed": expected_not_verified_count,
    }

    # Keep the generated example isolated from the next Hypothesis example.
    await db_session.rollback()
