"""Safe declarative edit-check JSON DSL.

The edit-check language is intentionally data-only.  It consists of boolean
nodes (``and``, ``or``, and ``not``) and leaf conditions.  No expression text,
Python, JavaScript, attribute access, or callable value is accepted.

The comparison operators that need ordinary scalar comparisons delegate to the
existing AST allowlisted evaluator.  This keeps the comparison semantics in one
safe implementation while the DSL itself remains a fixed, non-executable JSON
format.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Final, Literal

from app.core.exceptions import ValidationError
from app.core.expression_evaluator import ExpressionError, evaluate_expression

# Public constants are useful to schema/API callers and keep the allowlist
# discoverable without duplicating it in route code.
BOOLEAN_OPERATORS: Final[frozenset[str]] = frozenset({"and", "or", "not"})
CONDITION_OPERATORS: Final[frozenset[str]] = frozenset(
    {
        "is_null",
        "not_null",
        "==",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "not_in",
        "matches",
        "before",
        "after",
        "within_days",
    }
)
COMPARISON_OPERATORS: Final[frozenset[str]] = frozenset(
    {"==", "!=", ">", ">=", "<", "<=", "before", "after"}
)
VALUE_REQUIRED_OPERATORS: Final[frozenset[str]] = CONDITION_OPERATORS - {
    "is_null",
    "not_null",
}

# Keep regex evaluation bounded.  A regex is data, never executable code, but
# limiting its size prevents an unnecessarily expensive rule from being saved.
_MAX_REGEX_LENGTH = 512
_MAX_RULE_DEPTH = 32
_MAX_RULE_NODES = 256


class RuleValidationError(ValidationError):
    """Raised when a JSON rule is outside the supported DSL."""


def _error(message: str, path: str) -> RuleValidationError:
    return RuleValidationError(message, details={"path": path})


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _validate_json_value(value: Any, path: str) -> None:
    """Reject non-JSON values and recursively validate containers."""
    if _is_json_scalar(value):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise _error("Rule values must contain finite JSON numbers", path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error("Rule object keys must be strings", path)
            _validate_json_value(item, f"{path}.{key}")
        return
    raise _error("Rule values must be JSON-compatible", path)


def _validate_condition(node: Mapping[str, Any], path: str) -> dict[str, Any]:
    allowed = {"field", "operator", "value", "value_field"}
    unknown = set(node) - allowed
    if unknown:
        raise _error(f"Unknown condition keys: {sorted(unknown)}", path)

    if set(node) - {"field", "operator", "value", "value_field"}:
        raise _error("Invalid condition", path)
    field = node.get("field")
    if not isinstance(field, str) or not field.strip():
        raise _error("Condition field must be a non-empty string", f"{path}.field")

    operator = node.get("operator")
    if not isinstance(operator, str) or operator not in CONDITION_OPERATORS:
        raise _error(
            f"Unsupported condition operator; expected one of {sorted(CONDITION_OPERATORS)}",
            f"{path}.operator",
        )

    has_value = "value" in node
    has_value_field = "value_field" in node
    if operator in VALUE_REQUIRED_OPERATORS and has_value == has_value_field:
        raise _error(
            "Exactly one of 'value' or 'value_field' is required for this operator",
            path,
        )
    if operator in {"is_null", "not_null"} and (has_value or has_value_field):
        raise _error(f"Operator '{operator}' does not accept a comparison value", path)

    result: dict[str, Any] = {"field": field, "operator": operator}
    if has_value:
        value = node["value"]
        _validate_json_value(value, f"{path}.value")
        result["value"] = copy.deepcopy(value)
    if has_value_field:
        value_field = node["value_field"]
        if not isinstance(value_field, str) or not value_field.strip():
            raise _error("value_field must be a non-empty string", f"{path}.value_field")
        result["value_field"] = value_field

    if operator in {"in", "not_in"} and has_value and not isinstance(node["value"], list):
        raise _error(f"Operator '{operator}' requires a list value", f"{path}.value")
    if operator == "matches" and has_value:
        pattern = node["value"]
        if not isinstance(pattern, str):
            raise _error("Operator 'matches' requires a string regex", f"{path}.value")
        if len(pattern) > _MAX_REGEX_LENGTH:
            raise _error("Regex pattern is too long", f"{path}.value")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise _error(f"Invalid regex pattern: {exc}", f"{path}.value") from exc
    if operator == "within_days" and has_value:
        days = node["value"]
        if not isinstance(days, (int, float)) or isinstance(days, bool) or days < 0:
            raise _error(
                "Operator 'within_days' requires a non-negative number of days",
                f"{path}.value",
            )

    return result


def _validate_node(node: Any, path: str, depth: int, state: dict[str, int]) -> dict[str, Any]:
    if depth > _MAX_RULE_DEPTH:
        raise _error(f"Rule nesting exceeds {_MAX_RULE_DEPTH} levels", path)
    state["nodes"] += 1
    if state["nodes"] > _MAX_RULE_NODES:
        raise _error(f"Rule contains more than {_MAX_RULE_NODES} nodes", path)
    if not isinstance(node, Mapping):
        raise _error("Each rule node must be a JSON object", path)
    if not node:
        raise _error("Rule nodes cannot be empty", path)

    keys = set(node)
    boolean_keys = keys & BOOLEAN_OPERATORS
    if boolean_keys:
        if len(boolean_keys) != 1 or len(keys) != 1:
            raise _error("A boolean node must contain exactly one boolean key", path)
        operator = next(iter(boolean_keys))
        children = node[operator]
        if operator == "not":
            # ``not`` takes one object.  A one-item list is accepted as a
            # convenience for clients that serialize all boolean children as arrays.
            if isinstance(children, list):
                if len(children) != 1:
                    raise _error("'not' requires exactly one child", f"{path}.not")
                child = children[0]
            else:
                child = children
            return {"not": _validate_node(child, f"{path}.not", depth + 1, state)}
        if not isinstance(children, list) or not children:
            raise _error(f"'{operator}' requires a non-empty list of children", f"{path}.{operator}")
        return {
            operator: [
                _validate_node(child, f"{path}.{operator}[{index}]", depth + 1, state)
                for index, child in enumerate(children)
            ]
        }

    if "field" not in keys or "operator" not in keys:
        raise _error("A leaf node must contain 'field' and 'operator'", path)
    return _validate_condition(node, path)


def validate_rule(rule: Any) -> dict[str, Any]:
    """Validate and return a canonical, detached JSON DSL rule.

    Validation is deliberately independent of SQLAlchemy and can therefore be
    called before a model is constructed or persisted.  The returned value is a
    deep copy, so later mutation of a caller-owned input cannot alter a rule
    that has already been validated.
    """
    if isinstance(rule, str):
        try:
            rule = json.loads(rule)
        except json.JSONDecodeError as exc:
            raise RuleValidationError(
                "Rule must be a JSON object",
                details={"path": "$", "error": str(exc)},
            ) from exc
    return _validate_node(rule, "$", 0, {"nodes": 0})


def parse_rule(rule: Any) -> dict[str, Any]:
    """Alias for :func:`validate_rule` used by service/API callers."""
    return validate_rule(rule)


def _lookup(data: Any, field: str) -> Any:
    """Resolve a field from mappings using exact keys, then dotted paths."""
    if not isinstance(data, Mapping):
        return None
    if field in data:
        return data[field]
    current: Any = data
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _temporal(value: Any) -> date | datetime | None:
    if isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str):
        return None
    # Parse date-only values as dates so they compare cleanly with date fields.
    if "T" not in value and " " not in value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _temporal_pair(left: Any, right: Any) -> tuple[date | datetime, date | datetime] | None:
    left_temporal = _temporal(left)
    right_temporal = _temporal(right)
    if left_temporal is None or right_temporal is None:
        return None
    # Normalize a date to midnight when paired with a datetime.  This avoids
    # Python's incompatible date/datetime ordering and subtraction behavior.
    if isinstance(left_temporal, datetime) and isinstance(right_temporal, date) and not isinstance(right_temporal, datetime):
        right_temporal = datetime.combine(right_temporal, datetime.min.time(), tzinfo=left_temporal.tzinfo)
    elif isinstance(right_temporal, datetime) and isinstance(left_temporal, date) and not isinstance(left_temporal, datetime):
        left_temporal = datetime.combine(left_temporal, datetime.min.time(), tzinfo=right_temporal.tzinfo)
    return left_temporal, right_temporal


def _safe_compare(left: Any, operator: Literal["==", "!=", ">", ">=", "<", "<="], right: Any) -> bool:
    """Use the shared AST evaluator for scalar comparisons only."""
    try:
        result = evaluate_expression(
            f"left {operator} right", {"left": left, "right": right}
        )
    except (ExpressionError, TypeError, ValueError):
        return False
    return result is True


def _operand(condition: Mapping[str, Any], data: Mapping[str, Any]) -> tuple[bool, Any]:
    if "value_field" in condition:
        value = _lookup(data, condition["value_field"])
        return value is not None, value
    return True, condition.get("value")


def _evaluate_condition(condition: Mapping[str, Any], data: Mapping[str, Any]) -> bool:
    field_value = _lookup(data, condition["field"])
    operator = condition["operator"]
    if operator == "is_null":
        return field_value is None
    if operator == "not_null":
        return field_value is not None

    operand_exists, right = _operand(condition, data)
    if not operand_exists or field_value is None:
        return False

    if operator in COMPARISON_OPERATORS:
        if operator in {"before", "after"}:
            temporal_pair = _temporal_pair(field_value, right)
            if temporal_pair is None:
                return False
            left_value, right_value = temporal_pair
            comparison = "<" if operator == "before" else ">"
            return _safe_compare(left_value, comparison, right_value)  # type: ignore[arg-type]
        return _safe_compare(field_value, operator, right)  # type: ignore[arg-type]

    if operator in {"in", "not_in"}:
        if "value_field" in condition:
            if not isinstance(right, Sequence) or isinstance(right, (str, bytes, bytearray)):
                return False
            present = field_value in right
        else:
            present = field_value in right
        return present if operator == "in" else not present

    if operator == "matches":
        if not isinstance(field_value, str) or not isinstance(right, str):
            return False
        # fullmatch is intentionally used so every matches rule is anchored.
        try:
            return re.fullmatch(right, field_value) is not None
        except re.error:
            # Validated rules cannot reach this branch, but arbitrary runtime
            # data must never turn a malformed persisted rule into code execution.
            return False

    if operator == "within_days":
        if isinstance(right, (int, float)) and not isinstance(right, bool):
            if isinstance(field_value, (int, float)) and not isinstance(field_value, bool):
                return abs(field_value) <= right
            return False
        temporal_pair = _temporal_pair(field_value, right)
        if temporal_pair is None:
            return False
        left_temporal, right_temporal = temporal_pair
        try:
            return abs((left_temporal - right_temporal).total_seconds()) <= 86_400
        except TypeError:
            return False

    # validate_rule makes this unreachable; keep a defensive default for rules
    # loaded from legacy storage.
    return False


def evaluate_rule(rule: Any, data: Mapping[str, Any] | None = None) -> bool:
    """Safely evaluate a validated rule against JSON-like sample data.

    The rule is validated on every call so callers cannot bypass the schema by
    constructing a dictionary directly.  Evaluation only resolves mapping keys,
    performs allowlisted comparisons, and applies a compiled regular expression;
    it never evaluates text as Python or JavaScript.
    """
    canonical = validate_rule(rule)
    context = data if isinstance(data, Mapping) else {}
    return _evaluate_node(canonical, context)


def _evaluate_node(node: Mapping[str, Any], data: Mapping[str, Any]) -> bool:
    if "and" in node:
        return all(_evaluate_node(child, data) for child in node["and"])
    if "or" in node:
        return any(_evaluate_node(child, data) for child in node["or"])
    if "not" in node:
        return not _evaluate_node(node["not"], data)
    return _evaluate_condition(node, data)


# Friendly aliases used by service callers and external consumers.
evaluate = evaluate_rule
validate = validate_rule

__all__ = [
    "BOOLEAN_OPERATORS",
    "COMPARISON_OPERATORS",
    "CONDITION_OPERATORS",
    "RuleValidationError",
    "evaluate",
    "evaluate_rule",
    "parse_rule",
    "validate",
    "validate_rule",
]
