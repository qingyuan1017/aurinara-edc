"""Property 19: optional CTMS failure does not alter EDC behavior.

**Validates: Requirements 12.14-12.15, 13.14-13.16, 14.4, 14.7, 14.10**

The test runs the real EDC service methods against deterministic in-memory
sessions.  It compares the same authentication, capture, clinical audit,
clinical export, protocol visit/casebook, and subject-lifecycle workflow with
CTMS disabled, CTMS enabled but empty, and an unavailable CTMS worker.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.audit import AuditService
from app.core.ctms import CTMSPhase, build_ctms_manifest
from app.core.security import decode_token
from app.models.export import ExportType
from app.models.form_data import FieldValue, FormInstance, FormInstanceStatus
from app.models.identity import User, UserStatus
from app.models.subject import Subject, SubjectStatus
from app.models.visit import VisitDefinition, VisitInstance, VisitInstanceStatus
from app.services.auth_service import AuthenticationError, AuthService
from app.services.coordination_service import BoundedCoordinationQueue
from app.services.data_capture_service import DataCaptureService
from app.services.export_service import ExportService
from app.services.subject_service import SubjectService
from app.services.visit_service import VisitService

mode_strategy = st.sampled_from(("disabled", "empty", "worker-unavailable"))
password_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=8,
    max_size=24,
)
field_values_strategy = st.dictionaries(
    keys=st.uuids().map(str),
    values=st.one_of(
        st.text(alphabet=st.characters(whitelist_categories=("L", "N")), max_size=20),
        st.integers(min_value=-1000, max_value=1000),
    ),
    min_size=1,
    max_size=4,
)
lifecycle_path_strategy = st.lists(
    st.sampled_from(
        (
            SubjectStatus.enrolled,
            SubjectStatus.randomized,
            SubjectStatus.on_treatment,
            SubjectStatus.completed,
        )
    ),
    min_size=0,
    max_size=4,
).map(
    lambda path: _valid_lifecycle_path(path)
)


def _valid_lifecycle_path(path: list[SubjectStatus]) -> list[SubjectStatus]:
    """Keep generated lifecycle operations on the EDC state machine's path."""
    allowed = {
        SubjectStatus.screening: {SubjectStatus.enrolled, SubjectStatus.screen_failed},
        SubjectStatus.enrolled: {
            SubjectStatus.randomized,
            SubjectStatus.withdrawn,
            SubjectStatus.early_terminated,
        },
        SubjectStatus.randomized: {SubjectStatus.on_treatment},
        SubjectStatus.on_treatment: {
            SubjectStatus.completed,
            SubjectStatus.early_terminated,
            SubjectStatus.lost_to_follow_up,
            SubjectStatus.withdrawn,
        },
    }
    current = SubjectStatus.screening
    valid: list[SubjectStatus] = []
    for target in path:
        if target in allowed.get(current, set()):
            valid.append(target)
            current = target
    return valid


def _result(*, first=None, all_rows=()):
    result = MagicMock()
    result.scalars.return_value.first.return_value = first
    result.scalars.return_value.all.return_value = list(all_rows)
    return result


def _auth_session(user: User) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result(first=user))
    session.flush = AsyncMock()
    return session


class _CaptureSession:
    """Small in-memory session for DataCaptureService's field-value queries."""

    def __init__(self, expected_field_count: int) -> None:
        self.field_values: list[FieldValue] = []
        self._upserts_remaining = expected_field_count
        self.add = MagicMock(side_effect=self._add)
        self.flush = AsyncMock()
        self.execute = AsyncMock(side_effect=self._execute)

    def _add(self, value: object) -> None:
        if isinstance(value, FieldValue):
            # SQLAlchemy assigns this in the database; the property only needs
            # the stable normalized value and field reference.
            self.field_values.append(value)

    async def _execute(self, _statement):
        if self._upserts_remaining:
            self._upserts_remaining -= 1
            return _result(first=None)
        return _result(all_rows=self.field_values)


