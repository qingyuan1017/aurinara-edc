"""Unit coverage for the safe edit-check JSON DSL."""

from datetime import date

import pytest

from app.core.edit_check_dsl import (
    RuleValidationError,
    evaluate_rule,
    parse_rule,
    validate_rule,
)


class TestRuleValidation:
    def test_valid_boolean_tree_is_canonicalized(self):
        rule = {
            "and": [
                {"field": "age", "operator": ">=", "value": 18},
                {
                    "not": {
                        "field": "status",
                        "operator": "in",
                        "value": ["withdrawn", "screen_failed"],
                    }
                },
            ]
        }

        parsed = parse_rule(rule)

        assert parsed == rule
        assert parsed is not rule

    @pytest.mark.parametrize(
        "rule",
        [
            {},
            {"xor": []},
            {"and": []},
            {"not": [{"field": "a", "operator": "is_null"}, {"field": "b", "operator": "is_null"}]},
            {"field": "a"},
            {"field": "a", "operator": "run", "value": "__import__('os')"},
            {"field": "a", "operator": "=="},
            {"field": "a", "operator": "==", "value": 1, "value_field": "b"},
            {"field": "a", "operator": "is_null", "value": None},
            {"field": "a", "operator": "in", "value": "not-a-list"},
            {"field": "a", "operator": "matches", "value": "["},
            {"field": "a", "operator": "within_days", "value": -1},
        ],
    )
    def test_rejects_unsupported_or_malformed_rules(self, rule):
        with pytest.raises(RuleValidationError):
            validate_rule(rule)

    def test_json_text_is_supported_but_not_executed(self):
        rule = '{"field":"name","operator":"matches","value":".*"}'
        assert validate_rule(rule)["operator"] == "matches"


class TestRuleEvaluation:
    @pytest.mark.parametrize(
        ("rule", "data", "expected"),
        [
            ({"field": "a", "operator": "is_null"}, {}, True),
            ({"field": "a", "operator": "not_null"}, {"a": 0}, True),
            ({"field": "a", "operator": "==", "value": 2}, {"a": 2}, True),
            ({"field": "a", "operator": "!=", "value": 2}, {"a": 3}, True),
            ({"field": "a", "operator": ">", "value": 2}, {"a": 3}, True),
            ({"field": "a", "operator": ">=", "value": 3}, {"a": 3}, True),
            ({"field": "a", "operator": "<", "value": 4}, {"a": 3}, True),
            ({"field": "a", "operator": "<=", "value": 3}, {"a": 3}, True),
            ({"field": "a", "operator": "in", "value": [1, 3]}, {"a": 3}, True),
            ({"field": "a", "operator": "not_in", "value": [1, 2]}, {"a": 3}, True),
            ({"field": "name", "operator": "matches", "value": r"AE-[0-9]+"}, {"name": "AE-12"}, True),
            ({"field": "start", "operator": "before", "value_field": "end"}, {"start": "2024-01-01", "end": "2024-01-02"}, True),
            ({"field": "end", "operator": "after", "value": "2024-01-01"}, {"end": date(2024, 1, 2)}, True),
            ({"field": "day", "operator": "within_days", "value": 3}, {"day": -2}, True),
            ({"field": "start", "operator": "within_days", "value_field": "end"}, {"start": "2024-01-01", "end": "2024-01-02"}, True),
        ],
    )
    def test_fixed_operators(self, rule, data, expected):
        assert evaluate_rule(rule, data) is expected

    def test_boolean_tree_and_dotted_fields(self):
        rule = {
            "or": [
                {"field": "demographics.age", "operator": "<", "value": 18},
                {
                    "and": [
                        {"field": "demographics.age", "operator": ">=", "value": 18},
                        {"field": "consent", "operator": "==", "value": True},
                    ]
                },
            ]
        }
        assert evaluate_rule(rule, {"demographics": {"age": 18}, "consent": True}) is True

    def test_value_field_and_missing_values_fail_closed(self):
        rule = {"field": "left", "operator": "==", "value_field": "right"}
        assert evaluate_rule(rule, {"left": 1, "right": 1}) is True
        assert evaluate_rule(rule, {"left": 1}) is False
        assert evaluate_rule({"field": "x", "operator": "matches", "value": ".*"}, {"x": 42}) is False

    def test_regex_is_anchored_and_input_is_never_executed(self):
        rule = {"field": "value", "operator": "matches", "value": "safe|other"}
        assert evaluate_rule(rule, {"value": "unsafe"}) is False
        assert evaluate_rule(
            {"field": "value", "operator": "==", "value": "__import__('os').system('boom')"},
            {"value": "__import__('os').system('boom')"},
        ) is True

    def test_invalid_runtime_rule_is_rejected_before_evaluation(self):
        with pytest.raises(RuleValidationError):
            evaluate_rule({"field": "value", "operator": "exec", "value": "x"}, {})
