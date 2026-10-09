"""Property-based test for subject single published-design binding.

# Feature: designer-edc-refactor, Property 4: Single published-design binding at subject start

Property 4 (design.md): For all subjects for whom study conduct is started, the
subject is bound to exactly one Published_Design (identified by its
Design_Version) and to the selected Site.

The binding happens in ``app/services/edc/subject_service.py`` ``create_subject``,
which calls ``_get_published_version`` to find the latest Published Design_Version
and binds the new Subject to it via ``study_version_id``.

This test asserts, across studies with varied published/draft version histories:

* When at least one Published_Design exists, ``create_subject`` creates exactly
  one Subject whose ``study_version_id`` is non-null, references a *published*
  Design_Version, is the *current/latest* published one (newest ``published_at``),
  and is bound to the selected Site (R2.7, R7.3).
* When no Published_Design exists, ``create_subject`` is rejected with a
  ``BusinessRuleError`` and no Subject row is created, leaving study data
  unchanged (R2.8 / R7.9).

Study version histories are generated with Hypothesis so a wide range of
draft/published mixes (including the no-published-version case) is exercised.

**Validates: Requirements 2.7, 7.3**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from app.core.exceptions import BusinessRuleError
from app.models.edc.site import Site, SiteStatus
from app.models.edc.study import (
    Study,
    StudyStatus,
    StudyVersion,
    StudyVersionStatus,
)
from app.models.edc.subject import Subject
from app.models.shared.identity import User, UserStatus
from app.schemas.edc.subject import SubjectCreate
from app.services.edc.subject_service import SubjectService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A version history is a non-empty sequence of booleans: each element is one
# Design_Version in the study, True => published, False => draft. The ordering
# fixes the chronological order (and therefore the published_at ordering) of the
# versions so the "latest published" expectation is deterministic.
_version_history = st.lists(st.booleans(), min_size=1, max_size=8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_study_with_history(
    session: AsyncSession, published_flags: list[bool]
) -> tuple[Study, Site, User, list[StudyVersion]]:
    """Create a Study + Site + User and a Design_Version per ``published_flags``.

    Published versions receive a strictly increasing ``published_at`` following
    their position in ``published_flags`` so the newest published version is
    deterministic.

    Returns the study, its site, the acting user, and the ordered versions.
    """
    user = User(
        email=f"op-{uuid4().hex[:12]}@example.test",
        first_name="Op",
        last_name="User",
        status=UserStatus.active,
        mfa_enabled=False,
    )
    session.add(user)
    await session.flush()

    study = Study(
        study_code=f"STUDY-{uuid4().hex[:8]}",
        title="Binding Study",
        status=StudyStatus.active,
        created_by=user.id,
    )
    session.add(study)
    await session.flush()

    site = Site(
        study_id=study.id,
        site_number=f"S{uuid4().hex[:4]}",
        name="Test Site",
        status=SiteStatus.active,
    )
    session.add(site)
    await session.flush()

    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    versions: list[StudyVersion] = []
    for index, is_published in enumerate(published_flags):
        if is_published:
            status = StudyVersionStatus.published
            published_at = base_time + timedelta(days=index)
            published_by = user.id
        else:
            status = StudyVersionStatus.draft
            published_at = None
            published_by = None
        version = StudyVersion(
            study_id=study.id,
            version_number=f"{index + 1}.0",
            status=status,
            published_at=published_at,
            published_by=published_by,
        )
        session.add(version)
        versions.append(version)
    await session.flush()
    return study, site, user, versions


def _expected_latest_published(
    published_flags: list[bool], versions: list[StudyVersion]
) -> StudyVersion | None:
    """Return the version the subject must bind to: newest published, else None."""
    published = [
        version
        for version, is_published in zip(versions, published_flags, strict=True)
        if is_published
    ]
    if not published:
        return None
    # ``published_at`` increases with position, so the last published is newest.
    return max(published, key=lambda version: version.published_at)


# ---------------------------------------------------------------------------
# Property 4
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(published_flags=_version_history)
async def test_subject_binds_to_single_published_design(
    published_flags: list[bool],
):
    """Subject creation binds to exactly one published design, or is rejected.

    For every generated study:

    * If any Design_Version is published, ``create_subject`` persists exactly one
      Subject bound (via a non-null ``study_version_id``) to the newest published
      version and to the selected Site.
    * If no Design_Version is published, ``create_subject`` raises
      ``BusinessRuleError`` and no Subject is created.

    **Validates: Requirements 2.7, 7.3**
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            service = SubjectService()
            study, site, user, versions = await _seed_study_with_history(
                session, published_flags
            )
            expected_version = _expected_latest_published(published_flags, versions)

            create_data = SubjectCreate(site_id=site.id)

            if expected_version is None:
                # No Published_Design: creation is rejected and nothing persisted.
                with pytest.raises(BusinessRuleError):
                    await service.create_subject(
                        session, study.id, create_data, actor_id=user.id
                    )

                subject_count = (
                    await session.execute(
                        select(func.count())
                        .select_from(Subject)
                        .where(Subject.study_id == study.id)
                    )
                ).scalar_one()
                assert subject_count == 0
                return

            # A Published_Design exists: exactly one bound Subject is created.
            subject = await service.create_subject(
                session, study.id, create_data, actor_id=user.id
            )

            # Bound to exactly one Design_Version via a non-null FK (R2.7).
            assert subject.study_version_id is not None
            # The bound version is the newest *published* one (R7.3).
            assert subject.study_version_id == expected_version.id
            # Bound to the selected Site.
            assert subject.site_id == site.id

            # Re-read: the binding references a PUBLISHED version and is stable.
            stored = (
                await session.execute(
                    select(Subject).where(Subject.id == subject.id)
                )
            ).scalar_one()
            assert stored.study_version_id == expected_version.id

            bound_version = (
                await session.execute(
                    select(StudyVersion).where(
                        StudyVersion.id == stored.study_version_id
                    )
                )
            ).scalar_one()
            assert bound_version.status == StudyVersionStatus.published

            # Exactly one Subject was created for the study.
            subject_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Subject)
                    .where(Subject.study_id == study.id)
                )
            ).scalar_one()
            assert subject_count == 1
    finally:
        await engine.dispose()