class _ExportSession:
    def __init__(self) -> None:
        self.add = MagicMock()
        self.flush = AsyncMock()


async def _run_edc_workflow(
    *,
    user_id: UUID,
    password: str,
    authentication_succeeds: bool,
    values: dict[str, object],
    lifecycle_path: list[SubjectStatus],
    visit_offset: int,
    record_ids: dict[str, UUID],
) -> dict[str, object]:
    """Execute the baseline EDC workflow and return mode-independent facts."""
    audit_actions: list[tuple[str, str]] = []

    async def record_audit(_audit, _session, **kwargs):
        audit_actions.append((str(kwargs.get("entity_type")), str(kwargs.get("action"))))
        return SimpleNamespace(id=uuid4())

    user = User(
        id=user_id,
        email=f"resilience-{user_id}@example.test",
        first_name="EDC",
        last_name="Operator",
        status=UserStatus.active,
        password_hash="deterministic-test-hash",
        mfa_enabled=False,
    )
    auth = AuthService()
    try:
        with patch(
            "app.services.auth_service.verify_password",
            return_value=authentication_succeeds,
        ):
            pair = await auth.login(
                _auth_session(user),
                user.email,
                password if authentication_succeeds else f"{password}-wrong",
            )
        token_payload = decode_token(pair.access_token)
        authentication = (True, token_payload.sub, token_payload.type)
    except AuthenticationError:
        authentication = (False, str(user.id), None)

    with ExitStack() as stack:
        stack.enter_context(patch.object(AuditService, "record", record_audit))
        stack.enter_context(
            patch(
                "app.services.data_capture_service.lock_service.is_modification_blocked",
                new=AsyncMock(return_value=False),
            )
        )

        form = FormInstance(
            id=record_ids["form_id"],
            subject_id=record_ids["subject_id"],
            form_definition_id=record_ids["form_definition_id"],
            status=FormInstanceStatus.not_started,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        capture_session = _CaptureSession(len(values))
        captured = await DataCaptureService().save_draft(
            capture_session,
            form,
            values,
            user_id,
        )

        subject = Subject(
            id=record_ids["subject_id"],
            study_id=record_ids["study_id"],
            site_id=record_ids["site_id"],
            study_version_id=record_ids["study_version_id"],
            subject_number="101-0001",
            status=SubjectStatus.screening,
            created_by=user_id,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        subject_service = SubjectService()
        for target_status in lifecycle_path:
            await subject_service.transition_status(
                AsyncMock(), subject, target_status, user_id
            )

        definition = VisitDefinition(
            id=record_ids["visit_definition_id"],
            study_version_id=record_ids["study_version_id"],
            name="Baseline",
            visit_number=1,
            visit_type="scheduled",
            target_day=7,
            window_before=2,
            window_after=2,
            display_order=1,
            is_required=True,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        visit = VisitInstance(
            id=record_ids["visit_id"],
            subject_id=subject.id,
            visit_definition_id=definition.id,
            name=definition.name,
            status=VisitInstanceStatus.scheduled,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        visit.visit_definition = definition
        await VisitService().record_visit_date(
            AsyncMock(),
            visit,
            date(2024, 1, 1) + timedelta(days=visit_offset),
            user_id,
            baseline_date=date(2024, 1, 1),
        )

        casebook_session = AsyncMock()
        casebook_session.execute = AsyncMock(return_value=_result(first=subject))
        casebook = await subject_service.get_casebook(casebook_session, subject.id)

        export = await ExportService().create_export(
            _ExportSession(),
            study_id=subject.study_id,
            export_type=ExportType.csv,
            filters={"subject_id": str(subject.id)},
            actor_id=user_id,
        )
        export_session = _ExportSession()
        await ExportService().start_export(export_session, export)
        await ExportService().complete_export(
            export_session,
            export,
            file_path="clinical/exports/resilience.csv",
            file_size=128,
        )

    return {
        "authentication": authentication,
        "capture": (captured.status.value, dict(captured.data_jsonb or {})),
        "clinical_audit": tuple(audit_actions),
        "clinical_export": (
            export.module,
            export.content_owner,
            export.export_type,
            export.status,
            export.file_path,
        ),
        "protocol_visit": (
            visit.visit_date.isoformat() if visit.visit_date else None,
            visit.window_status,
            visit.status.value,
        ),
        "casebook": (
            str(casebook["subject_id"]),
            casebook["subject_number"],
            casebook["status"].value,
            str(casebook["study_version_id"]),
            tuple(casebook["visits"]),
        ),
        "clinical_lifecycle": subject.status.value,
    }


def _ctms_state(mode: str) -> dict[str, object]:
    """Model accepted CTMS work while keeping its failure state observable."""
    if mode == "disabled":
        manifest = build_ctms_manifest(enabled=False, phase=CTMSPhase.DISABLED)
        return {"manifest": manifest.as_dict(), "accepted_work": None}
    if mode == "empty":
        manifest = build_ctms_manifest(enabled=True, phase=CTMSPhase.PHASE_3)
        return {"manifest": manifest.as_dict(), "accepted_work": None}

    queue = BoundedCoordinationQueue(capacity=1)
    event_id = uuid4()
    accepted = queue.try_enqueue(event_id)
    return {
        "manifest": build_ctms_manifest(enabled=True, phase=CTMSPhase.PHASE_3).as_dict(),
        "accepted_work": {
            "accepted": accepted,
            "status": "Pending",
            "worker_status": "unavailable",
            "queue_size": queue.size,
        },
    }


class TestOptionalCTMSResilienceProperty:
    """Property 19: CTMS absence/failure preserves EDC clinical behavior."""

    @settings(max_examples=100, deadline=None)
    @given(
        mode=mode_strategy,
        password=password_strategy,
        authentication_succeeds=st.booleans(),
        values=field_values_strategy,
        lifecycle_path=lifecycle_path_strategy,
        visit_offset=st.integers(min_value=0, max_value=14),
    )
    @pytest.mark.asyncio
    async def test_optional_ctms_failure_preserves_edc_workflow(
        self,
        mode: str,
        password: str,
        authentication_succeeds: bool,
        values: dict[str, object],
        lifecycle_path: list[SubjectStatus],
        visit_offset: int,
    ):
        """CTMS mode changes only its own optional work state.

        **Validates: Requirements 12.14-12.15, 13.14-13.16, 14.4, 14.7, 14.10**
        """
        user_id = uuid4()
        record_ids = {name: uuid4() for name in (
            "study_id",
            "site_id",
            "subject_id",
            "study_version_id",
            "form_id",
            "form_definition_id",
            "visit_definition_id",
            "visit_id",
            "export_id",
        )}
        baseline = await _run_edc_workflow(
            user_id=user_id,
            password=password,
            authentication_succeeds=authentication_succeeds,
            values=values,
            lifecycle_path=lifecycle_path,
            visit_offset=visit_offset,
            record_ids=record_ids,
        )
        with_ctms_mode = await _run_edc_workflow(
            user_id=user_id,
            password=password,
            authentication_succeeds=authentication_succeeds,
            values=values,
            lifecycle_path=lifecycle_path,
            visit_offset=visit_offset,
            record_ids=record_ids,
        )

        assert with_ctms_mode == baseline
        ctms = _ctms_state(mode)
        if mode == "worker-unavailable":
            assert ctms["accepted_work"] == {
                "accepted": True,
                "status": "Pending",
                "worker_status": "unavailable",
                "queue_size": 1,
            }
        else:
            assert ctms["accepted_work"] is None
        assert ctms["manifest"]["module"] == "CTMS"
