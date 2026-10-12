"""Focused tests for atomic Designer JSON import orchestration."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.api.routes.designer.bulk_import import bulk_import_designer_definitions
from app.core.edit_check_dsl import validate_rule
from app.core.exceptions import ValidationError
from app.models.designer.study_version import StudyVersion, StudyVersionStatus
from app.schemas.designer.bulk_import import DesignerBulkImportRequest
from app.services.designer import bulk_import_service as bulk_module
from app.services.designer.bulk_import_service import DesignerBulkImportService
from app.services.designer.codelist_service import CodelistService
from app.services.designer.visit_definition_service import VisitDefinitionService

EXAMPLES_DIR = Path(__file__).parents[2] / "examples"


def _version() -> StudyVersion:
    return StudyVersion(
        id=uuid4(),
        study_id=uuid4(),
        version_number="1.0",
        status=StudyVersionStatus.draft,
        created_at=datetime.now(UTC),
    )


def _payload(codelist_code: str = "YES_NO") -> DesignerBulkImportRequest:
    return DesignerBulkImportRequest.model_validate(
        {
            "codelists": [
                {
                    "name": "Yes / No",
                    "code": "YES_NO",
                    "items": [
                        {"code": "Y", "label": "Yes", "display_order": 1},
                        {"code": "N", "label": "No", "display_order": 2},
                    ],
                }
            ],
            "forms": [
                {
                    "name": "Demographics",
                    "form_code": "DM",
                    "display_order": 1,
                    "sections": [
                        {
                            "name": "Main",
                            "display_order": 1,
                            "fields": [
                                {
                                    "label": "Completed?",
                                    "variable_name": "DMCOMP",
                                    "control_type": "radio",
                                    "data_type": "string",
                                    "display_order": 1,
                                    "codelist_code": codelist_code,
                                }
                            ],
                        }
                    ],
                }
            ],
            "edit_checks": [
                {
                    "name": "Completion required",
                    "rule_json": {"field": "DMCOMP", "operator": "not_null"},
                    "severity": "error",
                }
            ],
            "visits": [
                {
                    "name": "Baseline",
                    "visit_number": 1,
                    "visit_type": "scheduled",
                    "target_day": 0,
                    "display_order": 1,
                }
            ],
        }
    )


def test_import_schema_rejects_empty_payload_and_ambiguous_field_reference():
    with pytest.raises(PydanticValidationError, match="at least one"):
        DesignerBulkImportRequest()

    with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
        DesignerBulkImportRequest.model_validate(
            {"visits": _payload().model_dump()["visits"], "visit_definitions": []}
        )

    payload = _payload().model_dump(mode="json")
    payload["forms"][0]["sections"][0]["fields"][0]["codelist_id"] = str(uuid4())
    with pytest.raises(PydanticValidationError, match="either codelist_id or codelist_code"):
        DesignerBulkImportRequest.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    sorted(EXAMPLES_DIR.glob("designer-*.json")),
    ids=lambda path: path.name,
)
def test_designer_json_examples_remain_uploadable(path: Path):
    request = DesignerBulkImportRequest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    available_codelist_codes = {codelist.code for codelist in request.codelists}
    for codelist in request.codelists:
        CodelistService._validate_name(codelist.name)
        CodelistService._validate_item_count(len(codelist.items))
    for form in request.forms:
        for section in form.sections:
            for field in section.fields:
                if field.codelist_code is not None:
                    assert field.codelist_code in available_codelist_codes
    for edit_check in request.edit_checks:
        validate_rule(edit_check.rule_json)
    for visit in request.visits:
        VisitDefinitionService._validate_window(visit)
        VisitDefinitionService._validate_cycle_fields(visit)


async def test_import_creates_all_resources_and_resolves_codelist_code(monkeypatch):
    service = DesignerBulkImportService()
    version = _version()
    actor_id = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    codelist = SimpleNamespace(id=uuid4(), code="YES_NO")
    create_codelist = AsyncMock(return_value=codelist)
    create_form = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    create_section = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    create_field = AsyncMock()
    create_check = AsyncMock()
    create_visit = AsyncMock()
    monkeypatch.setattr(bulk_module.codelist_service, "create_codelist", create_codelist)
    monkeypatch.setattr(bulk_module.form_metadata_service, "create_form", create_form)
    monkeypatch.setattr(bulk_module.form_metadata_service, "create_section", create_section)
    monkeypatch.setattr(bulk_module.form_metadata_service, "create_field", create_field)
    monkeypatch.setattr(bulk_module.edit_check_service, "create_edit_check", create_check)
    monkeypatch.setattr(bulk_module.visit_definition_service, "define_visit", create_visit)

    response = await service.import_definitions(session, version, _payload(), actor_id)

    assert response.forms_created == 1
    assert response.sections_created == 1
    assert response.fields_created == 1
    assert response.codelists_created == 1
    assert response.codelist_items_created == 2
    assert response.edit_checks_created == 1
    assert response.visits_created == 1
    field_data = create_field.await_args.args[3]
    assert field_data.codelist_id == codelist.id


async def test_import_rejects_unknown_codelist_code_before_creating_field(monkeypatch):
    service = DesignerBulkImportService()
    version = _version()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    monkeypatch.setattr(
        bulk_module.codelist_service,
        "create_codelist",
        AsyncMock(return_value=SimpleNamespace(id=uuid4(), code="YES_NO")),
    )
    monkeypatch.setattr(
        bulk_module.form_metadata_service,
        "create_form",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    monkeypatch.setattr(
        bulk_module.form_metadata_service,
        "create_section",
        AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    create_field = AsyncMock()
    monkeypatch.setattr(bulk_module.form_metadata_service, "create_field", create_field)

    with pytest.raises(ValidationError, match="unknown codelist code"):
        await service.import_definitions(
            session, version, _payload(codelist_code="MISSING"), uuid4()
        )
    create_field.assert_not_awaited()


async def test_route_requires_permissions_for_only_supplied_resource_types(monkeypatch):
    version = _version()
    body = _payload()
    session = AsyncMock()
    user = SimpleNamespace(id=uuid4())
    permissions = MagicMock()
    expected = SimpleNamespace(forms_created=1)

    monkeypatch.setattr(bulk_module.study_version_service, "guard_mutable", MagicMock())
    monkeypatch.setattr("app.api.routes.designer.bulk_import.study_service.get_study", AsyncMock())
    monkeypatch.setattr(
        "app.api.routes.designer.bulk_import.designer_bulk_import_service.get_target_version",
        AsyncMock(return_value=version),
    )
    monkeypatch.setattr(
        "app.api.routes.designer.bulk_import.designer_bulk_import_service.import_definitions",
        AsyncMock(return_value=expected),
    )

    response = await bulk_import_designer_definitions(
        version.study_id, body, session, user, permissions
    )

    assert response is expected
    assert {call.args[1] for call in permissions.require.call_args_list} == {
        "designer.codelist.configure",
        "designer.editcheck.configure",
        "designer.field.configure",
        "designer.form.configure",
        "designer.visit.configure",
    }
    assert all(
        call.kwargs["study_id"] == version.study_id for call in permissions.require.call_args_list
    )
