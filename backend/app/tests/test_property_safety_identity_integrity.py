"""Property-based test for PV safety identity and reference integrity.

Feature: pv-safety-module, Task 2.3
**Validates: Requirements 3, 10, 23**

Property 1: Safety identity and reference integrity.

*For any* valid Study, Site, Subject_Reference, and Safety_Case sequence:
  1. Canonical Study/Site identity remains stable (the identifiers PV persists
     equal the canonical EDC identifiers and are never rewritten).
  2. Each Safety_Case references exactly one canonical Subject_Reference without
     duplicating or mutating the EDC clinical identity.
  3. Each safety case identifier is globally unique across the platform.
  4. Each Adverse_Event_Record belongs to exactly one Safety_Case.

Uses in-memory SQLite (matching test_safety_case_service.py) to exercise real
persistence through SafetyCaseService/SafetyCaseRepository/PVIdentityResolver,
with no external services and at least 100 generated examples.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.pv import ActorContext
from app.models.identity import User, UserStatus
from app.models.pv.safety_case import AdverseEventRecord, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.services.safety_case_service import SafetyCaseService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A sequence of one or more subject "slots"; each entry drives creating a
# canonical Subject_Reference and a number of Safety_Cases bound to it.
subject_case_sequence_strategy = st.lists(
    st.integers(min_value=1, max_value=3),
    min_size=1,
    max_size=4,
)

# Number of adverse events to capture per created Safety_Case.
adverse_event_count_strategy = st.integers(min_value=0, max_value=3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_engine_and_session():
    """Create an in-memory SQLite async engine with the full metadata."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, session_factory


async def _seed_actor(session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"pv-{uuid.uuid4().hex[:8]}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_study_site(
    session: AsyncSession, actor: User
) -> tuple[Study, StudyVersion, Site]:
    study = Study(
        study_code=f"PV-{uuid.uuid4().hex[:8]}",
        title="Safety study",
        created_by=actor.id,
    )
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.published,
    )
    session.add(version)
    await session.flush()

    site = Site(study_id=study.id, site_number="001", name="Site A")
    session.add(site)
    await session.flush()
    return study, version, site


async def _seed_subject(
    session: AsyncSession,
    actor: User,
    study: Study,
    version: StudyVersion,
    site: Site,
    subject_number: str,
) -> Subject:
    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number=subject_number,
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    return subject


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4())
    )


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestSafetyIdentityIntegrityProperty:
    """Property 1: Safety identity and reference integrity.

    **Validates: Requirements 3, 10, 23**
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        sequence=subject_case_sequence_strategy,
        events_per_case=adverse_event_count_strategy,
    )
    @pytest.mark.asyncio
    async def test_identity_and_reference_integrity(
        self, sequence: list[int], events_per_case: int
    ):
        """Create valid Study/Site/Subject_Reference/Safety_Case sequences and
        assert canonical identity stability, single-subject references, globally
        unique case identifiers, and single-case adverse-event ownership.
        """
        engine, session_factory = await _create_engine_and_session()
        try:
            async with session_factory() as session:
                service = SafetyCaseService()
                actor_user = await _seed_actor(session)
                actor = _actor(actor_user)
                study, version, site = await _seed_study_site(session, actor_user)

                # Canonical identity captured up front; must remain stable.
                canonical_study_id = study.id
                canonical_site_id = site.id

                created_case_ids: list[uuid.UUID] = []
                case_identifiers: list[str] = []
                # Map each created case to the subject it should reference.
                case_to_subject: dict[uuid.UUID, uuid.UUID] = {}
                # Track adverse-event -> case ownership.
                event_to_case: dict[uuid.UUID, uuid.UUID] = {}

                for idx, cases_for_subject in enumerate(sequence):
                    subject = await _seed_subject(
                        session,
                        actor_user,
                        study,
                        version,
                        site,
                        subject_number=f"S-{idx:04d}",
                    )
                    # Snapshot the clinical identity to detect mutation.
                    original_subject_number = subject.subject_number

                    for _ in range(cases_for_subject):
                        case = await service.create_case(
                            session,
                            study_id=study.id,
                            site_id=site.id,
                            subject_reference=subject.id,
                            case_type="Adverse Event",
                            payload={},
                            actor=actor,
                        )

                        # (2) Each Safety_Case references exactly one canonical
                        # Subject_Reference, unchanged from what was requested.
                        assert case.subject_reference == subject.id
                        # (1) Canonical Study/Site identity is preserved on the
                        # PV record exactly as the canonical EDC identifiers.
                        assert case.study_id == canonical_study_id
                        assert case.site_id == canonical_site_id

                        created_case_ids.append(case.id)
                        case_identifiers.append(case.case_identifier)
                        case_to_subject[case.id] = subject.id

                        # Capture adverse events under this case.
                        onset = date(2026, 1, 1)
                        for ev in range(events_per_case):
                            record = await service.add_adverse_event(
                                session,
                                case_id=case.id,
                                payload={
                                    "verbatim_term": f"term-{ev}",
                                    "onset_date": onset,
                                    "outcome": "Recovered",
                                    "resolution_date": onset + timedelta(days=ev),
                                },
                                actor=actor,
                            )
                            # (4) The adverse event belongs to this one case.
                            assert record.case_id == case.id
                            event_to_case[record.id] = case.id

                        # (2) The EDC clinical subject identity is never mutated
                        # by PV case/adverse-event creation.
                        refreshed_subject = await session.get(Subject, subject.id)
                        assert refreshed_subject.subject_number == original_subject_number

                # (1) Canonical Study/Site rows are untouched by PV.
                refreshed_study = await session.get(Study, canonical_study_id)
                refreshed_site = await session.get(Site, canonical_site_id)
                assert refreshed_study.id == canonical_study_id
                assert refreshed_site.id == canonical_site_id

                # (3) Each safety case identifier is globally unique.
                assert len(case_identifiers) == len(set(case_identifiers))
                distinct_persisted = (
                    await session.execute(
                        select(func.count(func.distinct(SafetyCase.case_identifier)))
                    )
                ).scalar_one()
                total_persisted = (
                    await session.execute(select(func.count()).select_from(SafetyCase))
                ).scalar_one()
                assert distinct_persisted == total_persisted == len(created_case_ids)

                # (2) Every persisted case references exactly the subject it was
                # created against.
                persisted_cases = (
                    await session.execute(select(SafetyCase))
                ).scalars().all()
                for persisted in persisted_cases:
                    assert persisted.subject_reference == case_to_subject[persisted.id]

                # (4) Each Adverse_Event_Record belongs to exactly one, correct
                # Safety_Case.
                persisted_events = (
                    await session.execute(select(AdverseEventRecord))
                ).scalars().all()
                assert len(persisted_events) == len(event_to_case)
                seen_event_ids: set[uuid.UUID] = set()
                for event in persisted_events:
                    assert event.id not in seen_event_ids
                    seen_event_ids.add(event.id)
                    assert event.case_id == event_to_case[event.id]
        finally:
            await engine.dispose()
