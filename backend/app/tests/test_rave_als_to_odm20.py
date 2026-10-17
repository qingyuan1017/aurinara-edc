from pathlib import Path

import pytest
from scripts.convert_rave_als_to_odm20 import ConversionError, convert_workbook

from app.schemas.designer.odm20 import AURINARA_EXTENSION, OdmDocument


def _workbook(*, include_check: bool = False, extra_field_rows: str = "") -> str:
    check_row = (
        "<Row><Cell><Data ss:Type='String'>CHK1</Data></Cell></Row>" if include_check else ""
    )
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<Workbook xmlns='urn:schemas-microsoft-com:office:spreadsheet'
 xmlns:ss='urn:schemas-microsoft-com:office:spreadsheet'>
 <Worksheet ss:Name='CRFDraft'><Table>
  <Row><Cell><Data ss:Type='String'>DraftName</Data></Cell><Cell><Data ss:Type='String'>ProjectName</Data></Cell><Cell><Data ss:Type='String'>PrimaryFormOID</Data></Cell><Cell><Data ss:Type='String'>DefaultMatrixOID</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>TEST Version 1.0</Data></Cell><Cell><Data ss:Type='String'>TEST</Data></Cell><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>DEFAULT</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='Forms'><Table>
  <Row><Cell><Data ss:Type='String'>OID</Data></Cell><Cell><Data ss:Type='String'>Ordinal</Data></Cell><Cell><Data ss:Type='String'>DraftFormName</Data></Cell><Cell><Data ss:Type='String'>DraftFormActive</Data></Cell><Cell ss:Index='7'><Data ss:Type='String'>IsSignatureRequired</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell><Data ss:Type='String'>Demographics</Data></Cell><Cell><Data ss:Type='String'>TRUE</Data></Cell><Cell ss:Index='7'><Data ss:Type='String'>TRUE</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='Fields'><Table>
  <Row><Cell><Data ss:Type='String'>FormOID</Data></Cell><Cell><Data ss:Type='String'>FieldOID</Data></Cell><Cell><Data ss:Type='String'>Ordinal</Data></Cell><Cell ss:Index='5'><Data ss:Type='String'>DraftFieldName</Data></Cell><Cell><Data ss:Type='String'>DraftFieldActive</Data></Cell><Cell><Data ss:Type='String'>VariableOID</Data></Cell><Cell><Data ss:Type='String'>DataFormat</Data></Cell><Cell><Data ss:Type='String'>DataDictionaryName</Data></Cell><Cell ss:Index='12'><Data ss:Type='String'>ControlType</Data></Cell><Cell ss:Index='15'><Data ss:Type='String'>PreText</Data></Cell><Cell ss:Index='20'><Data ss:Type='String'>IsLog</Data></Cell><Cell ss:Index='25'><Data ss:Type='String'>IsRequired</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell ss:Index='5'><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>TRUE</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>$1</Data></Cell><Cell><Data ss:Type='String'>dSEX</Data></Cell><Cell ss:Index='12'><Data ss:Type='String'>RadioButton</Data></Cell><Cell ss:Index='15'><Data ss:Type='String'>Sex</Data></Cell><Cell ss:Index='20'><Data ss:Type='String'>FALSE</Data></Cell><Cell ss:Index='25'><Data ss:Type='String'>TRUE</Data></Cell></Row>
  {extra_field_rows}
 </Table></Worksheet>
 <Worksheet ss:Name='Folders'><Table>
  <Row><Cell><Data ss:Type='String'>OID</Data></Cell><Cell><Data ss:Type='String'>Ordinal</Data></Cell><Cell><Data ss:Type='String'>FolderName</Data></Cell><Cell ss:Index='10'><Data ss:Type='String'>ParentFolderOID</Data></Cell><Cell><Data ss:Type='String'>IsReusable</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>SCR</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell><Data ss:Type='String'>Screening</Data></Cell><Cell ss:Index='11'><Data ss:Type='String'>FALSE</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='DataDictionaries'><Table>
  <Row><Cell><Data ss:Type='String'>DataDictionaryName</Data></Cell><Cell><Data ss:Type='String'>OID</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>dSEX</Data></Cell><Cell><Data ss:Type='String'>DSEX</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='DataDictionaryEntries'><Table>
  <Row><Cell><Data ss:Type='String'>DataDictionaryName</Data></Cell><Cell><Data ss:Type='String'>CodedData</Data></Cell><Cell><Data ss:Type='String'>Ordinal</Data></Cell><Cell><Data ss:Type='String'>UserDataString</Data></Cell><Cell><Data ss:Type='String'>Specify</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>dSEX</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell><Data ss:Type='String'>Male</Data></Cell><Cell><Data ss:Type='String'>FALSE</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='UnitDictionaries'><Table><Row><Cell><Data ss:Type='String'>UnitDictionaryName</Data></Cell></Row></Table></Worksheet>
 <Worksheet ss:Name='UnitDictionaryEntries'><Table><Row><Cell><Data ss:Type='String'>UnitDictionaryName</Data></Cell></Row></Table></Worksheet>
 <Worksheet ss:Name='Matrices'><Table><Row><Cell><Data ss:Type='String'>MatrixName</Data></Cell><Cell><Data ss:Type='String'>OID</Data></Cell></Row><Row><Cell><Data ss:Type='String'>Default</Data></Cell><Cell><Data ss:Type='String'>DEFAULT</Data></Cell></Row></Table></Worksheet>
 <Worksheet ss:Name='Matrix1#DEFAULT'><Table>
  <Row><Cell><Data ss:Type='String'>Matrix: DEFAULT</Data></Cell><Cell><Data ss:Type='String'>SCR</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>X</Data></Cell></Row>
 </Table></Worksheet>
 <Worksheet ss:Name='Checks'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row>{check_row}</Table></Worksheet>
 <Worksheet ss:Name='CheckSteps'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row></Table></Worksheet>
 <Worksheet ss:Name='CheckActions'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row></Table></Worksheet>
 <Worksheet ss:Name='Derivations'><Table><Row><Cell><Data ss:Type='String'>DerivationName</Data></Cell></Row></Table></Worksheet>
