"""Property 8: ICSR round-trip serialization.

Feature: pv-safety-module, Task 4.4
**Validates: Requirements 9, 16**

*For any* generated reportable Safety_Case and E2B field map (including
structurally invalid messages):

  1. For every valid produced message, parsing then producing yields an
     equivalent ``E2B_Message`` in the case identifier, every mandatory field,
     and the ``Coding_Dictionary_Versions`` used, and the parsed representation
     agrees with the source case on those same values (Requirement 9.1, 9.3,
     9.5).
  2. A structurally invalid message produces a descriptive parse error carrying
     the sanitized ``PV_E2B_INVALID_MESSAGE`` reason and creates no
     Safety_Case, i.e. ``parse_e2b`` returns nothing and raises (Requirements
     9.4, 16 sanitized error mapping).

``produce_e2b`` and ``parse_e2b`` are pure, deterministic functions with no I/O
and no database, so the property exercises them directly. No external service is
used and each property runs at least 100 generated examples.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.exceptions import ValidationError
from app.services.regulatory_reporting_service import (
    E2B_MANDATORY_FIELDS,
)
from app.services.regulatory_reporting_service import (
    regulatory_reporting_service as svc,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty scalar text that survives the produce/parse round-trip. The
# serializer stores values as XML text, so we constrain to printable text whose
# stripped form is non-empty (empty-after-strip counts as a missing mandatory
# field, which is exercised separately below). Control characters that XML
# cannot represent are excluded.
_field_value = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x24F,
        blacklist_categories=("Cs",),
    ),
    min_size=1,
    max_size=40,
).map(str.strip).filter(lambda s: s != "")

# Case identifiers share the same non-empty text shape.
_case_identifier = _field_value

# Dictionary names and versions for the Coding_Dictionary_Versions block.
_dictionary_name = st.sampled_from(["MedDRA", "WHODrug", "ICD10", "SNOMED"])
_dictionary_version = _field_value
_dictionary_versions = st.dictionaries(
    keys=_dictionary_name,
    values=_dictionary_version,
    max_size=4,
)


@st.composite
def _reportable_case(draw: st.DrawFn) -> dict:
    """A reportable Safety_Case representation with every mandatory field."""

    case: dict = {
        "case_identifier": draw(_case_identifier),
        "dictionary_versions": draw(_dictionary_versions),
    }
    for field in E2B_MANDATORY_FIELDS:
        case[field] = draw(_field_value)
    return case


# All keys required by ``produce_e2b``: the case identifier plus the mandatory
# fields. Dropping any one of them yields a structurally incomplete case.
_ALL_REQUIRED_KEYS: tuple[str, ...] = ("case_identifier", *E2B_MANDATORY_FIELDS)


def _normalize_versions(versions: dict) -> dict:
    """Coerce dictionary versions to their serialized string form."""

    return {str(name): str(value) for name, value in versions.items()}


# ---------------------------------------------------------------------------
# Property: valid round-trip preserves identifier, mandatory fields, versions
# ---------------------------------------------------------------------------


@given(case=_reportable_case())
@settings(max_examples=200, deadline=None, derandomize=True)
def test_valid_message_round_trips_equivalently(case: dict) -> None:
    """produce -> parse -> produce yields an equivalent E2B_Message.

    The rebuilt message equals the first, and the parsed representation agrees
    with the source case on the case identifier, every mandatory field, and the
    Coding_Dictionary_Versions (Requirements 9.1, 9.3, 9.5).
    """

    first_message = svc.produce_e2b(case)
    parsed = svc.parse_e2b(first_message)

    # Parsed representation agrees with the source case on the invariant fields.
    assert parsed["case_identifier"] == str(case["case_identifier"])
    for field in E2B_MANDATORY_FIELDS:
        assert parsed[field] == str(case[field])
    assert parsed["dictionary_versions"] == _normalize_versions(
        case["dictionary_versions"]
    )

    # Producing again from the parsed representation reproduces the message.
    rebuilt_case = {
        "case_identifier": parsed["case_identifier"],
        "dictionary_versions": parsed["dictionary_versions"],
    }
    for field in E2B_MANDATORY_FIELDS:
        rebuilt_case[field] = parsed[field]
    second_message = svc.produce_e2b(rebuilt_case)

    assert second_message == first_message

    # Parsing the rebuilt message yields an equivalent representation.
    reparsed = svc.parse_e2b(second_message)
    assert reparsed == parsed


# ---------------------------------------------------------------------------
# Property: a structurally invalid message is rejected and creates no case
# ---------------------------------------------------------------------------


@st.composite
def _structurally_invalid_message(draw: st.DrawFn) -> str:
    """Produce an E2B message that is structurally invalid in some way."""

    case = draw(_reportable_case())
    kind = draw(
        st.sampled_from(
            [
                "empty",
                "not_xml",
                "wrong_root",
                "missing_report",
                "missing_case_id",
                "missing_mandatory",
            ]
        )
    )

    if kind == "empty":
        return draw(st.sampled_from(["", "   ", "\n\t "]))
    if kind == "not_xml":
        # Well-started but never closed / not well-formed XML.
        return draw(
            st.sampled_from(
                [
                    "<ichicsr><safetyreport>",
                    "<ichicsr><safetyreport></ichicsr>",
                    "not xml at all",
                    "<<>>",
                ]
            )
        )
    if kind == "wrong_root":
        return "<other><safetyreport/></other>"
    if kind == "missing_report":
        return "<ichicsr></ichicsr>"

    # Build a valid message, then remove a required element to make it invalid.
    valid = svc.produce_e2b(case)
    if kind == "missing_case_id":
        import xml.etree.ElementTree as ET

        root = ET.fromstring(valid)
        report = root.find("safetyreport")
        assert report is not None
        case_id = report.find("safetyreportid")
        assert case_id is not None
        report.remove(case_id)
        return ET.tostring(root, encoding="unicode")

    # missing_mandatory: drop one mandatory field element.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(valid)
    report = root.find("safetyreport")
    assert report is not None
    field = draw(st.sampled_from(E2B_MANDATORY_FIELDS))
    element = report.find(field)
    assert element is not None
    report.remove(element)
    return ET.tostring(root, encoding="unicode")


@given(message=_structurally_invalid_message())
@settings(max_examples=200, deadline=None, derandomize=True)
def test_structurally_invalid_message_is_rejected(message: str) -> None:
    """A structurally invalid message raises a descriptive parse error.

    The error carries the sanitized ``PV_E2B_INVALID_MESSAGE`` reason and no
    Safety_Case representation is produced (Requirements 9.4, 16).
    """

    with pytest.raises(ValidationError) as exc:
        svc.parse_e2b(message)
    assert exc.value.details["reason"] == "PV_E2B_INVALID_MESSAGE"
    # A descriptive detail accompanies the reason without leaking internals.
    assert isinstance(exc.value.details.get("detail"), str)
    assert exc.value.details["detail"] != ""


# ---------------------------------------------------------------------------
# Property: an incomplete case cannot be produced and names the missing fields
# ---------------------------------------------------------------------------


@given(
    case=_reportable_case(),
    dropped=st.sampled_from(_ALL_REQUIRED_KEYS),
)
@settings(max_examples=150, deadline=None, derandomize=True)
def test_incomplete_case_names_missing_fields_and_produces_nothing(
    case: dict, dropped: str
) -> None:
    """produce_e2b rejects a case missing a mandatory field, naming it.

    No message is produced when a mandatory field (or the case identifier) is
    absent, and the error names the missing field (Requirement 9.2).
    """

    del case[dropped]
    with pytest.raises(ValidationError) as exc:
        svc.produce_e2b(case)
    assert dropped in exc.value.details["missing_fields"]
