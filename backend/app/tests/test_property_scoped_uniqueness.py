"""Property-based test for scoped uniqueness enforcement.

**Validates: Requirements 4.2, 6.2, 7.2, 22.5**

Property 7: Scoped uniqueness is enforced.

Generates random study codes, site numbers (within studies), and subject numbers
(within studies) and asserts:
  1. Study codes are globally unique — ConflictError on duplicate.
  2. Site numbers are unique within their study — ConflictError on duplicate within
     the same study, OK across different studies.
  3. Subject numbers are unique within their study — ConflictError on duplicate within
     the same study, OK across different studies.
  4. At least 100 iterations.

Uses in-memory SQLite to exercise real DB state. Only the tables needed for this
property are created.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.core.request_context import request_id_var
from app.core.security import hash_password
from app.models.identity import User, UserStatus
from app.models.site import Site, SiteStatus
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject, SubjectStatus
from app.schemas.site import SiteCreate
from app.schemas.study import StudyCreate
from app.schemas.subject import SubjectCreate
from app.services.site_service import SiteService
from app.services.study_service import StudyService
from app.services.subject_service import SubjectService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Study codes: short alphanumeric identifiers.
study_code_strategy = st.from_regex(r"[A-Z]{2,4}-[0-9]{3,6}", fullmatch=True)

# Site numbers: short numeric identifiers.
site_number_strategy = st.from_regex(r"[0-9]{3}", fullmatch=True)

# Subject numbers: site-number style identifiers.
subject_number_strategy = st.from_regex(r"[0-9]{3}-[0-9]{4}", fullmatch=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create an in-memory SQLite async engine with only the needed tables."""
    from app.models.audit import AuditEvent
    from app.models.site import StudySiteUser
    from app.models.visit import VisitDefinition, VisitInstance

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    tables = [
        m.__table__
        for m in (
            User,
            Study,
            StudyVersion,
            Site,
            StudySiteUser,
            Subject,
            AuditEvent,
            VisitDefinition,
            VisitInstance,
        )
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _seed_actor(session: AsyncSession) -> User:
    """Seed an actor user for audit trails."""
    user = User(
        id=uuid.uuid4(),
        email=f"actor-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("pw"),
        first_name="Act",
        last_name="Or",
        status=UserStatus.active,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_study_with_version(
    session: AsyncSession, actor: User, study_code: str
) -> tuple[Study, StudyVersion]:
    """Create a study and a published version for subject enrollment."""
    study = Study(
        id=uuid.uuid4(),
        study_code=study_code,
        title=f"Study {study_code}",
        status=StudyStatus.active,
        created_by=actor.id,
        created_at=datetime.now(UTC),
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        id=uuid.uuid4(),
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
        published_at=datetime.now(UTC),
        published_by=actor.id,
        created_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()

    return study, version


async def _seed_site(
    session: AsyncSession, study: Study, site_number: str
) -> Site:
    """Create a site within a study."""
    site = Site(
        id=uuid.uuid4(),
        study_id=study.id,
        site_number=site_number,
        name=f"Site {site_number}",
        status=SiteStatus.active,
        created_at=datetime.now(UTC),
    )
    session.add(site)
    await session.flush()
    return site


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestScopedUniquenessProperty:
    """Property-based tests for scoped uniqueness enforcement.

    **Validates: Requirements 4.2, 6.2, 7.2, 22.5**
    """

    @settings(max_examples=100, deadline=None)
    @given(study_code=study_code_strategy)
    @pytest.mark.asyncio
    async def test_study_code_globally_unique(self, study_code: str):
        """Duplicate study codes raise ConflictError.

        **Validates: Requirements 4.2**

        For any study code:
          - First creation succeeds.
          - Second creation with the same code raises ConflictError.
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = await _seed_actor(session)
                    svc = StudyService()

                    data = StudyCreate(
                        study_code=study_code,
                        title=f"Study {study_code}",
                    )

                    # First creation succeeds.
                    study = await svc.create_study(session, data, actor.id)
                    assert study.study_code == study_code

                    # Second creation with the same code raises ConflictError.
                    with pytest.raises(ConflictError):
                        await svc.create_study(session, data, actor.id)
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)

    @settings(max_examples=100, deadline=None)
    @given(site_number=site_number_strategy)
    @pytest.mark.asyncio
    async def test_site_number_unique_within_study(self, site_number: str):
        """Duplicate site numbers within the same study raise ConflictError.

        **Validates: Requirements 6.2**

        For any site number:
          - First creation within a study succeeds.
          - Second creation with the same number in the same study raises ConflictError.
          - Creation with the same number in a different study succeeds (scoped).
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = await _seed_actor(session)
                    svc = SiteService()

                    # Create two distinct studies.
                    study_a, _ = await _seed_study_with_version(
                        session, actor, f"SA-{uuid.uuid4().hex[:6]}"
                    )
                    study_b, _ = await _seed_study_with_version(
                        session, actor, f"SB-{uuid.uuid4().hex[:6]}"
                    )

                    data = SiteCreate(site_number=site_number, name="Test Site")

                    # First creation in study_a succeeds.
                    site = await svc.create_site(
                        session, study_a.id, data, actor.id
                    )
                    assert site.site_number == site_number
                    assert site.study_id == study_a.id

                    # Duplicate in the same study raises ConflictError.
                    with pytest.raises(ConflictError):
                        await svc.create_site(session, study_a.id, data, actor.id)

                    # Same number in a different study succeeds (scoped uniqueness).
                    site_b = await svc.create_site(
                        session, study_b.id, data, actor.id
                    )
                    assert site_b.site_number == site_number
                    assert site_b.study_id == study_b.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)

    @settings(max_examples=100, deadline=None)
    @given(subject_number=subject_number_strategy)
    @pytest.mark.asyncio
    async def test_subject_number_unique_within_study(self, subject_number: str):
        """Duplicate subject numbers within the same study raise ConflictError.

        **Validates: Requirements 7.2, 22.5**

        For any subject number:
          - First creation within a study succeeds.
          - Second creation with the same number in the same study raises ConflictError.
          - Creation with the same number in a different study succeeds (scoped).
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = await _seed_actor(session)
                    svc = SubjectService()

                    # Create two distinct studies with published versions and sites.
                    study_a, version_a = await _seed_study_with_version(
                        session, actor, f"SA-{uuid.uuid4().hex[:6]}"
                    )
                    study_b, version_b = await _seed_study_with_version(
                        session, actor, f"SB-{uuid.uuid4().hex[:6]}"
                    )

                    site_a = await _seed_site(session, study_a, "001")
                    site_b = await _seed_site(session, study_b, "001")

                    data_a = SubjectCreate(
                        site_id=site_a.id, subject_number=subject_number
                    )
                    data_b = SubjectCreate(
                        site_id=site_b.id, subject_number=subject_number
                    )

                    # First creation in study_a succeeds.
                    subject = await svc.create_subject(
                        session, study_a.id, data_a, actor.id
                    )
                    assert subject.subject_number == subject_number
                    assert subject.study_id == study_a.id

                    # Duplicate in the same study raises ConflictError.
                    with pytest.raises(ConflictError):
                        await svc.create_subject(
                            session, study_a.id, data_a, actor.id
                        )

                    # Same number in a different study succeeds (scoped uniqueness).
                    subject_b = await svc.create_subject(
                        session, study_b.id, data_b, actor.id
                    )
                    assert subject_b.subject_number == subject_number
                    assert subject_b.study_id == study_b.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)
