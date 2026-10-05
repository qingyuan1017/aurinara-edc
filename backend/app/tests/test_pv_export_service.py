"""Example-based coverage for PV safety exports on shared infrastructure.

Feature: pv-safety-module, Task 6.1
Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7

Exercises the PVExportService and pv_export_worker against an in-memory
database and an in-memory object store so the shared export-job lifecycle,
PV-only content, intersection filters, the 1,830-day span limit, the
900-second timeout, and download authorization/audit are covered end to end.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthorizationError, BusinessRuleError, ValidationError
from app.core.pv import ActorContext, Module
from app.models.audit import AuditEvent
from app.models.export import Export, ExportStatus
from app.models.identity import User, UserStatus
from app.models.pv.assessment import SeriousnessAssessment
from app.models.pv.regulatory import RegulatoryReport, ReportStatus
from app.models.pv.safety_case import AdverseEventRecord, CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.schemas.pv.export import MAX_DATE_RANGE_DAYS, PVExportFilters, PVExportFormat
from app.services.pv_export_service import EXPORT_TIMEOUT_SECONDS, PVExportService
from app.services.safety_case_service import SafetyCaseService
from app.workers import pv_export_worker


class MemoryStorage:
    """Minimal in-memory object store implementing the storage contract."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_canonical(session: AsyncSession) -> tuple[User, Study, Site, Subject]:
    actor = User(
        email=f"pv-{uuid4()}@example.test",
        first_name="PV",
        last_name="Associate",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()

    study = Study(study_code=f"PV-STUDY-{uuid4()}", title="Safety study", created_by=actor.id)
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
    return actor, study, site, subject


def _actor(user: User) -> ActorContext:
    return ActorContext(user_id=user.id, request_id=str(uuid4()), correlation_id=str(uuid4()))


async def _make_case(
    session: AsyncSession,
    *,
    study: Study,
    site: Site,
    subject: Subject,
    actor: ActorContext,
    case_type: str = "Adverse Event",
) -> SafetyCase:
    return await SafetyCaseService().create_case(
        session,
        study_id=study.id,
        site_id=site.id,
        subject_reference=subject.id,
        case_type=case_type,
        payload={},
        actor=actor,
    )


async def _audit_count(session: AsyncSession, entity_type: str, action: str | None = None) -> int:
    stmt = select(func.count()).select_from(AuditEvent).where(
        AuditEvent.entity_type == entity_type
    )
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    return int((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# Format acceptance (Requirement 12.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fmt",
    [PVExportFormat.CSV, PVExportFormat.EXCEL, PVExportFormat.JSON, PVExportFormat.E2B_XML],
)
async def test_create_export_accepts_pv_formats(db_session: AsyncSession, fmt: PVExportFormat):
    actor, study, _site, _subject = await _seed_canonical(db_session)
    service = PVExportService()

    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=fmt,
        filters=None,
        actor=_actor(actor),
    )

    assert export.export_type == fmt.value
    assert export.status == ExportStatus.queued
    assert export.module == Module.PV.value
    assert export.content_owner == Module.PV.value
    # Creation records exactly one PV safety Audit_Event.
    assert await _audit_count(db_session, "safety_export", "create") == 1


@pytest.mark.asyncio
async def test_create_export_rejects_unknown_format(db_session: AsyncSession):
    actor, study, _site, _subject = await _seed_canonical(db_session)
    service = PVExportService()

    with pytest.raises(ValidationError):
        await service.create_export(
            db_session,
            study_id=study.id,
            export_type="sas_xpt",
            filters=None,
            actor=_actor(actor),
        )

    # No job and no audit event were created (Requirement 12.5).
    assert (await db_session.execute(select(func.count()).select_from(Export))).scalar_one() == 0
    assert await _audit_count(db_session, "safety_export") == 0


# ---------------------------------------------------------------------------
# Date-range span limit (Requirement 12.3)
# ---------------------------------------------------------------------------


def test_filters_reject_span_over_limit():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    too_wide = start + timedelta(days=MAX_DATE_RANGE_DAYS + 1)
    with pytest.raises(ValueError):
        PVExportFilters(date_from=start, date_to=too_wide)


def test_filters_accept_span_at_limit():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    exactly = start + timedelta(days=MAX_DATE_RANGE_DAYS)
    filters = PVExportFilters(date_from=start, date_to=exactly)
    assert filters.date_from == start
    assert filters.date_to == exactly


def test_filters_reject_naive_dates():
    with pytest.raises(ValueError):
        PVExportFilters(date_from=datetime(2020, 1, 1))


@pytest.mark.asyncio
async def test_create_export_rejects_span_without_creating_job(db_session: AsyncSession):
    actor, study, _site, _subject = await _seed_canonical(db_session)
    service = PVExportService()
    start = datetime(2020, 1, 1, tzinfo=UTC)
    filters = {"date_from": start.isoformat(), "date_to": (start + timedelta(days=2000)).isoformat()}

    with pytest.raises(ValidationError):
        await service.create_export(
            db_session,
            study_id=study.id,
            export_type=PVExportFormat.CSV,
            filters=filters,
            actor=_actor(actor),
        )

    assert (await db_session.execute(select(func.count()).select_from(Export))).scalar_one() == 0


# ---------------------------------------------------------------------------
# Worker: produce in-scope Safety_Cases; empty when none qualify (12.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_produces_only_in_scope_cases(db_session: AsyncSession, monkeypatch):
    actor_user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(actor_user)
    case = await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    other_study = Study(study_code=f"OTHER-{uuid4()}", title="Other", created_by=actor_user.id)
    db_session.add(other_study)
    await db_session.flush()

    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)

    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.JSON,
        filters=None,
        actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)

    assert export.status == ExportStatus.completed
    assert export.file_path in storage.objects
    import json

    payload = json.loads(storage.objects[export.file_path])
    identifiers = {row["case_identifier"] for row in payload}
    assert identifiers == {case.case_identifier}


