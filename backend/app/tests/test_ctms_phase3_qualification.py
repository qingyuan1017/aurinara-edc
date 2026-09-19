"""Phase 3 CTMS recovery, privacy, and production qualification gate.

Feature: ctms-integration, Task 7.3
Validates: Requirements 8.3-8.12, 9.10-9.18, 12.8-12.15,
13.1-13.16, 14.3-14.10

The suite composes the Phase 3 boundaries instead of duplicating the focused
property tests.  It uses SQLite and deterministic in-memory storage so no
external queue, object store, backup provider, or EDC service is required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.ctms import CTMSPhase, Module, build_ctms_manifest
from app.core.database import Base
from app.core.exceptions import AuthorizationError, ServiceUnavailableError
from app.core.metrics import get_metrics
from app.models.audit import AuditEvent
from app.models.ctms.coordination import CoordinationEventLog, CTMSOutbox
from app.models.ctms.operational_study import OperationalStudy
from app.models.ctms.projection import ProjectionStatus
from app.models.ctms.retention import CTMSCoordinationConflict, CTMSFailedEvent
from app.models.ctms.work import OperationalTask
from app.models.export import Export
from app.models.file_attachment import FileAttachment
from app.models.identity import User, UserStatus
from app.models.query import Query, QueryMessage, QueryStatus, QueryTargetType
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject, SubjectStatus
from app.schemas.ctms.coordination import ConflictResolveRequest
from app.services.coordination_service import CoordinationService
from app.services.ctms_dashboard_service import CTMSDashboardService
from app.services.ctms_report_service import CTMSReportService
from app.services.ctms_retention_service import CTMSRetentionService
from app.services.export_service import ExportService
from app.services.file_attachment_service import FileAttachmentService
from app.services.query_service import QueryService
from app.services.status_ownership_rule_service import StatusOwnershipRuleService
from app.workers.ctms_export_worker import fetch_operational_rows
from app.workers.projection_rebuild_worker import ProjectionRebuildWorker


@pytest.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_metrics():
    get_metrics().reset()


async def _clinical_context(session: AsyncSession) -> tuple[User, Study, Site, Subject, Query]:
    actor = User(
        email=f"phase3-{uuid4()}@example.test",
        first_name="Phase",
        last_name="Three",
        status=UserStatus.active,
    )
    session.add(actor)
    await session.flush()
    study = Study(study_code=f"P3-{uuid4()}", title="Phase 3 qualification", created_by=actor.id)
    session.add(study)
    await session.flush()
    site = Site(study_id=study.id, site_number="P3-001", name="Qualification site")
    session.add(site)
    await session.flush()
    subject = Subject(
        study_id=study.id,
        site_id=site.id,
        study_version_id=uuid4(),
        subject_number="P3-001-001",
        status=SubjectStatus.enrolled,
        created_by=actor.id,
    )
    session.add(subject)
    await session.flush()
    query = Query(
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        target_type=QueryTargetType.subject.value,
        target_id=subject.id,
        query_type="system",
        text="Approved query summary",
        status=QueryStatus.open,
        created_by=actor.id,
        created_at=datetime(2026, 1, 10, tzinfo=UTC),
    )
    session.add(query)
    await session.flush()
    session.add(
        QueryMessage(
            query_id=query.id,
            author_id=actor.id,
            message="Unrestricted clinical message must never enter CTMS",
            created_at=datetime(2026, 1, 11, tzinfo=UTC),
        )
    )
    await session.flush()
    return actor, study, site, subject, query


class _MissingIdentity:
    async def resolve(self, *_args, **_kwargs):
        return None


class _ResolvedIdentity:
    async def resolve(self, *_args, **_kwargs):
        return object()


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        del content_type
        self.objects[key] = content

    async def get(self, key: str) -> bytes:
        self.reads.append(key)
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class _Upload:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.filename = "operational-evidence.txt"
        self.content_type = "text/plain"

    def read(self) -> bytes:
        return self.content


def _ctms_user(user_id, study_id, site_id):
    permission = SimpleNamespace(code="ctms.operational-data-read")
    management = SimpleNamespace(code="ctms.operational-study-management")
    role = SimpleNamespace(
        role_permissions=[SimpleNamespace(permission=permission), SimpleNamespace(permission=management)]
    )
    assignment = SimpleNamespace(role=role, study_id=study_id, site_id=site_id)
    return SimpleNamespace(id=user_id, status=UserStatus.active, user_roles=[assignment])


def _query_rule() -> dict[str, object]:
    return {
        "entity_type": "Query",
        "field_path": "status",
        "authoritative_module": Module.EDC,
        "writable_module": Module.EDC,
        "projection_target": Module.CTMS,
        "projection_type": "query_summary",
        "typed_allowlist": StatusOwnershipRuleService.default_allowlist("query_summary"),
        "allowed_transitions": {},
        "version": 1,
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "status": "active",
    }


def _quality_rule() -> dict[str, object]:
    return {
        "entity_type": "DataQualitySignal",
        "field_path": "signal",
        "authoritative_module": Module.EDC,
        "writable_module": Module.EDC,
        "projection_target": Module.CTMS,
        "projection_type": "data_quality_signal",
        "typed_allowlist": StatusOwnershipRuleService.default_allowlist("data_quality_signal"),
        "allowed_transitions": {},
        "version": 1,
        "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
        "status": "active",
    }


@pytest.mark.asyncio
async def test_phase3_query_summary_quality_signal_and_advanced_reports_are_scoped_and_minimized(
    db_session: AsyncSession,
):
    """Approved query summaries and quality signals remain read-only projections."""

    actor, study, site, subject, query = await _clinical_context(db_session)
    rebuild = ProjectionRebuildWorker()
    rebuilt = await rebuild.rebuild(
        db_session,
        study_id=study.id,
        site_id=site.id,
        projection_type="query_summary",
        source_module=Module.EDC,
        rule=_query_rule(),
        generation=uuid4(),
        correlation_id="phase3-query-rebuild",
    )
    projection = rebuilt.projections[0]
    assert projection.status == ProjectionStatus.CURRENT
    assert projection.query_id == query.id
    assert projection.payload_json["summary"] == "Approved query summary"
    assert "Unrestricted clinical message" not in repr(projection.payload_json)

    quality = await ProjectionRebuildWorker().projection_service.apply_projection(
        db_session,
        rule=_quality_rule(),
        projection_type="data_quality_signal",
        source_module=Module.EDC,
        source_record_id=uuid4(),
        payload={
            "study_id": study.id,
            "site_id": site.id,
            "signal_type": "Overdue Query Count",
            "value": 1,
            "numerator": 1,
            "denominator": 1,
            "source_watermark": "query-v1",
            "calculated_at": datetime(2026, 1, 15, tzinfo=UTC),
        },
        source_version="query-v1",
        source_timestamp=datetime(2026, 1, 15, tzinfo=UTC),
        correlation_id="phase3-quality-signal",
        study_id=study.id,
        site_id=site.id,
        query_id=query.id,
    )
    assert quality.applied is True
    dashboard = await CTMSDashboardService().study_dashboard(
        db_session, study.id, now=datetime(2026, 1, 16, tzinfo=UTC)
    )
    assert dashboard.projected_clinical[0]["read_only"] is True
    assert dashboard.projected_clinical[0]["signal_type"] == "Overdue Query Count"
    assert dashboard.projected_clinical[0]["source_module"] == Module.EDC.value

    db_session.add(
        OperationalTask(
            study_id=study.id,
            site_id=site.id,
            title="Resolve operational follow-up",
            status="Open",
            priority="High",
            due_date=datetime(2026, 1, 14, tzinfo=UTC),
            owner_id=actor.id,
            created_by=actor.id,
            correlation_id=uuid4(),
        )
    )
    await db_session.flush()
    report = await CTMSReportService().task_report(
        db_session,
        study.id,
        priority="High",
        due_date="overdue",
        now=datetime(2026, 1, 16, tzinfo=UTC),
    )
    assert report.totals["count"] == 1
    assert report.items[0]["operational_only"] is True
    assert str(subject.id) not in repr(report.items[0])


@pytest.mark.asyncio
async def test_phase3_retry_failed_event_conflict_resolution_replay_and_traceability(
    db_session: AsyncSession,
):
    """Recovery is bounded, sanitized, policy-aware, and correlation-traceable."""

    actor, study, site, _subject, _query = await _clinical_context(db_session)
    service = CoordinationService(identity_resolver=_MissingIdentity())
    event = await service.accept(
        db_session,
        event_type="QUERY_SUMMARY_PROJECTION",
        source_module=Module.EDC,
        target_module=Module.CTMS,
        entity_type="Query",
        source_record_id=uuid4(),
        source_version="1",
        rule_version=1,
        payload={"query_id": uuid4(), "summary": "approved"},
        idempotency_key="phase3-failed-event",
        correlation_id="phase3-recovery",
        target_projection_type="query_summary",
        study_id=study.id,
        site_id=site.id,
    )
    failed_result = await service.process(db_session, event_id=event.event_id, worker_id="phase3-worker")
    assert failed_result.outcome == "failed"
    failed = await db_session.scalar(select(CTMSFailedEvent).where(CTMSFailedEvent.event_id == event.event_id))
    assert failed is not None
    assert failed.reason_code == "RECORD_NOT_FOUND"
    assert "payload" not in repr(failed.sanitized_details_json).lower()

    retry_event = await CoordinationService().accept(
        db_session,
        event_type="QUERY_SUMMARY_PROJECTION",
        source_module=Module.EDC,
        target_module=Module.CTMS,
        entity_type="Query",
        source_record_id=uuid4(),
        source_version="1",
        rule_version=1,
        payload={"query_id": uuid4(), "summary": "approved"},
        idempotency_key="phase3-retry-event",
        correlation_id="phase3-retry",
        target_projection_type="query_summary",
        study_id=study.id,
    )
    retry_service = CoordinationService()
    retry_service._apply_target = AsyncMock(side_effect=ServiceUnavailableError())
    retry_result = await retry_service.process(
        db_session, event_id=retry_event.event_id, worker_id="phase3-worker"
    )
    assert retry_result.outcome == "retrying"
    retry_outbox = await db_session.scalar(select(CTMSOutbox).where(CTMSOutbox.event_id == retry_event.event_id))
    assert retry_outbox is not None
    assert retry_outbox.available_at > datetime.now(UTC) - timedelta(seconds=1)
    assert retry_event.attempt_count == 1

    conflict_event = await CoordinationService().accept(
        db_session,
        event_type="INVALID_TARGET",
        source_module=Module.EDC,
        target_module=Module.EDC,
        entity_type="Query",
        source_record_id=uuid4(),
        source_version="2",
        rule_version=1,
        payload={"query_id": uuid4(), "summary": "approved"},
        idempotency_key="phase3-conflict-event",
        correlation_id="phase3-conflict",
        target_projection_type="query_summary",
        study_id=study.id,
        site_id=site.id,
    )
    conflict_result = await CoordinationService().process(
        db_session, event_id=conflict_event.event_id, worker_id="phase3-worker"
    )
    assert conflict_result.outcome == "conflict"
    conflict = await db_session.scalar(
        select(CTMSCoordinationConflict).where(CTMSCoordinationConflict.event_id == conflict_event.event_id)
    )
    assert conflict is not None
    assert conflict.status == "open"
    assert "payload" not in repr(conflict.sanitized_details_json).lower()

    # Resolve through the same handler used by the authenticated API. Applying
    # the source requeues only the durable outbox row; it does not mutate EDC.
    from app.api.routes.ctms.coordination import resolve_coordination_conflict

    resolved = await resolve_coordination_conflict(
        conflict.id,
        ConflictResolveRequest(policy="apply_source", reason="Approved remediation"),
        db_session,
        actor,
    )
    assert resolved.status == "resolved"
    assert resolved.policy == "apply_source"
    refreshed_outbox = await db_session.scalar(
        select(CTMSOutbox).where(CTMSOutbox.event_id == conflict_event.event_id)
    )
    assert refreshed_outbox is not None and refreshed_outbox.status == "Pending"

    # Replay rechecks the current identity policy before changing event state.
    service.identity_resolver = _ResolvedIdentity()
    replay_actor = SimpleNamespace(
        id=actor.id,
        status=UserStatus.active,
        user_roles=[
            SimpleNamespace(
                role=SimpleNamespace(
                    role_permissions=[
                        SimpleNamespace(permission=SimpleNamespace(code="ctms.coordination-replay"))
                    ]
                ),
                study_id=study.id,
                site_id=site.id,
            )
        ],
    )
    replayed = await service.replay_failed_event(
        db_session,
        event_id=event.event_id,
        actor=replay_actor,
        reason="Current policy approved",
    )
    assert replayed.event_id == event.event_id
    assert event.status == "accepted"
    assert failed.sanitized_details_json == {"reason_code": "REPLAY_PENDING"}
    logs = (
        await db_session.scalars(select(CoordinationEventLog).where(CoordinationEventLog.correlation_id == "phase3-recovery"))
    ).all()
    assert logs and all(log.correlation_id == failed.correlation_id for log in logs)
    audit = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.correlation_id == "phase3-recovery"))
    ).all()
    assert audit
    assert all("payload" not in repr(row).lower() for row in [*logs, *audit, failed])


@pytest.mark.asyncio
async def test_phase3_export_attachment_health_and_edc_resilience_are_separated(
    db_session: AsyncSession,
):
    """Operational content stays separate while health and EDC remain usable."""

    actor, study, site, subject, query = await _clinical_context(db_session)
    task = OperationalTask(
        study_id=study.id,
        site_id=site.id,
        title="Operational export row",
        status="Open",
        priority="High",
        owner_id=actor.id,
        query_id=query.id,
        query_summary="Approved follow-up summary",
        created_by=actor.id,
        correlation_id=uuid4(),
    )
    db_session.add(task)
    clinical_attachment = FileAttachment(
        module="EDC",
        attachment_type="Clinical_Attachment",
        object_type="subject",
        object_id=subject.id,
        study_id=study.id,
        site_id=site.id,
        subject_id=subject.id,
        filename="clinical.pdf",
        content_type="application/pdf",
        size_bytes=6,
        storage_key="edc/clinical.pdf",
        uploaded_by=actor.id,
    )
    db_session.add(clinical_attachment)
    await db_session.flush()

    export = await ExportService().create_ctms_export(
        db_session,
        study_id=study.id,
        export_type="json",
        filters={"record_types": ["operational_task"], "page_size": 100},
        actor_id=actor.id,
        correlation_id="phase3-export",
    )
    rows = await fetch_operational_rows(db_session, export)
    assert rows and rows[0]["title"] == "Operational export row"
    assert "query_id" not in rows[0]
    assert "query_summary" not in rows[0]
    assert "clinical.pdf" not in repr(rows)

    storage = _MemoryStorage()
    attachment_service = FileAttachmentService(storage=storage)
    scoped_user = _ctms_user(actor.id, study.id, site.id)
    operational = await attachment_service.upload_operational(
        db_session,
        parent_type="operational_task",
        parent_id=task.id,
        study_id=study.id,
        site_id=site.id,
        file=_Upload(b"operational evidence"),
        actor_id=actor.id,
        user=scoped_user,
        correlation_id="phase3-attachment",
    )
    assert await attachment_service.download(db_session, operational, scoped_user) == b"operational evidence"
    with pytest.raises(AuthorizationError):
        await attachment_service.download(db_session, clinical_attachment, scoped_user)
    assert storage.reads == [operational.storage_key]

    from app.services.ctms_health_service import ctms_health_service

    ctms_health_service.set_worker_status("unavailable")
    get_metrics().record_ctms_projection(42)
    health = ctms_health_service.snapshot()
    assert health["worker_status"] == "unavailable"
    assert health["projection_lag_seconds"] == 42
    assert "clinical" not in repr(health).lower()

    # Disabling CTMS changes only its capability manifest.  The EDC query
    # lifecycle still performs a normal clinical mutation during worker outage.
    disabled = build_ctms_manifest(enabled=False, phase=CTMSPhase.DISABLED)
    assert disabled.enabled is False
    before = query.status
    await QueryService().close(db_session, query, actor.id)
    assert before == QueryStatus.open
    assert query.status == QueryStatus.closed
    ctms_health_service.set_worker_status("available")


@pytest.mark.asyncio
async def test_phase3_retention_restore_and_environment_recovery_controls_preserve_edc_rows(
    db_session: AsyncSession,
):
    """Retention/restore is auditable and configured recovery is isolated."""

    actor, study, _site, _subject, _query = await _clinical_context(db_session)
    now = datetime(2026, 2, 1, tzinfo=UTC)
    operational = OperationalStudy(
        study_id=study.id,
        status="Closed",
        created_by=actor.id,
        updated_by=actor.id,
        correlation_id=uuid4(),
        created_at=now - timedelta(days=30),
        updated_at=now - timedelta(days=30),
    )
    edc_export = Export(
        study_id=study.id,
        module="EDC",
        content_owner="EDC",
        export_type="json",
        status="Completed",
        requested_by=actor.id,
        created_at=now - timedelta(days=30),
    )
    db_session.add_all([operational, edc_export])
    await db_session.flush()
    retention = CTMSRetentionService(settings=Settings(retention_days=7))
    result = await retention.run(db_session, actor_id=actor.id, reason="Phase 3 retention", now=now)
    assert result.archived >= 1
    assert operational.retention_state == "archived"
    assert edc_export.retention_state == "active"

    await retention.restore(
        db_session,
        operational,
        actor_id=actor.id,
        reason="Qualification restore",
        now=now,
        resource="operational_study",
    )
    assert operational.retention_state == "active"
    assert operational.archived_at is None

    settings = Settings(
        environment="production",
        environment_namespace="phase3-production",
        object_storage_namespace="phase3-production-objects",
        backup_enabled=True,
        restore_enabled=True,
        backup_storage_uri="s3://phase3-backups",
    )
    metadata = settings.environment_metadata
    assert metadata["backup_enabled"] is True
    assert metadata["restore_enabled"] is True
    assert metadata["namespace"] != "local"
    assert metadata["object_storage_namespace"] == "phase3-production-objects"
    assert await db_session.scalar(select(OperationalStudy).where(OperationalStudy.id == operational.id)) is operational
    assert await db_session.scalar(select(func.count()).select_from(Export).where(Export.module == "EDC")) == 1
