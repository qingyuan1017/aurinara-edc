"""Focused tests for the seeded edit-check examples (task 19.4)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import BusinessRuleError
from app.models.edit_check import EditCheck
from app.models.study import StudyVersion, StudyVersionStatus
from app.services.edit_check_examples import (
    EXAMPLE_EDIT_CHECKS,
    seed_example_edit_checks,
)
from app.services.edit_check_service import EditCheckService


def _version(status: StudyVersionStatus = StudyVersionStatus.draft) -> MagicMock:
    version = MagicMock(spec=StudyVersion)
    version.id = uuid4()
    version.study_id = uuid4()
    version.status = status
    return version


def _session(*, existing_id=None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing_id
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_seed_creates_all_five_examples_with_expected_severities():
    session = _session()
    service = MagicMock()
    service.create_edit_check = AsyncMock(
        side_effect=lambda _session, version, definition, actor_id: EditCheck(
            id=uuid4(),
            study_version_id=version.id,
            name=definition["name"],
            description=definition["description"],
            rule_json=definition["rule_json"],
            severity=definition["severity"],
            is_active=True,
        )
    )
    version = _version()
    actor_id = uuid4()

    created = await seed_example_edit_checks(
        session, version, actor_id, service=service
    )

    assert len(created) == 5
    assert [check.name for check in created] == [
        definition["name"] for definition in EXAMPLE_EDIT_CHECKS
    ]
    assert [check.severity for check in created] == [
        "error",
        "error",
        "error",
        "error",
        "warning",
    ]
    assert service.create_edit_check.await_count == 5
    for call in service.create_edit_check.await_args_list:
        assert call.args[1] is version
        assert call.args[3] == actor_id


@pytest.mark.asyncio
async def test_seed_is_idempotent_when_version_has_existing_edit_check():
    session = _session(existing_id=uuid4())
    service = MagicMock()
    service.create_edit_check = AsyncMock()

    created = await seed_example_edit_checks(
        session, _version(), uuid4(), service=service
    )

    assert created == []
    service.create_edit_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_rejects_published_version_before_database_write():
    session = _session()
    service = MagicMock()
    service.create_edit_check = AsyncMock()

    with pytest.raises(BusinessRuleError, match="Cannot modify a published"):
        await seed_example_edit_checks(
            session,
            _version(StudyVersionStatus.published),
            uuid4(),
            service=service,
        )

    session.execute.assert_not_awaited()
    service.create_edit_check.assert_not_awaited()


def test_examples_are_safe_rules_and_fire_only_for_the_declared_failures():
    service = EditCheckService()
    rules = {definition["name"]: definition["rule_json"] for definition in EXAMPLE_EDIT_CHECKS}

    assert service.test(
        rules["AE start date after end date"],
        {"AESTDAT": "2024-02-02", "AEENDAT": "2024-02-01"},
    )
    assert not service.test(
        rules["AE start date after end date"],
        {"AESTDAT": "2024-02-01", "AEENDAT": "2024-02-01"},
    )

    assert service.test(
        rules["Informed consent after first procedure"],
        {"ICDAT": "2024-02-02", "PROCDAT": "2024-02-01"},
    )
    assert service.test(
        rules["Serious AE missing seriousness criteria"],
        {"AESER": "Yes", "AESCRIT": ""},
    )
    assert service.test(
        rules["Fatal AE missing death date"],
        {"AEOUT": "Fatal", "DTHDAT": None},
    )
    assert service.test(
        rules["Visit date outside visit window"],
        {
            "VISITDTC": "2024-01-10",
            "VISIT_WINDOW_START": "2024-01-11",
            "VISIT_WINDOW_END": "2024-01-13",
        },
    )
    assert not service.test(
        rules["Visit date outside visit window"],
        {
            "VISITDTC": "2024-01-12",
            "VISIT_WINDOW_START": "2024-01-11",
            "VISIT_WINDOW_END": "2024-01-13",
        },
    )