@pytest.mark.asyncio
async def test_worker_empty_result_when_none_qualify(db_session: AsyncSession, monkeypatch):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)

    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.JSON,
        filters=None,
        actor=_actor(actor_user),
    )
    await pv_export_worker.run_pv_export(db_session, export)

    import json

    assert export.status == ExportStatus.completed
    assert json.loads(storage.objects[export.file_path]) == []


# ---------------------------------------------------------------------------
# Intersection filters (Requirement 12.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filters_intersect(db_session: AsyncSession, monkeypatch):
    actor_user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(actor_user)

    # A serious, In Review case.
    serious_case = await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    serious_case.lifecycle_state = CaseState.IN_REVIEW.value
    ae = AdverseEventRecord(
        case_id=serious_case.id,
        verbatim_term="Headache",
        onset_date=date(2023, 1, 1),
        outcome="Recovered",
    )
    db_session.add(ae)
    await db_session.flush()
    db_session.add(SeriousnessAssessment(ae_id=ae.id, serious=True, criteria=["death"]))

    # A non-serious Open case (different status and seriousness).
    other_case = await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    other_ae = AdverseEventRecord(
        case_id=other_case.id,
        verbatim_term="Nausea",
        onset_date=date(2023, 2, 1),
        outcome="Recovered",
    )
    db_session.add(other_ae)
    await db_session.flush()
    db_session.add(SeriousnessAssessment(ae_id=other_ae.id, serious=False, criteria=[]))
    await db_session.flush()

    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)

    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.JSON,
        filters={"case_statuses": [CaseState.IN_REVIEW.value], "seriousness": True},
        actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)

    import json

    payload = json.loads(storage.objects[export.file_path])
    identifiers = {row["case_identifier"] for row in payload}
    assert identifiers == {serious_case.case_identifier}


@pytest.mark.asyncio
async def test_report_status_filter(db_session: AsyncSession, monkeypatch):
    actor_user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(actor_user)

    reported_case = await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    db_session.add(
        RegulatoryReport(
            case_id=reported_case.id,
            report_type="expedited",
            destination="FDA",
            status=ReportStatus.SUBMITTED.value,
            awareness_date=date(2023, 1, 1),
        )
    )
    await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    await db_session.flush()

    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)

    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.JSON,
        filters={"report_statuses": [ReportStatus.SUBMITTED.value]},
        actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)

    import json

    payload = json.loads(storage.objects[export.file_path])
    identifiers = {row["case_identifier"] for row in payload}
    assert identifiers == {reported_case.case_identifier}


