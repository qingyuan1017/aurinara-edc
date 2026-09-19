"""Focused coverage for CTMS enrollment authority and clinical protection."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConflictError, NotFoundError
from app.models.ctms.enrollment import (
    EnrollmentTargetStatus,
    EnrollmentTargetType,
    OperationalSubjectStatus,
)
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject, SubjectStatus
from app.schemas.ctms.enrollment import EnrollmentTargetCreate, OperationalMilestoneCreate
from app.services.enrollment_service import EnrollmentService


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    """Small deterministic async session fake for service-level boundary tests."""

    def __init__(self, records):
        self.records = records
        self.added = []
        self.flush_count = 0

    async def execute(self, statement):
        model = statement.column_descriptions[0]["entity"]
        rows = self.records.get(model, [])
        return _Result(rows)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flush_count += 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


def _scope_records(study, site, subject):
    from app.models.audit import AuditEvent
    from app.models.ctms.coordination import CTMSOutbox
    from app.models.ctms.enrollment import EnrollmentTarget, OperationalMilestone

    return {
        Study: [study],
        Site: [site],
        Subject: [subject] if subject is not None else [],
        EnrollmentTarget: [],
        OperationalMilestone: [],
        AuditEvent: [],
        CTMSOutbox: [],
    }


def _records():
    study_id = uuid4()
    site_id = uuid4()
    subject_id = uuid4()
    actor_id = uuid4()
    study = Study(
        id=study_id, study_code="STUDY-1", title="Study", created_by=actor_id
    )
    site = Site(id=site_id, study_id=study_id, site_number="001", name="Site")
    subject = Subject(
        id=subject_id,
        study_id=study_id,
        site_id=site_id,
        study_version_id=uuid4(),
        subject_number="001-0001",
        status=SubjectStatus.enrolled,
        created_by=actor_id,
    )
    return study, site, subject, actor_id


def _target_data(study_id, site_id):
    return EnrollmentTargetCreate(
        study_id=study_id,
        site_id=site_id,
        target_type=EnrollmentTargetType.enrollment,
        target_quantity=25,
        planning_period_start=datetime(2025, 1, 1, tzinfo=UTC),
        planning_period_end=datetime(2025, 12, 31, tzinfo=UTC),
    )


def _milestone_data(study_id, site_id, subject_id, status=OperationalSubjectStatus.enrolled):
    return OperationalMilestoneCreate(
        study_id=study_id,
        site_id=site_id,
        subject_id=subject_id,
        approved_pseudonym="P-001",
        milestone_type="Enrollment milestone",
        milestone_date=datetime(2025, 2, 1, tzinfo=UTC),
        status=status,
    )


@pytest.mark.asyncio
async def test_target_persists_study_site_dimension_and_target_lifecycle():
    study, site, subject, actor_id = _records()
    session = _Session(_scope_records(study, site, subject))
    service = EnrollmentService()

    target = await service.create_enrollment_target(
        session, _target_data(study.id, site.id), actor_id, correlation_id="corr-target"
    )

    assert target.study_id == study.id
    assert target.site_id == site.id
    assert target.target_type is EnrollmentTargetType.enrollment
    assert target.status is EnrollmentTargetStatus.draft
    assert target.target_quantity == 25
    assert target.id in {item.id for item in session.added if hasattr(item, "id")}

    await service.transition_target_status(
        session, target, EnrollmentTargetStatus.active, actor_id, reason="approved"
    )
    assert target.status is EnrollmentTargetStatus.active


@pytest.mark.asyncio
async def test_milestone_uses_canonical_subject_without_mutating_edc_subject():
    study, site, subject, actor_id = _records()
    session = _Session(_scope_records(study, site, subject))
    service = EnrollmentService()
    clinical_snapshot = (subject.id, subject.status, subject.subject_number, subject.study_version_id)

    milestone = await service.record_operational_milestone(
        session, _milestone_data(study.id, site.id, subject.id), actor_id
    )

    assert milestone.subject_id == subject.id
    assert milestone.approved_pseudonym == "P-001"
    assert (subject.id, subject.status, subject.subject_number, subject.study_version_id) == clinical_snapshot
    assert not any(isinstance(item, Subject) for item in session.added)


@pytest.mark.asyncio
async def test_unknown_subject_is_rejected_before_operational_mutation():
    study, site, _, actor_id = _records()
    session = _Session(_scope_records(study, site, None))
    service = EnrollmentService()
    data = _milestone_data(study.id, site.id, uuid4())

    with pytest.raises(NotFoundError) as error:
        await service.record_operational_milestone(session, data, actor_id)

    assert error.value.details["reason"] == "RECORD_NOT_FOUND"
    assert session.added == []


@pytest.mark.asyncio
async def test_withdrawn_subject_cannot_receive_non_withdrawn_operational_status():
    study, site, subject, actor_id = _records()
    subject.status = SubjectStatus.withdrawn
    session = _Session(_scope_records(study, site, subject))
    service = EnrollmentService()

    with pytest.raises(ConflictError) as error:
        await service.record_operational_milestone(
            session, _milestone_data(study.id, site.id, subject.id), actor_id
        )

    assert error.value.details["reason"] == "WITHDRAWN_SUBJECT_REFERENCE"
    assert session.added == []


def test_milestone_schema_rejects_clinical_fields():
    study, site, subject, _ = _records()
    with pytest.raises(PydanticValidationError):
        OperationalMilestoneCreate.model_validate(
            {
                **_milestone_data(study.id, site.id, subject.id).model_dump(),
                "clinical_data": {"value": "must not persist"},
            }
        )


@pytest.mark.asyncio
async def test_unconfigured_status_is_ctms_only_and_configured_projection_is_minimized():
    study, site, subject, _actor_id = _records()
    session = _Session(_scope_records(study, site, subject))
    service = EnrollmentService()

    assert (
        await service.project_edc_subject_status(
            session, subject.id, SubjectStatus.enrolled.value, approved_pseudonym="P-001"
        )
        is None
    )

    service.configure_status_projection(
        SubjectStatus.enrolled.value, OperationalSubjectStatus.enrolled.value, rule_version=3
    )
    event = await service.project_edc_subject_status(
        session,
        subject.id,
        SubjectStatus.enrolled.value,
        approved_pseudonym="P-001",
        source_version="edc-v4",
        correlation_id="corr-projection",
    )

    assert event is not None
    assert event.event_type == "EDC_SUBJECT_STATUS_PROJECTION"
    assert event.payload_json == {
        "subject_id": str(subject.id),
        "approved_pseudonym": "P-001",
        "status": "Enrolled",
        "source_version": "edc-v4",
        "rule_version": 3,
    }
    assert "subject_number" not in event.payload_json
    assert "clinical_data" not in event.payload_json
    assert not any(isinstance(item, Subject) for item in session.added)
