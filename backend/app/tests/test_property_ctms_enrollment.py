"""Property-based verification of CTMS enrollment authority boundaries.

**Validates: Requirements 5.1-5.15, 8.2-8.4, 8.10, 14.5**

Property 6: Enrollment operations never duplicate or replace clinical subjects.

The generated scenarios use a deterministic in-memory session.  No database,
worker, network, or other external service is used: the service under test
still performs its real canonical identity and ownership checks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.ctms.enrollment import (
    EnrollmentTargetStatus,
    EnrollmentTargetType,
    OperationalMilestone,
    OperationalSubjectStatus,
)
from app.models.site import Site
from app.models.study import Study
from app.models.subject import Subject, SubjectStatus
from app.schemas.ctms.enrollment import EnrollmentTargetCreate, OperationalMilestoneCreate
from app.services.ctms_ownership_guard import CTMSOwnershipError, assert_ctms_command_safe
from app.services.enrollment_service import EnrollmentService


class _Rows:
    """Minimal SQLAlchemy result facade for the in-memory session."""

    def __init__(self, rows: list[object]):
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _InMemorySession:
    """Deterministic async repository fake keyed by the selected ORM model."""

    def __init__(self, records: dict[type[object], list[object]]):
        self.records = records
        self.added: list[object] = []

    async def execute(self, statement):
        model = statement.column_descriptions[0]["entity"]
        return _Rows(self.records.get(model, []))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


_NONZERO_UUID = st.integers(min_value=1, max_value=2**128 - 1).map(
    lambda value: UUID(int=value)
)
_TOKEN = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=18,
)
_TARGET_DIMENSION = st.dictionaries(
    keys=st.sampled_from(["cohort", "region", "planning_period"]),
    values=_TOKEN,
    max_size=3,
)
_PROHIBITED_CLINICAL_FIELD = st.sampled_from(
    [
        "clinical_data",
        "source_document",
        "subject_number",
        "visit_instance",
        "form_instance",
        "field_values",
        "query_message",
    ]
)

_TARGET_TRANSITIONS: dict[EnrollmentTargetStatus, set[EnrollmentTargetStatus]] = {
    EnrollmentTargetStatus.draft: {
        EnrollmentTargetStatus.active,
        EnrollmentTargetStatus.cancelled,
    },
    EnrollmentTargetStatus.active: {
        EnrollmentTargetStatus.met,
        EnrollmentTargetStatus.expired,
        EnrollmentTargetStatus.cancelled,
    },
    EnrollmentTargetStatus.met: set(),
    EnrollmentTargetStatus.expired: set(),
    EnrollmentTargetStatus.cancelled: set(),
}


@st.composite
def enrollment_scenarios(draw: st.DrawFn) -> dict[str, object]:
    """Generate one complete target, subject, reference, and rule scenario."""

    return {
        "study_id": draw(_NONZERO_UUID),
        "site_id": draw(_NONZERO_UUID),
        "subject_id": draw(_NONZERO_UUID),
        "actor_id": draw(_NONZERO_UUID),
        "target_type": draw(st.sampled_from(list(EnrollmentTargetType))),
        "target_quantity": draw(st.integers(min_value=1, max_value=500)),
        "target_dimension": draw(_TARGET_DIMENSION),
        "target_initial_status": draw(st.sampled_from(list(EnrollmentTargetStatus))),
        "target_next_status": draw(st.sampled_from(list(EnrollmentTargetStatus))),
        "subject_status": draw(st.sampled_from(list(SubjectStatus))),
        "milestone_status": draw(st.sampled_from(list(OperationalSubjectStatus))),
        "approved_pseudonym": draw(st.one_of(st.none(), _TOKEN)),
        "reference_mode": draw(st.sampled_from(["valid", "unknown", "wrong_scope", "ambiguous"])),
        "projection_configured": draw(st.booleans()),
        "projection_active": draw(st.booleans()),
        "projection_status": draw(st.sampled_from(list(OperationalSubjectStatus))),
        "rule_version": draw(st.integers(min_value=1, max_value=20)),
        "prohibited_field": draw(_PROHIBITED_CLINICAL_FIELD),
    }


def _make_records(scenario: dict[str, object], *, reference_mode: str) -> tuple[Study, Site, Subject, dict]:
    """Build canonical EDC records and the requested reference variant."""

    study_id = scenario["study_id"]
    site_id = scenario["site_id"]
    subject_id = scenario["subject_id"]
    actor_id = scenario["actor_id"]
    study = Study(id=study_id, study_code="PROPERTY-STUDY", title="Property Study", created_by=actor_id)
    site = Site(id=site_id, study_id=study_id, site_number="001", name="Property Site")
    subject = Subject(
        id=subject_id,
        study_id=study_id,
        site_id=site_id,
        study_version_id=uuid4(),
        subject_number="001-0001",
        status=scenario["subject_status"],
        created_by=actor_id,
    )

    if reference_mode == "unknown":
        subjects: list[Subject] = []
    elif reference_mode == "ambiguous":
        subjects = [subject, subject]
    elif reference_mode == "wrong_scope":
        subject.site_id = uuid4()
        subjects = [subject]
    else:
        subjects = [subject]

    records = {Study: [study], Site: [site], Subject: subjects}
    return study, site, subject, records


def _clinical_snapshot(subject: Subject) -> tuple[object, ...]:
    """Capture all EDC-owned subject fields touched by the property boundary."""

    return (
        subject.id,
        subject.study_id,
        subject.site_id,
        subject.study_version_id,
        subject.subject_number,
        subject.status,
        subject.deleted_at,
    )


def _target_data(scenario: dict[str, object]) -> EnrollmentTargetCreate:
    return EnrollmentTargetCreate(
        study_id=scenario["study_id"],
        site_id=scenario["site_id"],
        target_type=scenario["target_type"],
        target_quantity=scenario["target_quantity"],
        planning_period_start=datetime(2025, 1, 1, tzinfo=UTC),
        planning_period_end=datetime(2025, 12, 31, tzinfo=UTC),
        dimension=scenario["target_dimension"],
        status=scenario["target_initial_status"],
    )


def _milestone_data(scenario: dict[str, object]) -> OperationalMilestoneCreate:
    return OperationalMilestoneCreate(
        study_id=scenario["study_id"],
        site_id=scenario["site_id"],
        subject_id=scenario["subject_id"],
        approved_pseudonym=scenario["approved_pseudonym"],
        milestone_type="Enrollment milestone",
        milestone_date=datetime(2025, 2, 1, tzinfo=UTC),
        status=scenario["milestone_status"],
    )


@given(scenario=enrollment_scenarios())
@settings(max_examples=100, deadline=None)
@pytest.mark.asyncio
async def test_enrollment_preserves_clinical_authority_and_minimizes_projections(
    scenario: dict[str, object],
):
    """Targets and milestones stay operational while EDC identity stays unchanged.

    **Validates: Requirements 5.1-5.15, 8.2-8.4, 8.10, 14.5**

    For every generated target dimension/status and canonical-reference case,
    the target lifecycle is enforced, invalid references have no CTMS mutation,
    and valid milestones never add or mutate an EDC Subject.  Withdrawn EDC
    subjects may only receive a Withdrawn operational status.  Projection
    events exist only for active explicit rules and contain the minimized
    subject/status allowlist.
    """

    study, site, subject, records = _make_records(
        scenario, reference_mode=scenario["reference_mode"]
    )
    actor_id = scenario["actor_id"]

    # Enrollment target lifecycle and operational dimensions.
    target_session = _InMemorySession(records)
    service = EnrollmentService()
    target = await service.create_enrollment_target(
        target_session,
        _target_data(scenario),
        actor_id,
        correlation_id=str(uuid4()),
    )
    assert target.study_id == study.id
    assert target.site_id == site.id
    assert target.target_type is scenario["target_type"]
    assert target.target_quantity == scenario["target_quantity"]
    assert target.dimension == scenario["target_dimension"]
    assert target.status is scenario["target_initial_status"]

    original_target_status = target.status
    next_status = scenario["target_next_status"]
    if next_status in _TARGET_TRANSITIONS[original_target_status]:
        await service.transition_target_status(
            target_session,
            target,
            next_status,
            actor_id,
            reason="property transition",
        )
        assert target.status is next_status
    else:
        with pytest.raises(BusinessRuleError):
            await service.transition_target_status(
                target_session,
                target,
                next_status,
                actor_id,
                reason="property transition",
            )
        assert target.status is original_target_status

    # Operational milestone validation is isolated from the target operation,
    # making the no-mutation assertion precise for every reference outcome.
    milestone_session = _InMemorySession(records)
    clinical_before = _clinical_snapshot(subject)
    reference_mode = scenario["reference_mode"]
    subject_status = scenario["subject_status"]
    requested_status = scenario["milestone_status"]
    if reference_mode == "valid" and not (
        subject_status is SubjectStatus.withdrawn
        and requested_status is not OperationalSubjectStatus.withdrawn
    ):
        milestone = await service.record_operational_milestone(
            milestone_session,
            _milestone_data(scenario),
            actor_id,
            correlation_id=str(uuid4()),
        )
        assert milestone.subject_id == subject.id
        assert milestone.approved_pseudonym == scenario["approved_pseudonym"]
        assert any(isinstance(item, OperationalMilestone) for item in milestone_session.added)
    else:
        expected_errors = (NotFoundError, ConflictError)
        with pytest.raises(expected_errors):
            await service.record_operational_milestone(
                milestone_session,
                _milestone_data(scenario),
                actor_id,
                correlation_id=str(uuid4()),
            )
        assert not any(isinstance(item, OperationalMilestone) for item in milestone_session.added)

    assert _clinical_snapshot(subject) == clinical_before
    assert not any(isinstance(item, Subject) for item in milestone_session.added)

    # Extra clinical payloads are rejected before a CTMS record can be built,
    # and the ownership guard independently rejects the same prohibited field.
    prohibited_field = scenario["prohibited_field"]
    protected_payload = {
        **_milestone_data(scenario).model_dump(mode="json"),
        prohibited_field: {"value": "clinical-secret"},
    }
    with pytest.raises(PydanticValidationError):
        OperationalMilestoneCreate.model_validate(protected_payload)
    with pytest.raises(CTMSOwnershipError):
        assert_ctms_command_safe(
            {prohibited_field: {"value": "clinical-secret"}},
            operation="record_operational_milestone",
        )

    # Projection tests use a fresh, unambiguous canonical subject regardless of
    # the milestone reference case above.
    projection_study, projection_site, projection_subject, projection_records = _make_records(
        scenario, reference_mode="valid"
    )
    projection_session = _InMemorySession(projection_records)
    projection_service = EnrollmentService()
    source_status = scenario["subject_status"].value
    if scenario["projection_configured"]:
        projection_service.configure_status_projection(
            source_status,
            scenario["projection_status"].value,
            rule_version=scenario["rule_version"],
            active=scenario["projection_active"],
        )

    source_version = "edc-property-v1"
    projection_clinical_before = _clinical_snapshot(projection_subject)
    event = await projection_service.project_edc_subject_status(
        projection_session,
        projection_subject.id,
        source_status,
        approved_pseudonym=scenario["approved_pseudonym"],
        source_version=source_version,
        correlation_id=str(uuid4()),
    )
    projection_expected = scenario["projection_configured"] and scenario["projection_active"]
    if not projection_expected:
        assert event is None
        assert not projection_session.added
    else:
        assert event is not None
        assert event.payload_json == {
            "subject_id": str(projection_subject.id),
            "approved_pseudonym": scenario["approved_pseudonym"],
            "status": scenario["projection_status"].value,
            "source_version": source_version,
            "rule_version": scenario["rule_version"],
        }
        assert set(event.payload_json) <= {
            "subject_id",
            "approved_pseudonym",
            "status",
            "source_version",
            "rule_version",
        }

    assert _clinical_snapshot(projection_subject) == projection_clinical_before
    assert projection_study.id == scenario["study_id"]
    assert projection_site.id == scenario["site_id"]
    assert not any(isinstance(item, Subject) for item in projection_session.added)
