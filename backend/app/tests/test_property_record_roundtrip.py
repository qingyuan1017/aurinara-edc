"""Property-based test for record round-trip persistence.

**Validates: Requirements 4.1, 6.1, 6.5, 8.1**

Property 9: Persisted records round-trip.

Generates random study metadata (study_code, title, sponsor, phase), random site
metadata (site_number, name, country), and random visit definition metadata
(name, visit_number, target_day, etc.), creates them via their respective services,
then reads them back and asserts that all persisted fields round-trip exactly
(what was written is what was read).

Uses in-memory SQLite with real service calls. Each iteration creates a fresh DB.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.request_context import request_id_var
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.site import Site, SiteStatus, StudySiteUser
from app.models.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.models.visit import VisitDefinition, VisitInstance
from app.schemas.site import SiteCreate
from app.schemas.study import StudyCreate
from app.schemas.visit import VisitDefinitionCreate
from app.services.site_service import SiteService
from app.services.study_service import StudyService
from app.services.visit_service import VisitService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Study metadata strategies
study_code_strategy = st.from_regex(r"[A-Z]{2,5}-[0-9]{3,6}", fullmatch=True)
study_title_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs"), max_codepoint=0x024F),
    min_size=1,
    max_size=100,
)
sponsor_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(categories=("L", "N", "Zs"), max_codepoint=0x024F),
        min_size=1,
        max_size=50,
    ),
)
phase_strategy = st.one_of(
    st.none(),
    st.sampled_from(["Phase I", "Phase II", "Phase III", "Phase IV"]),
)

# Site metadata strategies
site_number_strategy = st.from_regex(r"[0-9]{3,5}", fullmatch=True)
site_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs"), max_codepoint=0x024F),
    min_size=1,
    max_size=80,
)
country_strategy = st.one_of(
    st.none(),
    st.sampled_from(["US", "UK", "DE", "FR", "JP", "AU", "CA", "BR"]),
)

# Visit definition metadata strategies
visit_name_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "Zs"), max_codepoint=0x024F),
    min_size=1,
    max_size=80,
)
visit_number_strategy = st.integers(min_value=1, max_value=999)
visit_type_strategy = st.sampled_from(["scheduled", "unscheduled", "screening"])
target_day_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=365))
window_before_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=14))
window_after_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=14))
display_order_strategy = st.integers(min_value=1, max_value=100)
is_required_strategy = st.booleans()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create an in-memory SQLite async engine with only the needed tables."""
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


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestRecordRoundTripProperty:
    """Property-based tests for record round-trip persistence.

    **Validates: Requirements 4.1, 6.1, 6.5, 8.1**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        study_code=study_code_strategy,
        title=study_title_strategy,
        sponsor=sponsor_strategy,
        phase=phase_strategy,
    )
    @pytest.mark.asyncio
    async def test_study_metadata_round_trips(
        self, study_code: str, title: str, sponsor: str | None, phase: str | None
    ):
        """Study metadata fields round-trip exactly through create and read-back.

        **Validates: Requirements 4.1**

        For any valid study metadata:
          - Create the study via StudyService.
          - Read it back via get_study.
          - All persisted fields match exactly what was written.
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
                        title=title,
                        sponsor=sponsor,
                        phase=phase,
                    )

                    created = await svc.create_study(session, data, actor.id)
                    await session.commit()

                async with session_factory() as session:
                    svc = StudyService()
                    read_back = await svc.get_study(session, created.id)

                    assert read_back.study_code == study_code
                    assert read_back.title == title
                    assert read_back.sponsor == sponsor
                    assert read_back.phase == phase
                    assert read_back.status == StudyStatus.draft
                    assert read_back.created_by == actor.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)

    @settings(max_examples=100, deadline=None)
    @given(
        site_number=site_number_strategy,
        site_name=site_name_strategy,
        country=country_strategy,
    )
    @pytest.mark.asyncio
    async def test_site_metadata_round_trips(
        self, site_number: str, site_name: str, country: str | None
    ):
        """Site metadata fields round-trip exactly through create and read-back.

        **Validates: Requirements 6.1**

        For any valid site metadata:
          - Create the site via SiteService.
          - Read it back via get_site.
          - All persisted fields match exactly what was written.
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = await _seed_actor(session)

                    # Create a parent study for the site.
                    study = Study(
                        id=uuid.uuid4(),
                        study_code=f"RT-{uuid.uuid4().hex[:6]}",
                        title="Round Trip Study",
                        status=StudyStatus.active,
                        created_by=actor.id,
                    )
                    session.add(study)
                    await session.flush()

                    svc = SiteService()
                    data = SiteCreate(
                        site_number=site_number,
                        name=site_name,
                        country=country,
                    )

                    created = await svc.create_site(session, study.id, data, actor.id)
                    await session.commit()

                async with session_factory() as session:
                    svc = SiteService()
                    read_back = await svc.get_site(session, created.id)

                    assert read_back.site_number == site_number
                    assert read_back.name == site_name
                    assert read_back.country == country
                    assert read_back.study_id == study.id
                    assert read_back.status == SiteStatus.active
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)

    @settings(max_examples=100, deadline=None)
    @given(
        visit_name=visit_name_strategy,
        visit_number=visit_number_strategy,
        visit_type=visit_type_strategy,
        target_day=target_day_strategy,
        window_before=window_before_strategy,
        window_after=window_after_strategy,
        display_order=display_order_strategy,
        is_required=is_required_strategy,
    )
    @pytest.mark.asyncio
    async def test_visit_definition_metadata_round_trips(
        self,
        visit_name: str,
        visit_number: int,
        visit_type: str,
        target_day: int | None,
        window_before: int | None,
        window_after: int | None,
        display_order: int,
        is_required: bool,
    ):
        """Visit definition metadata fields round-trip exactly through create and read-back.

        **Validates: Requirements 8.1**

        For any valid visit definition metadata:
          - Create the visit definition via VisitService.
          - Read it back from the database directly.
          - All persisted fields match exactly what was written.
        """
        ctx = request_id_var.set(str(uuid.uuid4()))
        try:
            engine, session_factory = await _create_engine_and_session()
            try:
                async with session_factory() as session:
                    actor = await _seed_actor(session)

                    # Create a parent study and draft version.
                    study = Study(
                        id=uuid.uuid4(),
                        study_code=f"VD-{uuid.uuid4().hex[:6]}",
                        title="Visit Def Study",
                        status=StudyStatus.active,
                        created_by=actor.id,
                    )
                    session.add(study)
                    await session.flush()

                    version = StudyVersion(
                        id=uuid.uuid4(),
                        study_id=study.id,
                        version_number="1.0",
                        status=StudyVersionStatus.draft,
                    )
                    session.add(version)
                    await session.flush()

                    svc = VisitService()
                    data = VisitDefinitionCreate(
                        name=visit_name,
                        visit_number=visit_number,
                        visit_type=visit_type,
                        target_day=target_day,
                        window_before=window_before,
                        window_after=window_after,
                        display_order=display_order,
                        is_required=is_required,
                    )

                    created = await svc.define_visit(session, version, data, actor.id)
                    await session.commit()

                async with session_factory() as session:
                    from sqlalchemy import select

                    result = await session.execute(
                        select(VisitDefinition).where(
                            VisitDefinition.id == created.id
                        )
                    )
                    read_back = result.scalars().first()

                    assert read_back is not None
                    assert read_back.name == visit_name
                    assert read_back.visit_number == visit_number
                    assert read_back.visit_type == visit_type
                    assert read_back.target_day == target_day
                    assert read_back.window_before == window_before
                    assert read_back.window_after == window_after
                    assert read_back.display_order == display_order
                    assert read_back.is_required == is_required
                    assert read_back.study_version_id == version.id
            finally:
                await engine.dispose()
        finally:
            request_id_var.reset(ctx)
