"""Property-based test for scoped uniqueness enforcement.

**Validates: Requirements 4.2, 6.2, 7.2, 22.5**

Property 7: Scoped uniqueness is enforced.

For any two records of the same kind, the system rejects:
  1. A second study with a duplicate study code (globally unique) — Req 4.2.
  2. A second site with a duplicate site number within the same study,
     while allowing the same site number in a *different* study — Req 6.2.
  3. A second subject with a duplicate subject number within the same study,
     while allowing the same subject number in a *different* study — Req 7.2.

Each property generates random valid codes/numbers and random study groupings
and runs at least 100 iterations against a per-iteration in-memory SQLite engine.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.core.exceptions import ConflictError
from app.core.request_context import request_id_var
from app.models.audit import AuditEvent
from app.models.site import Site, StudySiteUser
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.models.visit import VisitDefinition, VisitInstance
from app.schemas.site import SiteCreate
from app.schemas.study import StudyCreate
from app.schemas.subject import SubjectCreate
from app.services.site_service import SiteService
from app.services.study_service import StudyService
from app.services.subject_service import SubjectService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Codes/numbers: short non-empty alphanumeric tokens (with hyphen) that satisfy
# the schema length constraints (study_code <=100, site_number <=50,
# subject_number <=100).
code_strategy = st.from_regex(r"[A-Z][A-Z0-9\-]{1,20}", fullmatch=True)

# Two-element grouping decision: whether the second record lands in the same
# study or a different one.
same_study_strategy = st.booleans()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Only the tables needed for study/site/subject creation. The full metadata
# includes Postgres-only JSONB columns (form metadata) that SQLite cannot
# render, so we restrict creation to the relevant tables.
_REQUIRED_TABLES = [
    Study.__table__,
    StudyVersion.__table__,
    Site.__table__,
    StudySiteUser.__table__,
    Subject.__table__,
    VisitDefinition.__table__,
    VisitInstance.__table__,
    AuditEvent.__table__,
]


async def _create_engine_and_session():
    """Create a fresh in-memory SQLite async engine + session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=_REQUIRED_TABLES)
        )
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _make_study(
    session: AsyncSession, service: StudyService, study_code: str, actor_id: uuid.UUID
) -> Study:
    """Create a study and publish its initial version (so subjects can enroll)."""
    study = await service.create_study(
        session, StudyCreate(study_code=study_code, title="Test Study"), actor_id
    )
    # Publish the auto-created initial version so subjects can be enrolled.
    result = await session.execute(
        select(StudyVersion).where(StudyVersion.study_id == study.id)
    )
    version = result.scalars().first()
    version.status = StudyVersionStatus.published
    version.published_at = datetime.now(UTC)
    version.published_by = actor_id
    await session.flush()
    return study


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestScopedUniquenessProperty:
    """Property-based tests for scoped uniqueness enforcement.

    **Validates: Requirements 4.2, 6.2, 7.2, 22.5**
    """

    @settings(max_examples=100, deadline=None)
    @given(study_code=code_strategy)
    @pytest.mark.asyncio
    async def test_duplicate_study_code_is_rejected_globally(self, study_code: str):
        """Creating a second study with the same study_code raises ConflictError.

        **Validates: Requirements 4.2**
        """
        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor_id = uuid.uuid4()
                    service = StudyService()

                    await service.create_study(
                        session,
                        StudyCreate(study_code=study_code, title="First"),
                        actor_id,
                    )

                    with pytest.raises(ConflictError):
                        await service.create_study(
                            session,
                            StudyCreate(study_code=study_code, title="Second"),
                            actor_id,
                        )
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        site_number=code_strategy,
        code_a=code_strategy,
        code_b=code_strategy,
        same_study=same_study_strategy,
    )
    @pytest.mark.asyncio
    async def test_site_number_unique_within_study(
        self,
        site_number: str,
        code_a: str,
        code_b: str,
        same_study: bool,
    ):
        """Site number is unique within a study, but allowed across studies.

        **Validates: Requirements 6.2**

        - Two sites with the same site_number in the SAME study → ConflictError.
        - The same site_number in DIFFERENT studies → allowed.
        """
        # Distinct study codes are required to build two distinct studies.
        if code_a == code_b:
            same_study = True

        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor_id = uuid.uuid4()
                    study_service = StudyService()
                    site_service = SiteService()

                    study_a = await study_service.create_study(
                        session,
                        StudyCreate(study_code=code_a, title="Study A"),
                        actor_id,
                    )

                    await site_service.create_site(
                        session,
                        study_a.id,
                        SiteCreate(site_number=site_number, name="Site 1"),
                        actor_id,
                    )

                    if same_study:
                        # Duplicate within the same study must be rejected.
                        with pytest.raises(ConflictError):
                            await site_service.create_site(
                                session,
                                study_a.id,
                                SiteCreate(site_number=site_number, name="Site 2"),
                                actor_id,
                            )
                    else:
                        # Same site_number in a DIFFERENT study is allowed.
                        study_b = await study_service.create_study(
                            session,
                            StudyCreate(study_code=code_b, title="Study B"),
                            actor_id,
                        )
                        site = await site_service.create_site(
                            session,
                            study_b.id,
                            SiteCreate(site_number=site_number, name="Site 2"),
                            actor_id,
                        )
                        assert site.id is not None
                        assert site.site_number == site_number
                        assert site.study_id == study_b.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)

    @settings(max_examples=100, deadline=None)
    @given(
        subject_number=code_strategy,
        site_number=code_strategy,
        code_a=code_strategy,
        code_b=code_strategy,
        same_study=same_study_strategy,
    )
    @pytest.mark.asyncio
    async def test_subject_number_unique_within_study(
        self,
        subject_number: str,
        site_number: str,
        code_a: str,
        code_b: str,
        same_study: bool,
    ):
        """Subject number is unique within a study, but allowed across studies.

        **Validates: Requirements 7.2**

        - Two subjects with the same subject_number in the SAME study → ConflictError.
        - The same subject_number in DIFFERENT studies → allowed.
        """
        if code_a == code_b:
            same_study = True

        token = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor_id = uuid.uuid4()
                    study_service = StudyService()
                    site_service = SiteService()
                    subject_service = SubjectService()

                    study_a = await _make_study(
                        session, study_service, code_a, actor_id
                    )
                    site_a = await site_service.create_site(
                        session,
                        study_a.id,
                        SiteCreate(site_number=site_number, name="Site A"),
                        actor_id,
                    )

                    await subject_service.create_subject(
                        session,
                        study_a.id,
                        SubjectCreate(
                            site_id=site_a.id, subject_number=subject_number
                        ),
                        actor_id,
                    )

                    if same_study:
                        # Duplicate within the same study must be rejected.
                        with pytest.raises(ConflictError):
                            await subject_service.create_subject(
                                session,
                                study_a.id,
                                SubjectCreate(
                                    site_id=site_a.id,
                                    subject_number=subject_number,
                                ),
                                actor_id,
                            )
                    else:
                        # Same subject_number in a DIFFERENT study is allowed.
                        study_b = await _make_study(
                            session, study_service, code_b, actor_id
                        )
                        site_b = await site_service.create_site(
                            session,
                            study_b.id,
                            SiteCreate(site_number=site_number, name="Site B"),
                            actor_id,
                        )
                        subject = await subject_service.create_subject(
                            session,
                            study_b.id,
                            SubjectCreate(
                                site_id=site_b.id, subject_number=subject_number
                            ),
                            actor_id,
                        )
                        assert subject.id is not None
                        assert subject.subject_number == subject_number
                        assert subject.study_id == study_b.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(token)
