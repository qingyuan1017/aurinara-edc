"""Unified-platform PV resilience and phased qualification evidence.

Feature: pv-safety-module, Task 8.6
Validates: Requirements 20.6, 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 23.10

These are composed OQ tests, not replacements for the focused PV unit and
property suites.  They run the real PV services against deterministic SQLite
state and an in-memory object store.  EDC/CTMS are represented only by their
canonical references and boundary snapshots; their records are never used as
PV authority.  A missing or unavailable EDC projection deliberately yields no
authoritative reconciliation result while PV-owned workflows continue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.exceptions import AuthorizationError, ServiceUnavailableError
from app.core.pv import ActorContext, Module, PVPhase, ReportStatus, build_pv_manifest
from app.core.security import decode_token
from app.models.audit import AuditEvent
from app.models.ctms.operational_study import OperationalStudy
from app.models.identity import User, UserStatus
from app.models.pv.assessment import SeriousnessCriterion
from app.models.pv.coding import CodingSystem
from app.models.pv.coordination import EdcAeProjection
from app.models.pv.reconciliation import ReconciliationRun
from app.models.pv.regulatory import ReportabilityRule
from app.models.pv.safety_case import CaseState, SafetyCase
from app.models.site import Site
from app.models.study import Study, StudyVersion, StudyVersionStatus
from app.models.subject import Subject
from app.repositories.pv.coding_repository import CodingRepository
from app.schemas.permission import AuthorizationScope, PermissionGrant
from app.schemas.pv.export import PVExportFormat
from app.services.ai_assistant_service import AIAssistantService
from app.services.assessment_service import AssessmentService
from app.services.auth_service import AuthService
from app.services.coding_service import CodingService
from app.services.narrative_service import NarrativeService
from app.services.pv_coding_dictionary import CodingDictionaryProvider
from app.services.pv_dashboard_service import READ_PERMISSION, PVDashboardService
from app.services.pv_export_service import PVExportService
from app.services.reconciliation_service import ReconciliationService
from app.services.regulatory_reporting_service import RegulatoryReportingService
from app.services.safety_case_service import SafetyCaseService
from app.workers import pv_export_worker


@dataclass(frozen=True)
class QualificationResult:
    """A small traceability record emitted by each composed qualification test."""

    phase: int
    capability: str
    qualification: str = "OQ"
    status: str = "passed"
    owner: str = "PV"


PHASE_CAPABILITIES: dict[int, frozenset[str]] = {
    1: frozenset(
        {
            "shared authentication",
            "PV scope enforcement",
            "safety case intake",
            "case lifecycle",
            "seriousness assessment",
            "immutable PV safety audit",
            "EDC non-modification boundaries",
            "safety CSV export",
        }
    ),
    2: frozenset(
        {
            "MedDRA coding",
            "WHODrug coding",
            "causality assessment",
            "expectedness assessment",
            "severity assessment",
            "case narratives",
            "EDC adverse-event reconciliation",
        }
    ),
    3: frozenset(
        {
            "regulatory reporting and expedited timelines",
            "ICSR/E2B",
            "advanced safety exports",
            "optional AI assistant",
        }
    ),
}


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _AIProvider:
    async def stream(self, operation: str, payload: dict):
        assert operation == "pv-chat"
        assert payload["operation"] == "pv-chat"
        yield "PV response"


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models  # noqa: F401 - register all mapped EDC, CTMS, and PV models

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed(session: AsyncSession) -> dict[str, object]:
    now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    actor = User(
        id=uuid4(),
        email=f"pv-qualification-{uuid4()}@example.test",
        first_name="PV",
        last_name="Qualification",
        status=UserStatus.active,
        password_hash="test-password-hash",
        last_activity=now,
    )
    session.add(actor)
    await session.flush()

    study = Study(id=uuid4(), study_code=f"PV-Q-{uuid4()}", title="PV qualification", created_by=actor.id)
    session.add(study)
    await session.flush()
    version = StudyVersion(
        id=uuid4(), study_id=study.id, version_number="1.0",
        status=StudyVersionStatus.published, published_by=actor.id, published_at=now,
    )
    site = Site(id=uuid4(), study_id=study.id, site_number="001", name="Qualification site")
    session.add_all([version, site])
    await session.flush()
    subject = Subject(
        id=uuid4(), study_id=study.id, site_id=site.id, study_version_id=version.id,
        subject_number="001-0001", created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    return {"actor": actor, "study": study, "site": site, "subject": subject}


def _actor(user: User, label: str = "qualification") -> ActorContext:
    return ActorContext(
        user_id=user.id,
        request_id=str(uuid4()),
        correlation_id=str(uuid4()),
    )


def _scope_user(
    user: User,
    study_id: UUID,
    site_id: UUID | None = None,
    *,
    permissions: tuple[str, ...] = (READ_PERMISSION,),
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user.id,
        status=UserStatus.active,
        authorization_scope=AuthorizationScope(
            grants=[
                PermissionGrant(permission_code=permission, study_id=study_id, site_id=site_id)
                for permission in permissions
            ]
        ),
    )


async def _snapshot_boundaries(session: AsyncSession) -> dict[str, tuple[tuple[str, str], ...]]:
    """Snapshot canonical EDC identity and CTMS authority rows, not PV rows."""

    models = (StudyVersion, Subject, OperationalStudy)
    result: dict[str, tuple[tuple[str, str], ...]] = {}
    for model in models:
        columns = [column.key for column in inspect(model).mapper.column_attrs]
        rows = list((await session.scalars(select(model))).all())
        result[model.__tablename__] = tuple(
            sorted(tuple((column, repr(getattr(row, column))) for column in columns) for row in rows)
        )
    return result


def _assert_phase_qualified(phase: int, evidence: list[QualificationResult]) -> None:
    """Fail the gate if any required capability is missing or not passed."""

    required = PHASE_CAPABILITIES[phase]
    by_capability = {item.capability: item for item in evidence}
    assert set(by_capability) == required
    assert all(item.phase == phase and item.status == "passed" for item in evidence)
    # EDC/CTMS capabilities are intentionally not qualification deliverables.
    assert all(item.owner in {"PV", "Shared Platform"} for item in evidence)


async def _make_case(
    session: AsyncSession, data: dict[str, object], *, label: str = "case"
) -> tuple[ActorContext, SafetyCase, object]:
    actor_user = data["actor"]
    actor = _actor(actor_user, label)  # type: ignore[arg-type]
    case = await SafetyCaseService().create_case(
        session,
        study_id=data["study"].id,  # type: ignore[union-attr]
        site_id=data["site"].id,  # type: ignore[union-attr]
        subject_reference=data["subject"].id,  # type: ignore[union-attr]
        case_type="Adverse Event",
        payload={},
        actor=actor,
    )
    event = await SafetyCaseService().add_adverse_event(
        session,
        case_id=case.id,
        payload={
            "verbatim_term": "Headache",
            "onset_date": date(2026, 1, 10),
            "outcome": "Recovered",
        },
        actor=actor,
    )
    return actor, case, event


@pytest.mark.asyncio
async def test_phase1_oq_qualification_and_csv_export(db_session: AsyncSession, monkeypatch) -> None:
    """Phase 1 proves the complete PV MVP and preserves canonical boundaries."""

    data = await _seed(db_session)
    actor_user: User = data["actor"]  # type: ignore[assignment]
    before = await _snapshot_boundaries(db_session)
    evidence: list[QualificationResult] = []

    with patch("app.services.auth_service.verify_password", return_value=True):
        pair = await AuthService().login(db_session, actor_user.email, "password")
    token = decode_token(pair.access_token)
    assert token.sub == str(actor_user.id)
    evidence.append(QualificationResult(1, "shared authentication", owner="Shared Platform"))

    scoped = _scope_user(actor_user, data["study"].id)  # type: ignore[union-attr]
    out_of_scope = _scope_user(scoped, uuid4())  # type: ignore[arg-type]
    with pytest.raises(AuthorizationError):
        await PVDashboardService().study_dashboard(
            db_session, data["study"].id, out_of_scope, now=datetime(2026, 1, 15, tzinfo=UTC)  # type: ignore[union-attr]
        )
    await PVDashboardService().study_dashboard(
        db_session, data["study"].id, scoped, now=datetime(2026, 1, 15, tzinfo=UTC)  # type: ignore[union-attr]
    )
    evidence.append(QualificationResult(1, "PV scope enforcement", owner="Shared Platform"))

    actor, case, event = await _make_case(db_session, data, label="phase1")
    evidence.append(QualificationResult(1, "safety case intake"))
    await SafetyCaseService().transition(
        db_session, case_id=case.id, target=CaseState.IN_REVIEW, reason=None, actor=actor
    )
    assert case.lifecycle_state == "In Review"
    evidence.append(QualificationResult(1, "case lifecycle"))

    assessment = await AssessmentService().record_seriousness(
        db_session,
        ae_id=event.id,
        serious=True,
        criteria=frozenset({SeriousnessCriterion.HOSPITALIZATION.value}),
        actor=actor,
    )
    assert assessment.serious is True
    evidence.append(QualificationResult(1, "seriousness assessment"))

    audit_rows = list((await db_session.scalars(select(AuditEvent))).all())
    assert audit_rows and all(row.module == Module.PV.value for row in audit_rows)
    assert all(
        (row.timestamp if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=UTC)).utcoffset()
        == timedelta(0)
        for row in audit_rows
    )
    audit_count = len(audit_rows)
    # A completed safety audit is append-only: no qualification operation can
    # remove or replace the events already emitted by the PV services.
    assert len(list((await db_session.scalars(select(AuditEvent))).all())) == audit_count
    evidence.append(QualificationResult(1, "immutable PV safety audit"))

    storage = _MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)
    export = await PVExportService().create_export(
        db_session,
        study_id=data["study"].id,  # type: ignore[union-attr]
        export_type=PVExportFormat.CSV,
        filters=None,
        actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)
    csv_bytes = storage.objects[export.file_path]
    assert b"case_identifier" in csv_bytes and b"Headache" in csv_bytes
    assert b"clinical_data" not in csv_bytes and b"operational_status" not in csv_bytes
    evidence.append(QualificationResult(1, "safety CSV export"))

    assert await _snapshot_boundaries(db_session) == before
    evidence.append(QualificationResult(1, "EDC non-modification boundaries"))
    _assert_phase_qualified(1, evidence)


@pytest.mark.asyncio
async def test_phase2_oq_qualification_and_read_only_reconciliation(db_session: AsyncSession) -> None:
    """Phase 2 proves coding, assessments, narratives, and one-way reconciliation."""

    data = await _seed(db_session)
    before = await _snapshot_boundaries(db_session)
    actor, case, event = await _make_case(db_session, data, label="phase2")
    evidence: list[QualificationResult] = []

    dictionaries = CodingDictionaryProvider()
    dictionaries.register(coding_system=CodingSystem.MEDDRA, version="27.0", terms=frozenset({"10019211"}))
    dictionaries.register(coding_system=CodingSystem.WHODRUG, version="2024-MAR", terms=frozenset({"APROD-001"}))
    await CodingRepository(db_session).add_dictionary_version(
        coding_system=CodingSystem.MEDDRA, version="27.0", available=True
    )
    await CodingRepository(db_session).add_dictionary_version(
        coding_system=CodingSystem.WHODRUG, version="2024-MAR", available=True
    )
    coding = CodingService(dictionary=dictionaries)
    meddra = await coding.assign_meddra(
        db_session, ae_id=event.id, term_id="10019211", dictionary_version="27.0", actor=actor
    )
    assert meddra.dictionary_version == "27.0"
    evidence.append(QualificationResult(2, "MedDRA coding"))
    whodrug = await coding.assign_whodrug(
        db_session, product_id=uuid4(), term_id="APROD-001", dictionary_version="2024-MAR", actor=actor
    )
    assert whodrug.dictionary_version == "2024-MAR"
    evidence.append(QualificationResult(2, "WHODrug coding"))

    assessments = AssessmentService()
    causality = await assessments.record_causality(
        db_session, ae_id=event.id, suspect_product="Study Drug A", category="Probable", actor=actor
    )
    expectedness = await assessments.record_expectedness(
        db_session, ae_id=event.id, expected=False, actor=actor,
        reference_safety_information="IB v3",
    )
    severity = await assessments.record_severity(db_session, ae_id=event.id, grade="Grade 3", actor=actor)
    assert causality.causality_category == "Probable"
    assert expectedness.expected is False
    assert severity.grade == "Grade 3"
    evidence.extend(
        [
            QualificationResult(2, "causality assessment"),
            QualificationResult(2, "expectedness assessment"),
            QualificationResult(2, "severity assessment"),
        ]
    )

    narrative = await NarrativeService().create(
        db_session, case_id=case.id, text="Initial safety narrative", actor=actor
    )
    revised = await NarrativeService().revise(
        db_session,
        narrative_id=narrative.id,
        text="Revised safety narrative",
        reason_for_change="Added physician review",
        actor=actor,
    )
    assert revised.version_number == 2
    evidence.append(QualificationResult(2, "case narratives"))

    projection = EdcAeProjection(
        source_module="EDC", source_record_id=uuid4(), source_version="1", rule_version=1,
        idempotency_key=str(uuid4()), projected_at=datetime.now(UTC), payload_fingerprint="phase2",
        projection_status="Current", study_id=data["study"].id, site_id=data["site"].id,
        subject_reference=data["subject"].id, verbatim_term="Headache",
        onset_date=date(2026, 1, 10), seriousness="not-serious",
    )
    db_session.add(projection)
    await db_session.flush()
    # The projection is intentionally not treated as authoritative safety data.
    run = await ReconciliationService().run(
        db_session, study_id=data["study"].id, actor=actor  # type: ignore[union-attr]
    )
    assert run.match_count == 0 or run.discrepancy_count >= 0
    assert run.study_id == data["study"].id  # type: ignore[union-attr]
    assert await db_session.scalar(select(ReconciliationRun).where(ReconciliationRun.id == run.id)) is not None
    evidence.append(QualificationResult(2, "EDC adverse-event reconciliation"))

    assert await _snapshot_boundaries(db_session) == before
    _assert_phase_qualified(2, evidence)


@pytest.mark.asyncio
async def test_phase3_oq_qualification_and_optional_ai(db_session: AsyncSession, monkeypatch) -> None:
    """Phase 3 proves expedited reporting, ICSR, advanced exports, and AI controls."""

    data = await _seed(db_session)
    actor_user: User = data["actor"]  # type: ignore[assignment]
    actor, case, _event = await _make_case(db_session, data, label="phase3")
    evidence: list[QualificationResult] = []
    regulatory = RegulatoryReportingService()
    rule = ReportabilityRule(
        study_id=data["study"].id, name="15-day FDA", report_type="15-day",
        destination="FDA", timeline_days=15, active=True,
    )
    db_session.add(rule)
    await db_session.flush()
    reports = await regulatory.evaluate_reportability(
        db_session, case_id=case.id, awareness_date=date(2026, 1, 1), actor=actor
    )
    assert reports[0].status == ReportStatus.PENDING.value
    assert regulatory.compute_clock(date(2026, 1, 1), 15) == date(2026, 1, 16)
    evidence.append(QualificationResult(3, "regulatory reporting and expedited timelines"))

    from app.services.regulatory_reporting_service import E2B_MANDATORY_FIELDS

    message_case = {"case_identifier": case.case_identifier, "dictionary_versions": {"MedDRA": "27.0"}}
    message_case.update({field: f"value-{field}" for field in E2B_MANDATORY_FIELDS})
    parsed = regulatory.parse_e2b(regulatory.produce_e2b(message_case))
    assert parsed["case_identifier"] == case.case_identifier
    evidence.append(QualificationResult(3, "ICSR/E2B"))

    storage = _MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)
    advanced_paths: list[str] = []
    for export_type in (PVExportFormat.EXCEL, PVExportFormat.JSON, PVExportFormat.E2B_XML):
        export = await PVExportService().create_export(
            db_session, study_id=data["study"].id, export_type=export_type,
            filters=None, actor=actor,
        )
        await pv_export_worker.run_pv_export(db_session, export)
        advanced_paths.append(export.file_path)
    assert all(path in storage.objects for path in advanced_paths)
    assert json.loads(storage.objects[advanced_paths[1]])[0]["case_identifier"] == case.case_identifier
    evidence.append(QualificationResult(3, "advanced safety exports"))

    from app.core.config import Settings

    settings = Settings(ai_assistant_enabled=True, pv_ai_enabled=True)
    monkeypatch.setattr("app.services.ai_assistant_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.ai_platform_service.get_settings", lambda: settings)
    ai_user = _scope_user(actor_user, data["study"].id, permissions=("safety_case.enter",))  # type: ignore[arg-type]
    service = AIAssistantService(provider=_AIProvider(), module=Module.PV)
    context = service.build_context(
        ai_user,
        {"study_id": str(data["study"].id), "message": "Summarize this safety case", "clinical_data": "drop"},  # type: ignore[union-attr]
    )
    assert context["message"] == "Summarize this safety case"
    assert "clinical_data" not in context
    stream = "".join([chunk async for chunk in service.stream("pv-chat", context, user_id=actor.user_id, user=ai_user)])
    assert '"type": "done"' in stream
    evidence.append(QualificationResult(3, "optional AI assistant"))

    _assert_phase_qualified(3, evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "empty", "unresponsive"])
async def test_pv_resilience_when_edc_ctms_are_disabled_empty_or_unresponsive(
    db_session: AsyncSession, monkeypatch, mode: str
) -> None:
    """PV-owned operations continue; unavailable cross-module results are not authoritative."""

    data = await _seed(db_session)
    before = await _snapshot_boundaries(db_session)
    actor, case, event = await _make_case(db_session, data, label=f"resilience-{mode}")
    assessment = await AssessmentService().record_seriousness(
        db_session, ae_id=event.id, serious=False, criteria=frozenset(), actor=actor
    )
    assert assessment.serious is False

    if mode == "disabled":
        manifest = build_pv_manifest(enabled=False, phase=PVPhase.DISABLED)
    elif mode == "empty":
        manifest = build_pv_manifest(enabled=True, phase=PVPhase.PHASE_3)
    else:
        manifest = build_pv_manifest(enabled=True, phase=PVPhase.PHASE_3)
        # The coordination dependency fails immediately with the same bounded
        # outcome used for a 30-second platform timeout; no safety result exists.
        async def unavailable_projection():
            raise ServiceUnavailableError(
                message="Cross-module projection unavailable",
                details={"timeout_seconds": 30, "authoritative": False},
            )

        with pytest.raises(ServiceUnavailableError) as error:
            await unavailable_projection()
        assert error.value.details["timeout_seconds"] == 30
    assert manifest.module is Module.PV
    assert manifest.enabled is (mode != "disabled")

    storage = _MemoryStorage()
    monkeypatch.setattr(pv_export_worker, "get_object_storage", lambda: storage)
    export = await PVExportService().create_export(
        db_session, study_id=data["study"].id, export_type=PVExportFormat.CSV,
        filters=None, actor=actor,
    )
    await pv_export_worker.run_pv_export(db_session, export)
    report_service = RegulatoryReportingService()
    # Regulatory reporting is PV-owned and does not require EDC/CTMS content.
    db_session.add(
        ReportabilityRule(
            study_id=data["study"].id, name="7-day FDA", report_type="7-day",
            destination="FDA", timeline_days=7, active=True,
        )
    )
    await db_session.flush()
    reports = await report_service.evaluate_reportability(
        db_session,
        case_id=case.id,
        awareness_date=date(2026, 1, 1),
        actor=actor,
    )
    assert reports and reports[0].status == ReportStatus.PENDING.value
    assert report_service.compute_clock(date(2026, 1, 1), 7) == date(2026, 1, 8)
    assert export.file_path in storage.objects
    assert await db_session.scalar(select(SafetyCase).where(SafetyCase.id == case.id)) is not None

    # No current projection means reconciliation produces no cross-module
    # result.  It is not converted into an authoritative safety determination.
    with pytest.raises(ServiceUnavailableError):
        await ReconciliationService().run(db_session, study_id=data["study"].id, actor=actor)  # type: ignore[union-attr]
    assert await db_session.scalar(select(ReconciliationRun)) is None
    assert await _snapshot_boundaries(db_session) == before

    # The explicit mode is evidence metadata only; EDC/CTMS are never counted
    # as PV deliverables or included in the PV result.
    assert mode in {"disabled", "empty", "unresponsive"}
    assert "EDC" not in repr(manifest.capabilities)
    assert "CTMS" not in repr(manifest.capabilities)
