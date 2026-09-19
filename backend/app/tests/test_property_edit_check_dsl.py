"""Property-based coverage for the safe edit-check JSON DSL.

# Feature: clinical-edc-system, Property 23: Edit-check rule serialization round-trip and safe evaluation
**Validates: Requirements 12.1, 12.7**
"""

from __future__ import annotations

import json
import re
from datetime import date
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.edit_check_dsl import (
    CONDITION_OPERATORS,
    RuleValidationError,
    evaluate_rule,
    validate_rule,
)

_FIELD_NAMES = ("age", "status", "name", "start", "end", "score", "code")
_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-100, max_value=100),
    st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=20),
)
_DATE_TEXT = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)).map(
    lambda value: value.isoformat()
)
_REGEX_PATTERNS = st.sampled_from(
    (r"safe", r"AE-[0-9]{1,3}", r"[A-Z]{2}[0-9]{2}", r"yes|no", r"\d{2}")
)


@st.composite
def _condition_strategy(draw: st.DrawFn) -> dict[str, object]:
    """Generate a valid leaf condition for every supported operator family."""
    field = draw(st.sampled_from(_FIELD_NAMES))
    operator = draw(st.sampled_from(tuple(sorted(CONDITION_OPERATORS))))

    if operator in {"is_null", "not_null"}:
        return {"field": field, "operator": operator}
    if operator in {"in", "not_in"}:
        return {
            "field": field,
            "operator": operator,
            "value": draw(st.lists(_SCALAR, min_size=0, max_size=5)),
        }
    if operator == "matches":
        return {"field": field, "operator": operator, "value": draw(_REGEX_PATTERNS)}
    if operator in {"before", "after"}:
        return {"field": field, "operator": operator, "value": draw(_DATE_TEXT)}
    if operator == "within_days":
        return {
            "field": field,
            "operator": operator,
            "value": draw(st.integers(min_value=0, max_value=30)),
        }
    return {
        "field": field,
        "operator": operator,
        "value": draw(_SCALAR),
    }


_RULE = st.recursive(
    _condition_strategy(),
    lambda children: st.one_of(
        st.lists(children, min_size=1, max_size=3).map(lambda values: {"and": values}),
        st.lists(children, min_size=1, max_size=3).map(lambda values: {"or": values}),
        children.map(lambda value: {"not": value}),
    ),
    max_leaves=8,
)


@st.composite
def _property_case(draw: st.DrawFn) -> dict[str, object]:
    """Generate a DSL rule, arbitrary JSON-like input, and adversarial code."""
    return {
        "rule": draw(_RULE),
        "data": draw(st.dictionaries(st.sampled_from(_FIELD_NAMES), _SCALAR, max_size=len(_FIELD_NAMES))),
        "regex_pattern": draw(_REGEX_PATTERNS),
        "regex_value": draw(
            st.text(alphabet="AE-safe012yesnobox", max_size=20)
        ),
        "unsafe_operator": draw(st.sampled_from(("exec", "eval", "run", "call", "python", "__import__"))),
        "unsafe_code": draw(
            st.sampled_from(
                (
                    "__import__('os').system('touch /tmp/edc-pbt-should-not-run')",
                    "open('/tmp/edc-pbt-should-not-run', 'w').write('x')",
                    "__import__('subprocess').run(['true'])",
                )
            )
        ),
    }


class TestEditCheckDslProperties:
    """Hypothesis properties for rule persistence shape and safe evaluation."""

    @settings(max_examples=150, deadline=None)
    @given(case=_property_case())
    def test_rules_round_trip_with_fixed_operators_and_never_execute_code(self, case):
        """Valid rules survive JSON persistence and unsafe rules fail closed.

        The generated rule covers the complete allowlisted operator set over
        the Hypothesis run. Regex evaluation is compared to ``fullmatch`` so a
        substring match cannot accidentally pass, and adversarial code is kept
        as data while an OS call is patched to prove it is never reached.
        """
        rule = case["rule"]
        data = case["data"]

        canonical = validate_rule(rule)
        persisted = json.loads(json.dumps(canonical, sort_keys=True))
        restored = validate_rule(persisted)

        assert set(_operators(restored)) <= CONDITION_OPERATORS
        assert restored == canonical
        assert evaluate_rule(restored, data) == evaluate_rule(canonical, data)
        assert isinstance(evaluate_rule(restored, data), bool)

        regex_rule = {
            "field": "code",
            "operator": "matches",
            "value": case["regex_pattern"],
        }
        expected_match = re.fullmatch(case["regex_pattern"], case["regex_value"]) is not None
        assert evaluate_rule(regex_rule, {"code": case["regex_value"]}) is expected_match

        unsafe_rule = {
            "field": "payload",
            "operator": case["unsafe_operator"],
            "value": case["unsafe_code"],
        }
        with patch("os.system") as system_call:
            with pytest.raises(RuleValidationError):
                evaluate_rule(unsafe_rule, {"payload": case["unsafe_code"]})
            system_call.assert_not_called()


def _operators(node: object):
    """Yield all leaf operators in a validated boolean tree."""
    if not isinstance(node, dict):
        return
    for boolean_operator in ("and", "or"):
        if boolean_operator in node:
            for child in node[boolean_operator]:
                yield from _operators(child)
            return
    if "not" in node:
        yield from _operators(node["not"])
        return
    yield node["operator"]
