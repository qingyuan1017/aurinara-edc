"""Example-based unit tests for PV ICSR/E2B(R3) produce and parse.

Covers Requirement 9.1-9.5 for the pure ``produce_e2b``/``parse_e2b`` functions:
producing a reportable case, naming missing mandatory fields, parsing a valid
message, rejecting a structurally invalid message, and the produce->parse->produce
round-trip invariant. These functions are pure, so the tests need no database.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from app.core.exceptions import ValidationError
from app.services.regulatory_reporting_service import (
    E2B_MANDATORY_FIELDS,
)
from app.services.regulatory_reporting_service import (
    regulatory_reporting_service as svc,
)


def _complete_case() -> dict:
    """A reportable Safety_Case representation with every mandatory field."""

    case = {
        "case_identifier": "PV-CASE-0001",
        "dictionary_versions": {"MedDRA": "27.0", "WHODrug": "2024-MAR"},
    }
    for field in E2B_MANDATORY_FIELDS:
        case[field] = f"value-{field}"
    # Give a couple of fields realistic values.
    case["reaction_onset_date"] = "2024-01-15"
    case["seriousness"] = "serious"
    return case


class TestProduceE2B:
    def test_produces_wellformed_xml_with_case_identifier(self) -> None:
        message = svc.produce_e2b(_complete_case())
        root = ET.fromstring(message)
        assert root.tag == "ichicsr"
        report = root.find("safetyreport")
        assert report is not None
        assert report.findtext("safetyreportid") == "PV-CASE-0001"

    def test_produces_every_mandatory_field(self) -> None:
        message = svc.produce_e2b(_complete_case())
        report = ET.fromstring(message).find("safetyreport")
        assert report is not None
        for field in E2B_MANDATORY_FIELDS:
            assert report.find(field) is not None, f"missing {field} in produced message"

    def test_produces_dictionary_versions(self) -> None:
        message = svc.produce_e2b(_complete_case())
        parsed = svc.parse_e2b(message)
        assert parsed["dictionary_versions"] == {"MedDRA": "27.0", "WHODrug": "2024-MAR"}

    def test_missing_case_identifier_is_rejected_and_named(self) -> None:
        case = _complete_case()
        del case["case_identifier"]
        with pytest.raises(ValidationError) as exc:
            svc.produce_e2b(case)
        assert "case_identifier" in exc.value.details["missing_fields"]

    def test_missing_mandatory_fields_are_all_named(self) -> None:
        case = _complete_case()
        del case["reaction_verbatim"]
        del case["suspect_product"]
        with pytest.raises(ValidationError) as exc:
            svc.produce_e2b(case)
        missing = exc.value.details["missing_fields"]
        assert "reaction_verbatim" in missing
        assert "suspect_product" in missing

    def test_empty_string_field_counts_as_missing(self) -> None:
        case = _complete_case()
        case["seriousness"] = "   "
        with pytest.raises(ValidationError) as exc:
            svc.produce_e2b(case)
        assert "seriousness" in exc.value.details["missing_fields"]

    def test_produce_does_not_mutate_input(self) -> None:
        case = _complete_case()
        before = dict(case)
        svc.produce_e2b(case)
        assert case == before

    def test_produce_is_deterministic(self) -> None:
        case = _complete_case()
        assert svc.produce_e2b(case) == svc.produce_e2b(dict(case))


class TestParseE2B:
    def test_parses_valid_message(self) -> None:
        message = svc.produce_e2b(_complete_case())
        parsed = svc.parse_e2b(message)
        assert parsed["case_identifier"] == "PV-CASE-0001"
        for field in E2B_MANDATORY_FIELDS:
            assert field in parsed

    def test_empty_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            svc.parse_e2b("   ")
        assert exc.value.details["reason"] == "PV_E2B_INVALID_MESSAGE"

    def test_malformed_xml_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            svc.parse_e2b("<ichicsr><safetyreport>")

    def test_wrong_root_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            svc.parse_e2b("<other/>")

    def test_missing_case_identifier_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            svc.parse_e2b("<ichicsr><safetyreport></safetyreport></ichicsr>")

    def test_missing_mandatory_field_is_rejected(self) -> None:
        # Well-formed with a case identifier but no mandatory fields.
        message = (
            "<ichicsr><safetyreport>"
            "<safetyreportid>PV-CASE-0002</safetyreportid>"
            "</safetyreport></ichicsr>"
        )
        with pytest.raises(ValidationError):
            svc.parse_e2b(message)


class TestRoundTrip:
    def test_produce_parse_produce_is_stable(self) -> None:
        """Requirement 9.5: produce -> parse -> produce yields an equivalent message."""

        first = svc.produce_e2b(_complete_case())
        parsed = svc.parse_e2b(first)
        rebuilt_case = {
            "case_identifier": parsed["case_identifier"],
            "dictionary_versions": parsed["dictionary_versions"],
        }
        for field in E2B_MANDATORY_FIELDS:
            rebuilt_case[field] = parsed[field]
        second = svc.produce_e2b(rebuilt_case)
        assert first == second

    def test_round_trip_preserves_identifier_fields_and_versions(self) -> None:
        message = svc.produce_e2b(_complete_case())
        first = svc.parse_e2b(message)
        second = svc.parse_e2b(svc.produce_e2b(dict(first, **{
            "case_identifier": first["case_identifier"],
        }) | {f: first[f] for f in E2B_MANDATORY_FIELDS}))
        assert first["case_identifier"] == second["case_identifier"]
        assert first["dictionary_versions"] == second["dictionary_versions"]
        for field in E2B_MANDATORY_FIELDS:
            assert first[field] == second[field]
