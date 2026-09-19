"""Focused runtime tests for Edit_Check_Engine task 19.3."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.edit_check import EditCheck
from app.models.form_data import FormInstance
from app.models.query import QueryTargetType, QueryType
from app.services.edit_check_service import EditCheckService


def _check(*, severity: str = "warning") -> EditCheck:
    return EditCheck(
        id=uuid4(),
        study_version_id=uuid4(),
        name="Lab range",
        description="Lab result is outside the reference range",
        rule_json={
            "or": [
                {"field": "lab", "operator": "<", "value_field": "lab.normal_low"},
                {"field": "lab", "operator": ">", "value_field": "lab.normal_high"},
            ]
        },
        severity=severity,
        is_active=True,
    )


def _form() -> FormInstance:
    return FormInstance(
        id=uuid4(),
        subject_id=uuid4(),
        form_definition_id=uuid4(),
        data_jsonb={"lab": 5, "lab.normal_low": 10, "lab.normal_high": 20},
    )


def test_test_evaluates_sample_data_without_persistence():
    service = EditCheckService()
    rule = _check().rule_json

    assert service.test(rule, {"lab": 5, "lab.normal_low": 10, "lab.normal_high": 20}) is True


def test_test_accepts_normal_range_pseudo_fields_as_dotted_values():
    service = EditCheckService()
    rule = {"field": "lab", "operator": ">=", "value_field": "lab.normal_low"}

    assert service.test(rule, {"lab": 10, "lab.normal_low": 10}) is True


async def test_runtime_persists_failed_result_with_severity():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(
        return_value=SimpleNamespace(study_id=uuid4(), site_id=uuid4())
    )
    service = EditCheckService()
    form = _form()
    check = _check(severity="error")

    with patch("app.services.edit_check_service.audit_service") as audit:
        audit.record = AsyncMock()
        result = await service.evaluate_edit_check(
            session, form, check, actor_id=uuid4(), sample_data=form.data_jsonb
        )

    assert result is not None
    assert result.outcome == "failed"
    assert result.severity == "error"
    assert result.form_instance_id == form.id
    session.add.assert_called_once_with(result)
    audit.record.assert_awaited_once()


async def test_query_severity_creates_system_query_linked_to_form():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    study_id, site_id = uuid4(), uuid4()
    session.get = AsyncMock(return_value=SimpleNamespace(study_id=study_id, site_id=site_id))
    query_service = MagicMock()
    query_service.create_query = AsyncMock()
    service = EditCheckService(query_service_instance=query_service)
    form = _form()
    check = _check(severity="query")
    actor_id = uuid4()

    with patch("app.services.edit_check_service.audit_service") as audit:
        audit.record = AsyncMock()
        await service.evaluate_edit_check(
            session, form, check, actor_id=actor_id, sample_data=form.data_jsonb
        )

    query_service.create_query.assert_awaited_once()
    query_kwargs = query_service.create_query.call_args.kwargs
    assert query_kwargs["query_type"] == QueryType.system
    assert query_kwargs["target_type"] == QueryTargetType.form_instance
    assert query_kwargs["target_id"] == form.id
    assert query_kwargs["study_id"] == study_id
    assert query_kwargs["site_id"] == site_id
    assert query_kwargs["subject_id"] == form.subject_id
    assert query_kwargs["actor_id"] == actor_id
