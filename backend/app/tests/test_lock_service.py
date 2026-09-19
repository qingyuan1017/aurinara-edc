"""Unit tests for freeze, lock, unlock, and ancestor blocking."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.models.lock import FreezeLock, FreezeLockObjectType, FreezeLockType
from app.models.study import Study
from app.services.lock_service import LockService, _HierarchyRef


@pytest.fixture
def service():
    return LockService()


@pytest.fixture
def actor_id():
    return uuid.uuid4()


def _result(first=None):
    result = MagicMock()
    result.scalars.return_value.first.return_value = first
    result.first.return_value = first
    return result


def _study():
    return Study(
        id=uuid.uuid4(),
        study_code="STUDY-001",
        title="Test Study",
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )


class TestFreezeAndLock:
    async def test_freeze_sets_target_and_audits(self, service, actor_id):
        study = _study()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(return_value=_result())

        with patch("app.services.lock_service.audit_service") as audit:
            audit.record = AsyncMock()
            control = await service.freeze(session, study, actor_id)

        assert control.object_type == FreezeLockObjectType.study.value
        assert control.object_id == study.id
        assert control.lock_type == FreezeLockType.freeze.value
        assert control.is_active is True
        audit.record.assert_awaited_once()
        assert audit.record.call_args.kwargs["action"] == "freeze"
        assert audit.record.call_args.kwargs["entity_type"] == "study"

    async def test_lock_sets_lock_state_and_audits(self, service, actor_id):
        study = _study()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(return_value=_result())

        with patch("app.services.lock_service.audit_service") as audit:
            audit.record = AsyncMock()
            control = await service.lock(session, study, actor_id)

        assert control.lock_type == FreezeLockType.lock.value
        assert control.is_active is True
        assert audit.record.call_args.kwargs["action"] == "lock"


class TestUnlock:
    async def test_unlock_requires_nonblank_reason(self, service, actor_id):
        session = AsyncMock()
        with pytest.raises(ValidationError, match="reason"):
            await service.unlock(session, _study(), "  ", actor_id)
        session.execute.assert_not_awaited()

    async def test_unlock_clears_lock_and_audits_reason(self, service, actor_id):
        study = _study()
        control = FreezeLock(
            id=uuid.uuid4(),
            object_type="study",
            object_id=study.id,
            lock_type="lock",
            is_active=True,
            locked_by=uuid.uuid4(),
            locked_at=datetime.now(UTC),
        )
        session = AsyncMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock(return_value=_result(control))

        with patch("app.services.lock_service.audit_service") as audit:
            audit.record = AsyncMock()
            result = await service.unlock(
                session, study, "Approved protocol correction", actor_id
            )

        assert result is control
        assert control.is_active is False
        assert control.unlocked_by == actor_id
        assert control.unlock_reason == "Approved protocol correction"
        assert audit.record.call_args.kwargs["action"] == "unlock"
        assert audit.record.call_args.kwargs["reason"] == "Approved protocol correction"

    async def test_unlock_missing_active_control_is_not_found(self, service, actor_id):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result())
        with pytest.raises(NotFoundError):
            await service.unlock(session, _study(), "reason", actor_id)


class TestModificationBlocking:
    async def test_any_ancestor_control_blocks_modification(self, service):
        field_id = uuid.uuid4()
        form_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        subject_id = uuid.uuid4()
        site_id = uuid.uuid4()
        study_id = uuid.uuid4()
        refs = [
            _HierarchyRef(FreezeLockObjectType.field, field_id),
            _HierarchyRef(FreezeLockObjectType.form, form_id),
            _HierarchyRef(FreezeLockObjectType.visit, visit_id),
            _HierarchyRef(FreezeLockObjectType.subject, subject_id),
            _HierarchyRef(FreezeLockObjectType.site, site_id),
            _HierarchyRef(FreezeLockObjectType.study, study_id),
        ]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result((uuid.uuid4(),)))

        with patch.object(service, "_hierarchy_refs", return_value=refs):
            assert await service.is_modification_blocked(
                session,
                field_id,
                object_type=FreezeLockObjectType.field,
            ) is True

    async def test_no_active_ancestor_control_allows_modification(self, service):
        field_id = uuid.uuid4()
        refs = [_HierarchyRef(FreezeLockObjectType.field, field_id)]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result())

        with patch.object(service, "_hierarchy_refs", return_value=refs):
            assert await service.is_modification_blocked(
                session,
                field_id,
                object_type=FreezeLockObjectType.field,
            ) is False
