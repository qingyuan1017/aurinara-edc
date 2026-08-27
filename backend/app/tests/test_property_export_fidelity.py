"""Property-based test for export filtering and content fidelity (CSV).

**Validates: Requirements 18.4, 19.3, 19.4, 19.5**

Property 34: Export filtering and content fidelity.

For any export request with filters, the ExportService:
1. Creates an export with status=Queued and the filters persisted.
2. The lifecycle transitions (Queued→Running→Completed) work without error
   for valid sequences.
3. The lifecycle rejects invalid transitions (e.g., Queued→Completed,
   Failed→Running).

Since we can't easily test the full CSV worker (needs real DB), this test
focuses on verifying ExportService lifecycle and filter persistence using
mocked sessions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import BusinessRuleError
from app.models.export import Export, ExportStatus, ExportType
from app.services.export_service import ExportService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Filter key strategies — mirrors the supported filter parameters
site_id_strategy = st.one_of(st.none(), st.uuids().map(str))
subject_id_strategy = st.one_of(st.none(), st.uuids().map(str))
domain_strategy = st.one_of(
    st.none(),
    st.sampled_from(["AE", "DM", "VS", "LB", "CM", "MH", "EX", "DS"]),
)
date_strategy = st.one_of(
    st.none(),
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
    ).map(lambda d: d.isoformat()),
)
boolean_filter_strategy = st.one_of(st.none(), st.booleans())

export_type_strategy = st.sampled_from([ExportType.csv, ExportType.subject_list])


@st.composite
def export_filters_strategy(draw):
    """Generate random export filter combinations."""
    filters = {}

    site_id = draw(site_id_strategy)
    if site_id is not None:
        filters["site_id"] = site_id

    subject_id = draw(subject_id_strategy)
    if subject_id is not None:
        filters["subject_id"] = subject_id

    domain = draw(domain_strategy)
    if domain is not None:
        filters["domain"] = domain

    date_from = draw(date_strategy)
    if date_from is not None:
        filters["date_from"] = date_from

    date_to = draw(date_strategy)
    if date_to is not None:
        filters["date_to"] = date_to

    changed_since = draw(date_strategy)
    if changed_since is not None:
        filters["changed_since"] = changed_since

    locked_only = draw(boolean_filter_strategy)
    if locked_only is not None:
        filters["locked_only"] = locked_only

    clean_only = draw(boolean_filter_strategy)
    if clean_only is not None:
        filters["clean_only"] = clean_only

    # Optional: visit and form filters
    visit_instance_id = draw(st.one_of(st.none(), st.uuids().map(str)))
    if visit_instance_id is not None:
        filters["visit_instance_id"] = visit_instance_id

    form_definition_id = draw(st.one_of(st.none(), st.uuids().map(str)))
    if form_definition_id is not None:
        filters["form_definition_id"] = form_definition_id

    return filters if filters else None


@st.composite
def export_request_strategy(draw):
    """Generate a complete export creation request."""
    return {
        "study_id": draw(st.uuids()),
        "export_type": draw(export_type_strategy),
        "filters": draw(export_filters_strategy()),
        "actor_id": draw(st.uuids()),
    }


# Invalid transition pairs: (from_status, attempted_action)
# Valid transitions are: Queued→Running (start), Running→Completed (complete),
# Running→Failed (fail)
INVALID_TRANSITIONS = [
    # Cannot start from non-Queued
    (ExportStatus.running, "start"),
    (ExportStatus.completed, "start"),
    (ExportStatus.failed, "start"),
    # Cannot complete from non-Running
    (ExportStatus.queued, "complete"),
    (ExportStatus.completed, "complete"),
    (ExportStatus.failed, "complete"),
    # Cannot fail from non-Running
    (ExportStatus.queued, "fail"),
    (ExportStatus.completed, "fail"),
    (ExportStatus.failed, "fail"),
]

invalid_transition_strategy = st.sampled_from(INVALID_TRANSITIONS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_export(
    study_id: uuid.UUID,
    export_type: str = ExportType.csv,
    filters: dict | None = None,
    actor_id: uuid.UUID | None = None,
    status: str = ExportStatus.queued,
) -> Export:
    """Create an Export model instance for testing."""
    export = Export(
        id=uuid.uuid4(),
        study_id=study_id,
        export_type=export_type,
        status=status,
        filters=filters,
        requested_by=actor_id or uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    return export


def _make_mock_session() -> AsyncMock:
    """Create a mock async session that tracks relevant calls."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Property 34: Export filtering and content fidelity
