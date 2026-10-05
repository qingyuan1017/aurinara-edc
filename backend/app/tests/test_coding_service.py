"""Example-based coverage for PV MedDRA/WHODrug coding.

Feature: pv-safety-module, Task 3.2
Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

Exercises the CodingService against an in-memory database so persistence,
dictionary-version/term validation, recoding traceability, and the atomic PV
safety Audit_Event are covered end to end. Term validation uses a deterministic
in-memory dictionary provider with pinned term sets; no external service is
used.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import NotFoundError, ValidationError
from app.core.pv import ActorContext
from app.models.audit import AuditEvent
from app.models.identity import User, UserStatus
from app.models.pv.coding import (
    CodingSystem,
    MedDraCoding,
    WhoDrugCoding,
)
from app.models.pv.safety_case import CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.repositories.pv.coding_repository import CodingRepository
from app.services.coding_service import CodingService
from app.services.pv_coding_dictionary import CodingDictionaryProvider

MEDDRA_VERSION = "27.0"
WHODRUG_VERSION = "2024-MAR"
VALID_MEDDRA_TERM = "10019211"  # "Headache" (pinned)
VALID_WHODRUG_TERM = "APROD-001"


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _dictionary() -> CodingDictionaryProvider:
    provider = CodingDictionaryProvider()
    provider.register(
        coding_system=CodingSystem.MEDDRA,
        version=MEDDRA_VERSION,
        terms=frozenset({VALID_MEDDRA_TERM, "10028395"}),
    )
    provider.register(
        coding_system=CodingSystem.WHODRUG,
        version=WHODRUG_VERSION,
        terms=frozenset({VALID_WHODRUG_TERM, "APROD-002"}),
    )
    return provider


def _service() -> CodingService:
    return CodingService(dictionary=_dictionary())


def _actor(user: User) -> ActorContext:
    return ActorContext(
        user_id=user.id, request_id=str(uuid4()), correlation_id=str(uuid4())
    )


async def _seed(session: AsyncSession, *, closed: bool = False):
    actor = User(
        email=f"coder-{uuid4()}@example.test",
        first_name="PV",
        last_name="Coder",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()

    study = Study(study_code=f"S-{uuid4()}", title="Coding study", created_by=actor.id)
    session.add(study)
    await session.flush()

    version = StudyVersion(
        study_id=study.id, version_number="1.0", status=StudyVersionStatus.published
    )
    session.add(version)
    await session.flush()

    site = Site(study_id=study.id, site_number="001", name="Site A")
    session.add(site)
    await session.flush()

    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=version.id,
        subject_number="S-001",
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()

    case = SafetyCase(
        case_identifier=f"PV-{uuid4().hex[:12].upper()}",
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type="Adverse Event",
        lifecycle_state=(CaseState.CLOSED.value if closed else CaseState.OPEN.value),
        created_by=actor.id,
    )
    session.add(case)
    await session.flush()

    from app.models.pv.safety_case import AdverseEventRecord

    ae = AdverseEventRecord(
        case_id=case.id,
        verbatim_term="bad headache",
        onset_date=date(2024, 1, 1),
        outcome="recovered",
        created_by=actor.id,
    )
    session.add(ae)
    await session.flush()
    return actor, case, ae


async def _register_versions(session: AsyncSession, *, meddra=True, whodrug=True) -> None:
    repo = CodingRepository(session)
    if meddra:
        await repo.add_dictionary_version(
            coding_system=CodingSystem.MEDDRA, version=MEDDRA_VERSION, available=True
        )
    if whodrug:
        await repo.add_dictionary_version(
            coding_system=CodingSystem.WHODRUG, version=WHODRUG_VERSION, available=True
        )


async def _audit_count(session: AsyncSession, entity_type: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_type == entity_type
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# MedDRA assignment (Requirements 6.1, 6.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_meddra_persists_coding_and_audit(db_session: AsyncSession):
    actor, _case, ae = await _seed(db_session)
    await _register_versions(db_session)

    coding = await _service().assign_meddra(
        db_session,
        ae_id=ae.id,
        term_id=VALID_MEDDRA_TERM,
        dictionary_version=MEDDRA_VERSION,
        actor=_actor(actor),
        term_label="Headache",
    )

    assert coding.ae_id == ae.id
    assert coding.term_id == VALID_MEDDRA_TERM
    assert coding.dictionary_version == MEDDRA_VERSION
    assert coding.assigned_by == actor.id
    assert coding.assigned_at is not None
    assert coding.prior_coding_id is None
    assert await _audit_count(db_session, "meddra_coding") == 1


@pytest.mark.asyncio
async def test_assign_whodrug_persists_coding_and_audit(db_session: AsyncSession):
    actor, _case, _ae = await _seed(db_session)
    await _register_versions(db_session)
    product_id = uuid4()

    coding = await _service().assign_whodrug(
        db_session,
        product_id=product_id,
        term_id=VALID_WHODRUG_TERM,
        dictionary_version=WHODRUG_VERSION,
        actor=_actor(actor),
    )

    assert coding.product_id == product_id
    assert coding.term_id == VALID_WHODRUG_TERM
    assert coding.dictionary_version == WHODRUG_VERSION
    assert await _audit_count(db_session, "whodrug_coding") == 1


# ---------------------------------------------------------------------------
# Rejections persist no coding (Requirements 6.3, 6.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_meddra_rejects_unknown_term(db_session: AsyncSession):
    actor, _case, ae = await _seed(db_session)
    await _register_versions(db_session)

    with pytest.raises(ValidationError) as exc:
        await _service().assign_meddra(
            db_session,
            ae_id=ae.id,
            term_id="NOT-A-TERM",
            dictionary_version=MEDDRA_VERSION,
            actor=_actor(actor),
        )
    assert exc.value.details["reason"] == "CODING_TERM_NOT_FOUND"
    assert await _row_count(db_session, MedDraCoding) == 0
    assert await _audit_count(db_session, "meddra_coding") == 0


@pytest.mark.asyncio
async def test_assign_meddra_rejects_unavailable_version(db_session: AsyncSession):
    actor, _case, ae = await _seed(db_session)
    # No dictionary versions registered at all.

    with pytest.raises(ValidationError) as exc:
        await _service().assign_meddra(
            db_session,
            ae_id=ae.id,
            term_id=VALID_MEDDRA_TERM,
            dictionary_version=MEDDRA_VERSION,
            actor=_actor(actor),
        )
    assert exc.value.details["reason"] == "CODING_DICTIONARY_UNAVAILABLE"
    assert await _row_count(db_session, MedDraCoding) == 0


@pytest.mark.asyncio
async def test_assign_whodrug_rejects_version_marked_unavailable(db_session: AsyncSession):
    actor, _case, _ae = await _seed(db_session)
    repo = CodingRepository(db_session)
    await repo.add_dictionary_version(
        coding_system=CodingSystem.WHODRUG, version=WHODRUG_VERSION, available=False
    )

    with pytest.raises(ValidationError) as exc:
        await _service().assign_whodrug(
            db_session,
            product_id=uuid4(),
            term_id=VALID_WHODRUG_TERM,
            dictionary_version=WHODRUG_VERSION,
            actor=_actor(actor),
        )
    assert exc.value.details["reason"] == "CODING_DICTIONARY_UNAVAILABLE"
    assert await _row_count(db_session, WhoDrugCoding) == 0


@pytest.mark.asyncio
async def test_assign_meddra_rejects_missing_adverse_event(db_session: AsyncSession):
    actor, _case, _ae = await _seed(db_session)
    await _register_versions(db_session)

    with pytest.raises(NotFoundError):
        await _service().assign_meddra(
            db_session,
            ae_id=uuid4(),
            term_id=VALID_MEDDRA_TERM,
            dictionary_version=MEDDRA_VERSION,
            actor=_actor(actor),
        )
    assert await _row_count(db_session, MedDraCoding) == 0


@pytest.mark.asyncio
async def test_assign_meddra_rejected_when_case_closed(db_session: AsyncSession):
    actor, _case, ae = await _seed(db_session, closed=True)
    await _register_versions(db_session)

    with pytest.raises(ValidationError) as exc:
        await _service().assign_meddra(
            db_session,
            ae_id=ae.id,
            term_id=VALID_MEDDRA_TERM,
            dictionary_version=MEDDRA_VERSION,
            actor=_actor(actor),
        )
    assert exc.value.details["reason"] == "CASE_CLOSED"
    assert await _row_count(db_session, MedDraCoding) == 0


# ---------------------------------------------------------------------------
# Recode retains the prior assignment immutably and links it (Requirements 6.5, 6.6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recode_meddra_retains_prior_and_links(db_session: AsyncSession):
    actor, _case, ae = await _seed(db_session)
    await _register_versions(db_session)
    service = _service()

    prior = await service.assign_meddra(
        db_session,
        ae_id=ae.id,
        term_id=VALID_MEDDRA_TERM,
        dictionary_version=MEDDRA_VERSION,
        actor=_actor(actor),
    )
    prior_term = prior.term_id
    prior_version = prior.dictionary_version

    new_coding = await service.recode(
        db_session,
        prior_coding_id=prior.id,
        term_id="10028395",
        dictionary_version=MEDDRA_VERSION,
        actor=_actor(actor),
    )

    assert isinstance(new_coding, MedDraCoding)
    assert new_coding.prior_coding_id == prior.id
    assert new_coding.ae_id == ae.id
    assert new_coding.term_id == "10028395"

    # The prior assignment is unchanged (immutable).
    reloaded_prior = await CodingRepository(db_session).get_meddra_coding(prior.id)
    assert reloaded_prior is not None
    assert reloaded_prior.term_id == prior_term
    assert reloaded_prior.dictionary_version == prior_version
    assert reloaded_prior.prior_coding_id is None

    # Two rows total, and the recode emitted its own audit event.
    assert await _row_count(db_session, MedDraCoding) == 2
    assert await _audit_count(db_session, "meddra_coding") == 2


@pytest.mark.asyncio
async def test_recode_rejects_unknown_prior(db_session: AsyncSession):
    actor, _case, _ae = await _seed(db_session)
    await _register_versions(db_session)

    with pytest.raises(NotFoundError):
        await _service().recode(
            db_session,
            prior_coding_id=uuid4(),
            term_id=VALID_MEDDRA_TERM,
            dictionary_version=MEDDRA_VERSION,
            actor=_actor(actor),
        )


@pytest.mark.asyncio
async def test_recode_whodrug_preserves_product_and_links(db_session: AsyncSession):
    actor, _case, _ae = await _seed(db_session)
    await _register_versions(db_session)
    service = _service()
    product_id = uuid4()

    prior = await service.assign_whodrug(
        db_session,
        product_id=product_id,
        term_id=VALID_WHODRUG_TERM,
        dictionary_version=WHODRUG_VERSION,
        actor=_actor(actor),
    )

    new_coding = await service.recode(
        db_session,
        prior_coding_id=prior.id,
        term_id="APROD-002",
        dictionary_version=WHODRUG_VERSION,
        actor=_actor(actor),
    )

    assert isinstance(new_coding, WhoDrugCoding)
    assert new_coding.product_id == product_id
    assert new_coding.prior_coding_id == prior.id
    assert await _row_count(db_session, WhoDrugCoding) == 2


async def _row_count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())