# ---------------------------------------------------------------------------
# E2B XML output is well-formed and PV-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2b_xml_export_is_well_formed(db_session: AsyncSession, monkeypatch):
    import xml.etree.ElementTree as ET

    actor_user, study, site, subject = await _seed_canonical(db_session)
    actor = _actor(actor_user)
    case = await _make_case(db_session, study=study, site=site, subject=subject, actor=actor)
    db_session.add(
        AdverseEventRecord(
            case_id=case.id,
            verbatim_term="Rash",
            onset_date=date(2023, 3, 1),
            outcome="Recovered",
        )
    )
    await db_session.flush()

    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)

    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.E2B_XML,
        filters=None,
        actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)

    root = ET.fromstring(storage.objects[export.file_path])
    assert root.tag == "ichicsr"
    reports = root.findall("safetyreport")
    assert len(reports) == 1
    assert reports[0].findtext("safetyreportid") == case.case_identifier
    # No EDC clinical or CTMS operational element leaks into the document.
    assert b"subject_number" not in storage.objects[export.file_path]


# ---------------------------------------------------------------------------
# Timeout: Running > 900s -> Failed, no file (Requirement 12.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_running_job_over_window_fails_without_file(db_session: AsyncSession):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.CSV,
        filters=None,
        actor=_actor(actor_user),
    )
    await service.start_export(db_session, export)

    now = datetime.now(UTC) + timedelta(seconds=EXPORT_TIMEOUT_SECONDS + 1)
    await service.fail_if_timed_out(db_session, export, now=now)

    assert export.status == ExportStatus.failed
    assert export.file_path is None
    assert export.error_message


@pytest.mark.asyncio
async def test_running_job_within_window_not_failed(db_session: AsyncSession):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    service = PVExportService()
    export = await service.create_export(
        db_session,
        study_id=study.id,
        export_type=PVExportFormat.CSV,
        filters=None,
        actor=_actor(actor_user),
    )
    await service.start_export(db_session, export)

    now = datetime.now(UTC) + timedelta(seconds=EXPORT_TIMEOUT_SECONDS - 1)
    await service.fail_if_timed_out(db_session, export, now=now)

    assert export.status == ExportStatus.running


# ---------------------------------------------------------------------------
# Download authorization and audit (Requirements 12.4, 12.7)
# ---------------------------------------------------------------------------


async def _completed_export(session: AsyncSession, monkeypatch, owner: ActorContext, study: Study):
    storage = MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)
    service = PVExportService()
    export = await service.create_export(
        session,
        study_id=study.id,
        export_type=PVExportFormat.CSV,
        filters=None,
        actor=owner,
    )
    await pv_export_worker.run_pv_export(session, export)
    return service, export


@pytest.mark.asyncio
async def test_owner_download_within_window_records_audit(db_session: AsyncSession, monkeypatch):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    owner = _actor(actor_user)
    service, export = await _completed_export(db_session, monkeypatch, owner, study)

    authorized = await service.authorize_download(
        db_session, export_id=export.id, actor=owner, now=export.completed_at
    )

    assert authorized.id == export.id
    assert await _audit_count(db_session, "safety_export", "download") == 1


@pytest.mark.asyncio
async def test_download_denied_after_window(db_session: AsyncSession, monkeypatch):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    owner = _actor(actor_user)
    service, export = await _completed_export(db_session, monkeypatch, owner, study)

    late = export.completed_at + timedelta(seconds=EXPORT_TIMEOUT_SECONDS + 1)
    with pytest.raises(BusinessRuleError):
        await service.authorize_download(db_session, export_id=export.id, actor=owner, now=late)

    assert await _audit_count(db_session, "safety_export", "download") == 0


@pytest.mark.asyncio
async def test_download_denied_for_other_user(db_session: AsyncSession, monkeypatch):
    actor_user, study, _site, _subject = await _seed_canonical(db_session)
    owner = _actor(actor_user)
    service, export = await _completed_export(db_session, monkeypatch, owner, study)

    other = User(
        email=f"other-{uuid4()}@example.test",
        first_name="Other",
        last_name="User",
        status=UserStatus.active,
    )
    db_session.add(other)
    await db_session.flush()
    intruder = ActorContext(user_id=other.id, request_id=str(uuid4()), correlation_id=str(uuid4()))

    with pytest.raises(AuthorizationError):
        await service.authorize_download(
            db_session, export_id=export.id, actor=intruder, now=export.completed_at
        )

    assert await _audit_count(db_session, "safety_export", "download") == 0