# ---------------------------------------------------------------------------


class TestExportFilteringAndFidelityProperties:
    """Property-based tests for export filtering and lifecycle fidelity.

    **Validates: Requirements 18.4, 19.3, 19.4, 19.5**
    """

    @settings(max_examples=100, deadline=None)
    @given(request=export_request_strategy())
    async def test_create_export_persists_filters_and_queued_status(self, request):
        """For any filter combination, create_export produces a Queued export
        with the exact filters persisted.

        **Validates: Requirements 19.3**

        Asserts:
        - The returned export has status=Queued
        - The returned export has the exact filters dict that was passed in
        - The returned export has the correct study_id, export_type, and actor
        """
        service = ExportService()
        session = _make_mock_session()

        # Mock audit_service.record to avoid side effects
        with patch("app.services.export_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            export = await service.create_export(
                session,
                study_id=request["study_id"],
                export_type=request["export_type"],
                filters=request["filters"],
                actor_id=request["actor_id"],
            )

        # Status must be Queued on creation
        assert export.status == ExportStatus.queued, (
            f"Newly created export must have status=Queued, got '{export.status}'"
        )

        # Filters must be persisted exactly as provided
        assert export.filters == request["filters"], (
            f"Export filters must match input. "
            f"Expected: {request['filters']}, Got: {export.filters}"
        )

        # Study ID must match
        assert export.study_id == request["study_id"], (
            f"Export study_id mismatch: expected {request['study_id']}, "
            f"got {export.study_id}"
        )

        # Export type must match
        assert export.export_type == request["export_type"], (
            f"Export type mismatch: expected {request['export_type']}, "
            f"got {export.export_type}"
        )

        # Actor must match
        assert export.requested_by == request["actor_id"], (
            f"Export requested_by mismatch: expected {request['actor_id']}, "
            f"got {export.requested_by}"
        )

        # session.add must have been called (persisted)
        session.add.assert_called_once_with(export)
        session.flush.assert_awaited_once()

    @settings(max_examples=100, deadline=None)
    @given(request=export_request_strategy())
    async def test_valid_lifecycle_queued_to_running_to_completed(self, request):
        """For any export, the valid lifecycle Queued→Running→Completed
        succeeds without error.

        **Validates: Requirements 19.3, 19.5**

        Asserts:
        - start_export transitions from Queued to Running and sets started_at
        - complete_export transitions from Running to Completed and sets
          file_path, file_size, completed_at
        """
        service = ExportService()
        session = _make_mock_session()

        # Create an export in Queued state
        export = _make_export(
            study_id=request["study_id"],
            export_type=request["export_type"],
            filters=request["filters"],
            actor_id=request["actor_id"],
            status=ExportStatus.queued,
        )

        # Transition: Queued → Running
        result = await service.start_export(session, export)
        assert result.status == ExportStatus.running, (
            f"After start_export, status must be Running, got '{result.status}'"
        )
        assert result.started_at is not None, (
            "After start_export, started_at must be set"
        )

        # Transition: Running → Completed
        file_path = f"/exports/export_{export.id}.csv"
        file_size = 1024

        result = await service.complete_export(
            session,
            export,
            file_path=file_path,
            file_size=file_size,
        )
        assert result.status == ExportStatus.completed, (
            f"After complete_export, status must be Completed, got '{result.status}'"
        )
        assert result.file_path == file_path, (
            f"After complete_export, file_path must be set to '{file_path}'"
        )
        assert result.file_size == file_size, (
            f"After complete_export, file_size must be {file_size}"
        )
        assert result.completed_at is not None, (
            "After complete_export, completed_at must be set"
        )

    @settings(max_examples=100, deadline=None)
    @given(request=export_request_strategy())
    async def test_valid_lifecycle_queued_to_running_to_failed(self, request):
        """For any export, the valid lifecycle Queued→Running→Failed
        succeeds without error.

        **Validates: Requirements 19.3, 19.5**

        Asserts:
        - start_export transitions from Queued to Running
        - fail_export transitions from Running to Failed and sets error_message
        """
        service = ExportService()
        session = _make_mock_session()

        # Create an export in Queued state
        export = _make_export(
            study_id=request["study_id"],
            export_type=request["export_type"],
            filters=request["filters"],
            actor_id=request["actor_id"],
            status=ExportStatus.queued,
        )

        # Transition: Queued → Running
        result = await service.start_export(session, export)
        assert result.status == ExportStatus.running

        # Transition: Running → Failed
        error_msg = "Test failure reason"
        result = await service.fail_export(
            session,
            export,
            error_message=error_msg,
        )
        assert result.status == ExportStatus.failed, (
            f"After fail_export, status must be Failed, got '{result.status}'"
        )
        assert result.error_message == error_msg, (
            f"After fail_export, error_message must be set"
        )
        assert result.completed_at is not None, (
            "After fail_export, completed_at must be set"
        )

    @settings(max_examples=100, deadline=None)
    @given(
        request=export_request_strategy(),
        invalid_transition=invalid_transition_strategy,
    )
    async def test_invalid_lifecycle_transitions_are_rejected(
        self, request, invalid_transition
    ):
        """For any export, invalid status transitions raise BusinessRuleError.

        **Validates: Requirements 19.3, 19.4**

        The lifecycle must reject:
        - start_export on non-Queued exports
        - complete_export on non-Running exports
        - fail_export on non-Running exports
        """
        service = ExportService()
        session = _make_mock_session()

        from_status, action = invalid_transition

        # Create an export in the "from" status
        export = _make_export(
            study_id=request["study_id"],
            export_type=request["export_type"],
            filters=request["filters"],
            actor_id=request["actor_id"],
            status=from_status,
        )

        with pytest.raises(BusinessRuleError):
            if action == "start":
                await service.start_export(session, export)
            elif action == "complete":
                await service.complete_export(
                    session,
                    export,
                    file_path="/fake/path.csv",
                    file_size=100,
                )
            elif action == "fail":
                await service.fail_export(
                    session,
                    export,
                    error_message="test error",
                )

    @settings(max_examples=100, deadline=None)
    @given(request=export_request_strategy())
    async def test_filters_round_trip_through_create(self, request):
        """For any filter combination, the filters stored on the export
        are identical to the input filters (content fidelity).

        **Validates: Requirements 19.3, 19.5**

        This verifies that no filter keys are silently dropped, renamed,
        or transformed during export creation.
        """
        service = ExportService()
        session = _make_mock_session()

        with patch("app.services.export_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            export = await service.create_export(
                session,
                study_id=request["study_id"],
                export_type=request["export_type"],
                filters=request["filters"],
                actor_id=request["actor_id"],
            )

        input_filters = request["filters"]

        if input_filters is None:
            assert export.filters is None, (
                "When no filters provided, export.filters must be None"
            )
        else:
            assert export.filters is not None, (
                "When filters provided, export.filters must not be None"
            )
            # Every input key must be present in the stored filters
            for key, value in input_filters.items():
                assert key in export.filters, (
                    f"Filter key '{key}' was dropped during creation"
                )
                assert export.filters[key] == value, (
                    f"Filter '{key}' value mismatch: "
                    f"input={value}, stored={export.filters[key]}"
                )
            # No extra keys should be injected
            for key in export.filters:
                assert key in input_filters, (
                    f"Unexpected filter key '{key}' appeared in stored filters"
                )

    @settings(max_examples=100, deadline=None)
    @given(request=export_request_strategy())
    async def test_create_export_records_audit_event(self, request):
        """For any export creation, an audit event is recorded.

        **Validates: Requirements 18.4**

        The export creation must write an Audit_Event capturing the action,
        ensuring traceability of export operations.
        """
        service = ExportService()
        session = _make_mock_session()

        with patch("app.services.export_service.audit_service") as mock_audit:
            mock_audit.record = AsyncMock()

            await service.create_export(
                session,
                study_id=request["study_id"],
                export_type=request["export_type"],
                filters=request["filters"],
                actor_id=request["actor_id"],
            )

        # Audit record must be called at least once for export creation
        mock_audit.record.assert_awaited_once()

        # Verify audit call args
        call_kwargs = mock_audit.record.call_args[1]
        assert call_kwargs["entity_type"] == "export", (
            f"Audit entity_type must be 'export', got '{call_kwargs['entity_type']}'"
        )
        assert call_kwargs["action"] == "create", (
            f"Audit action must be 'create', got '{call_kwargs['action']}'"
        )
        assert call_kwargs["study_id"] == request["study_id"], (
            "Audit study_id must match the export's study_id"
        )
        assert call_kwargs["actor_id"] == request["actor_id"], (
            "Audit actor_id must match the requesting user"
        )
