"""Focused conformance tests for the Designer ODM 2.0 JSON profile."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.edit_check_dsl import evaluate_rule, validate_rule
from app.core.exceptions import BusinessRuleError
from app.models.designer.form_metadata import FieldDefinition
from app.models.designer.subject_phase_definition import (
    SubjectPhaseDefinition,
    SubjectPhaseVisitDefinition,
)
from app.models.designer.subject_phase_transition import SubjectPhaseTransition
from app.models.edc.study import Study, StudyStatus, StudyVersion, StudyVersionStatus
from app.schemas.designer.odm20 import AURINARA_EXTENSION, OdmDocument
from app.services.designer.odm20_service import (
    _deserialize_coding_rule,
    _serialize_coding_rule,
    odm20_service,
)
from app.services.designer.rule_engine_v2 import (
    DerivationSpec,
    evaluate_derivation,
    evaluate_derivation_plan,
    evaluate_rule_outcome,
    execute_rule_actions,
    validate_derivation_expression,
)
from app.services.designer.subject_phase_service import subject_phase_service


def _document() -> dict:
    return {
        "odmVersion": "2.0",
        "profile": "urn:aurinara:odm:profile:designer-metadata:1",
        "fileType": "Snapshot",
        "fileOID": "FILE.TEST",
        "study": {
            "oid": "STUDY.TEST",
            "studyName": "Test study",
            "protocolName": "TEST-001",
            "metaDataVersion": {
                "oid": "MDV.V1",
                "name": "1.0",
                "studyEvents": [
                    {
                        "oid": "SE.BASELINE",
                        "name": "Baseline",
                        "formRefs": [{"oid": "FORM.DM", "mandatory": True, "orderNumber": 1}],
                    }
                ],
                "forms": [
                    {
                        "oid": "FORM.DM",
                        "name": "Demographics",
                        "itemGroupRefs": [{"oid": "IG.DM", "mandatory": True, "orderNumber": 1}],
                    }
                ],
                "itemGroups": [
                    {
                        "oid": "IG.DM",
                        "name": "Demographics",
                        "itemRefs": [{"oid": "ITEM.AGE", "mandatory": True, "orderNumber": 1}],
                    }
                ],
                "items": [
                    {
                        "oid": "ITEM.AGE",
                        "name": "AGE",
                        "dataType": "integer",
                        "extensions": {AURINARA_EXTENSION: {"controlType": "integer"}},
                    }
                ],
                "codeLists": [],
                "measurementUnits": [],
                "conditions": [],
                "methods": [],
                "extensions": {AURINARA_EXTENSION: {"schedule": "master"}},
            },
        },
    }


@pytest.fixture
async def odm_db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _add_subject_phases(payload: dict) -> None:
    payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION].update(
        {
            "subjectPhases": [
                {
                    "oid": "PH.SCREENING",
                    "name": "Screening",
                    "phaseType": "registered",
                    "displayOrder": 1,
                    "visitOIDs": ["SE.BASELINE"],
                },
                {
                    "oid": "PH.COMPLETE",
                    "name": "Complete",
                    "phaseType": "complete",
                    "displayOrder": 2,
                    "visitOIDs": [],
                },
            ],
            "subjectPhaseTransitions": [
                {
                    "oid": "PHT.SCREENING.COMPLETE",
                    "fromPhaseOID": "PH.SCREENING",
                    "toPhaseOID": "PH.COMPLETE",
                    "label": "Complete study",
                }
            ],
        }
    )


def test_odm20_profile_validates_cross_references() -> None:
    document = OdmDocument.model_validate(_document())
    assert document.study.meta_data_version.study_events[0].form_refs[0].oid == "FORM.DM"


def test_odm20_profile_rejects_dangling_reference() -> None:
    payload = _document()
    payload["study"]["metaDataVersion"]["studyEvents"][0]["formRefs"][0]["oid"] = "FORM.MISSING"
    with pytest.raises(ValidationError, match="Dangling ODM reference"):
        OdmDocument.model_validate(payload)


def test_odm20_profile_rejects_unknown_extension_namespace() -> None:
    payload = _document()
    payload["study"]["metaDataVersion"]["extensions"]["urn:vendor:unknown"] = {}
    with pytest.raises(ValidationError, match="Unsupported ODM extension"):
        OdmDocument.model_validate(payload)


def test_odm20_profile_validates_designer_extension_references() -> None:
    payload = _document()
    payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION].update(
        {
            "codingSettings": [{"fieldItemOID": "ITEM.AGE", "dictionaryReference": "MedDRA"}],
            "crfAccess": [{"role": "Investigator", "formOID": "FORM.DM"}],
        }
    )
    assert OdmDocument.model_validate(payload).study.meta_data_version.oid == "MDV.V1"
    payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION]["codingSettings"][0][
        "fieldItemOID"
    ] = "ITEM.MISSING"
    with pytest.raises(ValidationError, match="dangling item reference"):
        OdmDocument.model_validate(payload)


def test_odm20_profile_validates_subject_phase_extension() -> None:
    payload = _document()
    payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION].update(
        {
            "subjectPhases": [
                {
                    "oid": "PH.SCREENING",
                    "name": "Screening",
                    "phaseType": "registered",
                    "displayOrder": 1,
                    "visitOIDs": ["SE.BASELINE"],
                },
                {
                    "oid": "PH.COMPLETE",
                    "name": "Complete",
                    "phaseType": "complete",
                    "displayOrder": 2,
                    "visitOIDs": [],
                },
            ],
            "subjectPhaseTransitions": [
                {
                    "oid": "PHT.SCREENING.COMPLETE",
                    "fromPhaseOID": "PH.SCREENING",
                    "toPhaseOID": "PH.COMPLETE",
                    "label": "Complete study",
                }
            ],
        }
    )

    document = OdmDocument.model_validate(payload)
    assert odm20_service._counts(document)["subject_phases"] == 2
    assert odm20_service._counts(document)["subject_phase_transitions"] == 1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda extension: extension["subjectPhases"][0].update({"visitOIDs": ["SE.MISSING"]}),
            "Dangling ODM reference",
        ),
        (
            lambda extension: extension["subjectPhases"][0].update({"phaseType": "arm"}),
            "cannot contain visits",
        ),
        (
            lambda extension: extension["subjectPhaseTransitions"][0].update(
                {"toPhaseOID": "PH.MISSING"}
            ),
            "Dangling ODM reference",
        ),
    ],
)
def test_odm20_profile_rejects_invalid_subject_phase_extension(mutate, message) -> None:
    payload = _document()
    extension = payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION]
    extension.update(
        {
            "subjectPhases": [
                {
                    "oid": "PH.SCREENING",
                    "name": "Screening",
                    "phaseType": "registered",
                    "displayOrder": 1,
                    "visitOIDs": ["SE.BASELINE"],
                },
                {
                    "oid": "PH.COMPLETE",
                    "name": "Complete",
                    "phaseType": "complete",
                    "displayOrder": 2,
                    "visitOIDs": [],
                },
            ],
            "subjectPhaseTransitions": [
                {
                    "oid": "PHT.SCREENING.COMPLETE",
                    "fromPhaseOID": "PH.SCREENING",
                    "toPhaseOID": "PH.COMPLETE",
                }
            ],
        }
    )
    mutate(extension)

    with pytest.raises(ValidationError, match=message):
        OdmDocument.model_validate(payload)


def test_odm20_profile_allows_complete_phase_visits() -> None:
    payload = _document()
    _add_subject_phases(payload)
    payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION]["subjectPhases"][1][
        "visitOIDs"
    ] = ["SE.BASELINE"]

    document = OdmDocument.model_validate(payload)

    assert document.study.meta_data_version.extensions[AURINARA_EXTENSION]["subjectPhases"][1][
        "visitOIDs"
    ] == ["SE.BASELINE"]


def test_odm20_profile_rejects_common_event_phase_membership() -> None:
    payload = _document()
    payload["study"]["metaDataVersion"]["studyEvents"][0]["type"] = "common"
    _add_subject_phases(payload)

    with pytest.raises(ValidationError, match="common study event"):
        OdmDocument.model_validate(payload)


def test_odm20_profile_rejects_invalid_file_oid() -> None:
    payload = _document()
    payload["fileOID"] = "not an oid"
    with pytest.raises(ValidationError, match="fileOID"):
        OdmDocument.model_validate(payload)


@pytest.mark.asyncio
async def test_validation_report_is_non_mutating_and_counted() -> None:
    report = await odm20_service.validate_document(_document())
    assert report.valid is True
    assert report.counts["forms"] == 1
    assert report.counts["items"] == 1
    assert report.extensions_used == [AURINARA_EXTENSION]


@pytest.mark.asyncio
async def test_subject_phases_import_and_export_round_trip(
    odm_db_session: AsyncSession,
) -> None:
    actor_id = uuid4()
    study = Study(
        study_code=f"ODM-{uuid4().hex[:8]}",
        title="ODM phase study",
        protocol_number="ODM-PHASE-001",
        status=StudyStatus.draft,
        created_by=actor_id,
    )
    odm_db_session.add(study)
    await odm_db_session.flush()
    payload = _document()
    _add_subject_phases(payload)

    imported = await odm20_service.import_document(
        odm_db_session,
        study_id=study.id,
        payload=payload,
        actor_id=actor_id,
        target_version_id=None,
        version_number="phase-import",
    )

    phases = list(
        (
            await odm_db_session.execute(
                select(SubjectPhaseDefinition)
                .where(SubjectPhaseDefinition.design_version_id == imported.study_version_id)
                .order_by(SubjectPhaseDefinition.display_order)
            )
        )
        .scalars()
        .all()
    )
    assert [(phase.odm_oid, phase.name) for phase in phases] == [
        ("PH.SCREENING", "Screening"),
        ("PH.COMPLETE", "Complete"),
    ]
    phase_visits = list(
        (
            await odm_db_session.execute(
                select(SubjectPhaseVisitDefinition).where(
                    SubjectPhaseVisitDefinition.subject_phase_definition_id == phases[0].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(phase_visits) == 1
    transition = (
        await odm_db_session.execute(
            select(SubjectPhaseTransition).where(
                SubjectPhaseTransition.design_version_id == imported.study_version_id
            )
        )
    ).scalar_one()
    assert transition.odm_oid == "PHT.SCREENING.COMPLETE"

    exported = await odm20_service.export_document(
        odm_db_session,
        study_id=study.id,
        version_id=imported.study_version_id,
    )
    extension = exported.study.meta_data_version.extensions[AURINARA_EXTENSION]
    assert (
        extension["subjectPhases"]
        == payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION]["subjectPhases"]
    )
    assert (
        extension["subjectPhaseTransitions"]
        == payload["study"]["metaDataVersion"]["extensions"][AURINARA_EXTENSION][
            "subjectPhaseTransitions"
        ]
    )


@pytest.mark.asyncio
async def test_import_bounds_long_field_label_and_preserves_full_text(
    odm_db_session: AsyncSession,
) -> None:
    actor_id = uuid4()
    study = Study(
        study_code=f"ODM-{uuid4().hex[:8]}",
        title="ODM long field label",
        status=StudyStatus.draft,
        created_by=actor_id,
    )
    odm_db_session.add(study)
    await odm_db_session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    odm_db_session.add(version)
    await odm_db_session.flush()
    payload = _document()
    long_label = "Long Rave field prompt " * 30
    payload["study"]["metaDataVersion"]["items"][0]["extensions"][AURINARA_EXTENSION]["label"] = (
        long_label
    )

    await odm20_service.import_document(
        odm_db_session,
        study_id=study.id,
        payload=payload,
        actor_id=actor_id,
        target_version_id=version.id,
        version_number=None,
    )

    field = (
        await odm_db_session.execute(
            select(FieldDefinition).where(FieldDefinition.odm_oid == "ITEM.AGE")
        )
    ).scalar_one()
    assert len(field.label) == 500
    assert field.label == long_label[:500]
    assert field.question == long_label


@pytest.mark.asyncio
async def test_subject_phase_import_replaces_untouched_default_flow(
    odm_db_session: AsyncSession,
) -> None:
    actor_id = uuid4()
    study = Study(
        study_code=f"ODM-{uuid4().hex[:8]}",
        title="ODM default phase replacement",
        status=StudyStatus.draft,
        created_by=actor_id,
    )
    odm_db_session.add(study)
    await odm_db_session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    odm_db_session.add(version)
    await odm_db_session.flush()
    await subject_phase_service.seed_default_phase_flow(
        odm_db_session,
        design_version_id=version.id,
        study_id=study.id,
        actor_id=actor_id,
    )
    payload = _document()
    _add_subject_phases(payload)

    await odm20_service.import_document(
        odm_db_session,
        study_id=study.id,
        payload=payload,
        actor_id=actor_id,
        target_version_id=version.id,
        version_number=None,
    )

    phase_oids = list(
        (
            await odm_db_session.execute(
                select(SubjectPhaseDefinition.odm_oid)
                .where(SubjectPhaseDefinition.design_version_id == version.id)
                .order_by(SubjectPhaseDefinition.display_order)
            )
        )
        .scalars()
        .all()
    )
    assert phase_oids == ["PH.SCREENING", "PH.COMPLETE"]


@pytest.mark.asyncio
async def test_subject_phase_import_rejects_authored_target_flow(
    odm_db_session: AsyncSession,
) -> None:
    actor_id = uuid4()
    study = Study(
        study_code=f"ODM-{uuid4().hex[:8]}",
        title="ODM authored phase rejection",
        status=StudyStatus.draft,
        created_by=actor_id,
    )
    odm_db_session.add(study)
    await odm_db_session.flush()
    version = StudyVersion(
        study_id=study.id,
        version_number="1.0",
        status=StudyVersionStatus.draft,
    )
    odm_db_session.add(version)
    await odm_db_session.flush()
    await subject_phase_service.create_phase_definition(
        odm_db_session,
        design_version_id=version.id,
        name="Protocol-specific phase",
        display_order=1,
        actor_id=actor_id,
    )
    payload = _document()
    _add_subject_phases(payload)

    with pytest.raises(BusinessRuleError, match="empty draft"):
        await odm20_service.import_document(
            odm_db_session,
            study_id=study.id,
            payload=payload,
            actor_id=actor_id,
            target_version_id=version.id,
            version_number=None,
        )


def test_structured_coding_rule_round_trips_through_text_storage() -> None:
    rule = {
        "supplementalItemOIDs": ["ITEM.ROUTE", "ITEM.INDICATION"],
        "unresolvedSupplementalTerms": [],
    }
    stored = _serialize_coding_rule(rule)
    assert isinstance(stored, str)
    assert _deserialize_coding_rule(stored) == rule
    assert _deserialize_coding_rule("Exact match") == "Exact match"


@pytest.mark.asyncio
async def test_import_rejects_duplicate_metadata_version_oid_before_flush() -> None:
    existing_version_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    session = AsyncMock()
    session.scalar.side_effect = [None, existing_version_id]
    document = OdmDocument.model_validate(_document())

    with pytest.raises(BusinessRuleError, match="metadata version OID already exists") as exc:
        await odm20_service._target_version(
            session,
            study_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            target_version_id=None,
            version_number="2.0",
            document=document,
        )

    assert exc.value.details == {
        "metadata_version_oid": "MDV.V1",
        "existing_design_version_id": str(existing_version_id),
    }
    session.flush.assert_not_awaited()


def test_v2_rule_returns_typed_actions_only_when_matched() -> None:
    rule = {
        "schemaVersion": 2,
        "scope": {},
        "condition": {
            "operator": ">",
            "field": {"itemOID": "ITEM.AGE", "repeat": "current"},
            "value": 65,
            "children": [],
        },
        "actions": [
            {
                "type": "open_query",
                "target": {"itemOID": "ITEM.AGE", "repeat": "current"},
                "message": "Confirm age",
            }
        ],
        "execution": {"trigger": "form_save", "priority": 100, "stopOnFailure": True},
    }
    assert validate_rule(rule)["schemaVersion"] == 2
    assert evaluate_rule(rule, {"ITEM.AGE": 70}) is True
    outcome = evaluate_rule_outcome(rule, {"ITEM.AGE": 70})
    assert outcome.matched is True
    assert outcome.actions[0]["type"] == "open_query"
    assert evaluate_rule_outcome(rule, {"ITEM.AGE": 60}).actions == ()


def test_derivation_evaluator_supports_safe_builtins() -> None:
    expression = {
        "function": "age",
        "arguments": [{"value": "2000-10-15"}, {"value": "2026-10-14"}],
    }
    assert evaluate_derivation(expression, {}) == 25
    assert validate_derivation_expression(expression) == set()
    assert validate_derivation_expression(
        {"function": "add", "arguments": [{"field": "ITEM.A"}, {"value": 1}]}
    ) == {"ITEM.A"}
    with pytest.raises(ValueError, match="Unsupported derivation function"):
        evaluate_derivation({"function": "eval", "arguments": []}, {})
    with pytest.raises(ValueError, match="requires 2 arguments"):
        validate_derivation_expression({"function": "add", "arguments": []})


def test_derivation_plan_orders_dependencies_and_rejects_cycles() -> None:
    definitions = [
        DerivationSpec(
            target_item_oid="ITEM.C",
            expression={
                "function": "multiply",
                "arguments": [{"field": "ITEM.B"}, {"value": 2}],
            },
            execution_order=1,
        ),
        DerivationSpec(
            target_item_oid="ITEM.B",
            expression={
                "function": "add",
                "arguments": [{"field": "ITEM.A"}, {"value": 1}],
            },
            execution_order=200,
        ),
    ]
    assert evaluate_derivation_plan(definitions, {"ITEM.A": 3}) == {
        "ITEM.B": 4,
        "ITEM.C": 8,
    }
    with pytest.raises(ValueError, match="cycle"):
        evaluate_derivation_plan(
            [
                DerivationSpec("ITEM.A", {"field": "ITEM.B"}),
                DerivationSpec("ITEM.B", {"field": "ITEM.A"}),
            ],
            {},
        )


@pytest.mark.asyncio
async def test_action_executor_is_ordered_and_rolls_back_local_mutations() -> None:
    values = {"ITEM.A": 1}
    result = await execute_rule_actions(
        [
            {"type": "set_value", "target": {"itemOID": "ITEM.A"}, "value": 2},
            {"type": "hide", "target": {"itemOID": "ITEM.A"}},
        ],
        values,
    )
    assert result.values["ITEM.A"] == 2
    assert result.directives[0]["type"] == "hide"

    async def fail_command(_action: dict) -> None:
        raise RuntimeError("query service failed")

    with pytest.raises(RuntimeError, match="query service failed"):
        await execute_rule_actions(
            [
                {"type": "set_value", "target": {"itemOID": "ITEM.A"}, "value": 9},
                {"type": "open_query", "target": {"itemOID": "ITEM.A"}},
            ],
            values,
            command_handler=fail_command,
        )
    assert values["ITEM.A"] == 2
