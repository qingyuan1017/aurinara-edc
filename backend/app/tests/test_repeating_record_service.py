"""Unit tests for the Repeating_Record_Service.

Validates Requirements 11.1-11.4: monotonic row sequences, audited edits,
soft-delete retention metadata, and audited restoration.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BusinessRuleError, ConflictError, ValidationError
from app.models.form_data import FormInstance, FormInstanceStatus
from app.models.form_record import FormRecord
from app.services.repeating_record_service import (
    RepeatingRecordService,
    repeating_record_service,
)


@pytest.fixture
def service():
    return RepeatingRecordService()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _make_form_instance() -> FormInstance:
    return FormInstance(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        form_definition_id=uuid.uuid4(),
        status=FormInstanceStatus.in_progress,
        created_at=datetime.now(UTC),
    )


def _make_session(*, max_sequence: int | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    lock_result = MagicMock()
    max_result = MagicMock()
    max_result.scalar_one_or_none.return_value = max_sequence
    session.execute = AsyncMock(side_effect=[lock_result, max_result])
    return session


class TestAddRecord:
    async def test_add_record_assigns_next_sequence_and_values(
        self, service, actor_id
    ):
        form_instance = _make_form_instance()
        session = _make_session(max_sequence=4)

        with patch(
            "app.services.repeating_record_service.audit_service"
        ) as audit:
            audit.record = AsyncMock()
            record = await service.add_record(
                session,
                form_instance,
                {"event": "headache"},
                actor_id,
            )

        assert record.sequence_number == 5
        assert record.form_instance_id == form_instance.id
        assert record.data_jsonb == {"event": "headache"}
        session.add.assert_called_once_with(record)
        audit.record.assert_awaited_once()
        assert audit.record.call_args.kwargs["entity_type"] == "form_record"
        assert audit.record.call_args.kwargs["action"] == "create"
        assert audit.record.call_args.kwargs["actor_id"] == actor_id

    async def test_add_record_starts_at_one_and_accepts_actor_only(
        self, service, actor_id
    ):
        form_instance = _make_form_instance()
        session = _make_session(max_sequence=None)

        with patch(
            "app.services.repeating_record_service.audit_service"
        ) as audit:
            audit.record = AsyncMock()
            record = await service.add_record(session, form_instance, actor_id)

        assert record.sequence_number == 1
        assert record.data_jsonb is None
        assert audit.record.call_args.kwargs["actor_id"] == actor_id


class TestEditRecord:
    async def test_edit_record_replaces_values_and_audits_change(
        self, service, actor_id
    ):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            sequence_number=1,
            data_jsonb={"status": "ongoing"},
        )
        session = AsyncMock()
        session.flush = AsyncMock()

        with patch(
            "app.services.repeating_record_service.audit_service"
        ) as audit:
            audit.record = AsyncMock()
            result = await service.edit_record(
                session, record, {"status": "resolved"}, actor_id
            )

        assert result.data_jsonb == {"status": "resolved"}
        assert result.updated_at is not None
        kwargs = audit.record.call_args.kwargs
        assert kwargs["action"] == "update"
        assert kwargs["old_value"] == "{'status': 'ongoing'}"
        assert kwargs["new_value"] == "{'status': 'resolved'}"
        assert kwargs["actor_id"] == actor_id

    async def test_edit_record_rejects_deleted_row(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            sequence_number=1,
            deleted_at=datetime.now(UTC),
        )

        with pytest.raises(BusinessRuleError, match="restore it first"):
            await service.edit_record(AsyncMock(), record, {}, actor_id)

    async def test_edit_record_requires_mapping_values(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(), form_instance_id=uuid.uuid4(), sequence_number=1
        )

        with pytest.raises(ValidationError, match="must be an object"):
            await service.edit_record(AsyncMock(), record, [], actor_id)


class TestSoftDeleteAndRestore:
    async def test_soft_delete_retains_row_and_deletion_metadata(
        self, service, actor_id
    ):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            sequence_number=1,
            data_jsonb={"term": "headache"},
        )
        session = AsyncMock()
        session.flush = AsyncMock()

        with patch(
            "app.services.repeating_record_service.audit_service"
        ) as audit:
            audit.record = AsyncMock()
            result = await service.soft_delete(
                session, record, "Entered in error", actor_id
            )

        assert result.id == record.id
        assert result.deleted_at is not None
        assert result.deleted_at.tzinfo is not None
        assert result.deleted_by == actor_id
        assert result.deletion_reason == "Entered in error"
        assert result.data_jsonb == {"term": "headache"}
        kwargs = audit.record.call_args.kwargs
        assert kwargs["action"] == "delete"
        assert kwargs["reason"] == "Entered in error"
        assert kwargs["actor_id"] == actor_id

    async def test_soft_delete_rejects_blank_reason(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(), form_instance_id=uuid.uuid4(), sequence_number=1
        )

        with pytest.raises(ValidationError, match="reason is required"):
            await service.soft_delete(AsyncMock(), record, "  ", actor_id)

    async def test_soft_delete_rejects_repeat_delete(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            sequence_number=1,
            deleted_at=datetime.now(UTC),
        )

        with pytest.raises(ConflictError, match="already deleted"):
            await service.soft_delete(AsyncMock(), record, "again", actor_id)

    async def test_restore_clears_deletion_state_and_audits(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(),
            form_instance_id=uuid.uuid4(),
            sequence_number=1,
            deleted_at=datetime.now(UTC),
            deleted_by=uuid.uuid4(),
            deletion_reason="Entered in error",
        )
        session = AsyncMock()
        session.flush = AsyncMock()

        with patch(
            "app.services.repeating_record_service.audit_service"
        ) as audit:
            audit.record = AsyncMock()
            result = await service.restore(session, record, actor_id)

        assert result.deleted_at is None
        assert result.deleted_by is None
        assert result.deletion_reason is None
        assert result.updated_at is not None
        kwargs = audit.record.call_args.kwargs
        assert kwargs["action"] == "restore"
        assert kwargs["actor_id"] == actor_id
        assert kwargs["new_value"] == (
            "deleted_at=None, deleted_by=None, deletion_reason=None"
        )

    async def test_restore_rejects_active_row(self, service, actor_id):
        record = FormRecord(
            id=uuid.uuid4(), form_instance_id=uuid.uuid4(), sequence_number=1
        )

        with pytest.raises(ConflictError, match="not deleted"):
            await service.restore(AsyncMock(), record, actor_id)


class TestSingleton:
    def test_singleton_exists(self):
        assert isinstance(repeating_record_service, RepeatingRecordService)