</Workbook>"""


def test_converts_sparse_spreadsheetml_to_valid_odm(tmp_path: Path) -> None:
    source = tmp_path / "source.xls"
    source.write_text(_workbook(), encoding="utf-8")

    result = convert_workbook(source)

    document = OdmDocument.model_validate(result.document)
    mdv = document.study.meta_data_version
    assert document.study.protocol_name == "TEST"
    assert [row.name for row in mdv.forms] == ["Demographics"]
    assert mdv.items[0].code_list_oid == "CL.DSEX"
    assert mdv.study_events[0].form_refs[0].oid == "F.DM"
    screening = next(event for event in mdv.study_events if event.name == "Screening")
    assert screening.extensions[AURINARA_EXTENSION]["definitionKind"] == "visit"
    extension = mdv.extensions[AURINARA_EXTENSION]
    assert extension["schedule"] == "DEFAULT"
    assert result.report["valid"] is True


def test_maps_subject_matrix_column_without_requiring_a_subject_folder(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xls"
    workbook = _workbook().replace(
        "<Data ss:Type='String'>SCR</Data></Cell></Row>\n"
        "  <Row><Cell><Data ss:Type='String'>DM</Data></Cell>",
        "<Data ss:Type='String'>Subject</Data></Cell></Row>\n"
        "  <Row><Cell><Data ss:Type='String'>DM</Data></Cell>",
    )
    source.write_text(workbook, encoding="utf-8")

    result = convert_workbook(source)

    events = result.document["study"]["metaDataVersion"]["studyEvents"]
    subject = next(event for event in events if event["name"] == "Subject")
    assert subject["formRefs"] == [{"oid": "F.DM", "mandatory": True, "orderNumber": 1}]
    screening = next(event for event in events if event["name"] == "Screening")
    assert screening["extensions"][AURINARA_EXTENSION]["definitionKind"] == "folder"


def test_fails_closed_for_unresolved_checks(tmp_path: Path) -> None:
    source = tmp_path / "source.xls"
    source.write_text(_workbook(include_check=True), encoding="utf-8")

    with pytest.raises(ConversionError, match="Unresolved executable metadata"):
        convert_workbook(source)

    result = convert_workbook(source, unresolved_rules="omit")
    assert result.report["omitted"] == {"checks": 1}


def test_converts_supported_rave_edit_check_to_ingestible_v2_rule(tmp_path: Path) -> None:
    source = tmp_path / "source.xls"
    workbook = _workbook()
    workbook = workbook.replace(
        "<Worksheet ss:Name='Checks'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row></Table></Worksheet>",
        """<Worksheet ss:Name='Checks'><Table>
  <Row><Cell><Data ss:Type='String'>CheckName</Data></Cell><Cell><Data ss:Type='String'>CheckActive</Data></Cell><Cell><Data ss:Type='String'>Infix</Data></Cell><Cell><Data ss:Type='String'>NeedsRetesting</Data></Cell><Cell><Data ss:Type='String'>RetestingReason</Data></Cell><Cell><Data ss:Type='String'>OID</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell><Cell><Data ss:Type='String'>TRUE</Data></Cell><Cell><Data ss:Type='String'>If SEX equals 1 then open a query</Data></Cell><Cell><Data ss:Type='String'>FALSE</Data></Cell><Cell/><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell></Row>
 </Table></Worksheet>""",
    )
    workbook = workbook.replace(
        "<Worksheet ss:Name='CheckSteps'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row></Table></Worksheet>",
        """<Worksheet ss:Name='CheckSteps'><Table>
  <Row><Cell><Data ss:Type='String'>CheckName</Data></Cell><Cell><Data ss:Type='String'>StepOrdinal</Data></Cell><Cell><Data ss:Type='String'>CheckFunction</Data></Cell><Cell><Data ss:Type='String'>StaticValue</Data></Cell><Cell><Data ss:Type='String'>DataFormat</Data></Cell><Cell><Data ss:Type='String'>VariableOID</Data></Cell><Cell><Data ss:Type='String'>FolderOID</Data></Cell><Cell><Data ss:Type='String'>FormOID</Data></Cell><Cell><Data ss:Type='String'>FieldOID</Data></Cell><Cell><Data ss:Type='String'>RecordPosition</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell/><Cell/><Cell><Data ss:Type='String'>CodedValue</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>SCR</Data></Cell><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>0</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell><Cell><Data ss:Type='String'>2</Data></Cell><Cell/><Cell><Data ss:Type='String'>1</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell><Cell><Data ss:Type='String'>3</Data></Cell><Cell><Data ss:Type='String'>IsEqualTo</Data></Cell></Row>
 </Table></Worksheet>""",
    )
    workbook = workbook.replace(
        "<Worksheet ss:Name='CheckActions'><Table><Row><Cell><Data ss:Type='String'>CheckName</Data></Cell></Row></Table></Worksheet>",
        """<Worksheet ss:Name='CheckActions'><Table>
  <Row><Cell><Data ss:Type='String'>CheckName</Data></Cell><Cell><Data ss:Type='String'>FolderOID</Data></Cell><Cell><Data ss:Type='String'>FormOID</Data></Cell><Cell><Data ss:Type='String'>FieldOID</Data></Cell><Cell><Data ss:Type='String'>VariableOID</Data></Cell><Cell><Data ss:Type='String'>RecordPosition</Data></Cell><Cell><Data ss:Type='String'>ActionType</Data></Cell><Cell><Data ss:Type='String'>ActionString</Data></Cell><Cell><Data ss:Type='String'>ActionOptions</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM_SEX_QUERY</Data></Cell><Cell><Data ss:Type='String'>SCR</Data></Cell><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>SEX</Data></Cell><Cell><Data ss:Type='String'>0</Data></Cell><Cell><Data ss:Type='String'>OpenQuery</Data></Cell><Cell><Data ss:Type='String'>Please verify sex.</Data></Cell><Cell><Data ss:Type='String'>Site from System</Data></Cell></Row>
 </Table></Worksheet>""",
    )
    source.write_text(workbook, encoding="utf-8")

    result = convert_workbook(source)

    assert result.report["converted"] == {"checks": 1}
    condition = result.document["study"]["metaDataVersion"]["conditions"][0]
    assert condition["expression"]["schemaVersion"] == 2
    assert condition["expression"]["condition"] == {
        "operator": "==",
        "field": {
            "itemOID": "I.DM.SEX",
            "studyEventOID": "SE.SCR",
            "formOID": "F.DM",
            "itemGroupOID": "IG.DM",
            "repeat": "current",
        },
        "value": 1,
        "children": [],
    }
    assert condition["expression"]["actions"][0]["type"] == "open_query"
    assert condition["extensions"][AURINARA_EXTENSION]["needsRetesting"] is True


def test_maps_uncoded_rave_controls_without_false_codelist_requirements(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xls"
    extra_fields = """
  <Row><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>CONSENT</Data></Cell><Cell><Data ss:Type='String'>2</Data></Cell><Cell ss:Index='5'><Data ss:Type='String'>CONSENT</Data></Cell><Cell><Data ss:Type='String'>TRUE</Data></Cell><Cell><Data ss:Type='String'>CONSENT</Data></Cell><Cell><Data ss:Type='String'>1</Data></Cell><Cell/><Cell ss:Index='12'><Data ss:Type='String'>CheckBox</Data></Cell><Cell ss:Index='15'><Data ss:Type='String'>Consent confirmed</Data></Cell><Cell ss:Index='20'><Data ss:Type='String'>FALSE</Data></Cell><Cell ss:Index='25'><Data ss:Type='String'>FALSE</Data></Cell></Row>
  <Row><Cell><Data ss:Type='String'>DM</Data></Cell><Cell><Data ss:Type='String'>AEREF</Data></Cell><Cell><Data ss:Type='String'>3</Data></Cell><Cell ss:Index='5'><Data ss:Type='String'>AEREF</Data></Cell><Cell><Data ss:Type='String'>TRUE</Data></Cell><Cell><Data ss:Type='String'>AEREF</Data></Cell><Cell><Data ss:Type='String'>$200</Data></Cell><Cell/><Cell ss:Index='12'><Data ss:Type='String'>Dynamic SearchList</Data></Cell><Cell ss:Index='15'><Data ss:Type='String'>Related AE identifier</Data></Cell><Cell ss:Index='20'><Data ss:Type='String'>FALSE</Data></Cell><Cell ss:Index='25'><Data ss:Type='String'>FALSE</Data></Cell></Row>
"""
    source.write_text(_workbook(extra_field_rows=extra_fields), encoding="utf-8")

    result = convert_workbook(source)
    items = {item["name"]: item for item in result.document["study"]["metaDataVersion"]["items"]}

    assert items["CONSENT"]["dataType"] == "boolean"
    assert items["CONSENT"].get("codeListOID") is None
    assert items["CONSENT"]["extensions"][AURINARA_EXTENSION]["controlType"] == "boolean"
    assert items["AEREF"].get("codeListOID") is None
    assert items["AEREF"]["extensions"][AURINARA_EXTENSION]["controlType"] == "text"
    assert (
        items["AEREF"]["extensions"][AURINARA_EXTENSION]["sourceControlType"]
        == "Dynamic SearchList"
    )
    assert any(
        "Mapped 1 Dynamic SearchList field" in warning for warning in result.report["warnings"]
    )
