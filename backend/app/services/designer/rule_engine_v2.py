"""Side-effect-free v2 rule evaluation and derivation helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.edit_check_dsl import evaluate_rule, validate_rule


@dataclass(frozen=True)
class RuleOutcome:
    matched: bool
    actions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DerivationSpec:
    target_item_oid: str
    expression: Mapping[str, Any]
    execution_order: int = 100


@dataclass(frozen=True)
class ActionExecutionResult:
    values: dict[str, Any]
    directives: tuple[dict[str, Any], ...]
    commands: tuple[dict[str, Any], ...]


def evaluate_rule_outcome(rule: Mapping[str, Any], context: Mapping[str, Any]) -> RuleOutcome:
    canonical = validate_rule(rule)
    matched = evaluate_rule(canonical, context)
    actions = tuple(canonical.get("actions", ())) if matched else ()
    return RuleOutcome(matched=matched, actions=actions)


def evaluate_derivation(expression: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
    """Evaluate the bounded, declarative derivation AST without executing code."""
    if "field" in expression:
        return context.get(str(expression["field"]))
    if "value" in expression:
        return expression["value"]
    function = expression.get("function")
    arguments = [evaluate_derivation(arg, context) for arg in expression.get("arguments", [])]
    if function == "add":
        return arguments[0] + arguments[1]
    if function == "subtract":
        return arguments[0] - arguments[1]
    if function == "multiply":
        return arguments[0] * arguments[1]
    if function == "divide":
        return arguments[0] / arguments[1]
    if function == "concat":
        return "".join("" if value is None else str(value) for value in arguments)
    if function == "space":
        return " "
    if function == "now":
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if function == "date_add":
        return (date.fromisoformat(str(arguments[0])) + timedelta(days=int(arguments[1]))).isoformat()
    if function == "date_diff":
        return (date.fromisoformat(str(arguments[0])) - date.fromisoformat(str(arguments[1]))).days
    if function == "age":
        born = date.fromisoformat(str(arguments[0]))
        at = date.fromisoformat(str(arguments[1]))
        return at.year - born.year - ((at.month, at.day) < (born.month, born.day))
    raise ValueError(f"Unsupported derivation function: {function}")


def validate_derivation_expression(expression: Mapping[str, Any]) -> set[str]:
    """Validate the bounded derivation AST and return referenced field OIDs."""
    keys = {key for key in ("field", "value", "function") if key in expression}
    if len(keys) != 1:
        raise ValueError("A derivation node must contain exactly one of field, value, or function")
    if "field" in expression:
        if not isinstance(expression["field"], str) or not expression["field"]:
            raise ValueError("A derivation field reference must be a non-empty string")
        return {expression["field"]}
    if "value" in expression:
        return set()
    function = expression["function"]
    arguments = expression.get("arguments", [])
    arity = {
        "add": 2,
        "subtract": 2,
        "multiply": 2,
        "divide": 2,
        "concat": None,
        "space": 0,
        "now": 0,
        "date_add": 2,
        "date_diff": 2,
        "age": 2,
    }
    if function not in arity or not isinstance(arguments, list):
        raise ValueError(f"Unsupported derivation function: {function}")
    if arity[function] is not None and len(arguments) != arity[function]:
        raise ValueError(f"{function} requires {arity[function]} arguments")
    references: set[str] = set()
    for argument in arguments:
        if not isinstance(argument, Mapping):
            raise ValueError("Derivation arguments must be expression objects")
        references.update(validate_derivation_expression(argument))
    return references


def evaluate_derivation_plan(
    definitions: Iterable[DerivationSpec], context: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate derivations in dependency order and reject cycles/missing inputs."""
    pending = list(definitions)
    targets = [definition.target_item_oid for definition in pending]
    if len(targets) != len(set(targets)):
        raise ValueError("Only one active derivation may target an item")
    working = dict(context)
    updates: dict[str, Any] = {}
    while pending:
        ready = [
            definition
            for definition in pending
            if not (
                validate_derivation_expression(definition.expression)
                & (set(targets) - set(working))
            )
        ]
        if not ready:
            raise ValueError("Derivation dependency cycle detected")
        ready.sort(key=lambda row: (row.execution_order, row.target_item_oid))
        for definition in ready:
            references = validate_derivation_expression(definition.expression)
            missing = references - set(working)
            if missing:
                raise ValueError(
                    f"Derivation references unavailable item(s): {', '.join(sorted(missing))}"
                )
            value = evaluate_derivation(definition.expression, working)
            working[definition.target_item_oid] = value
            updates[definition.target_item_oid] = value
            pending.remove(definition)
    return updates


async def execute_rule_actions(
    actions: Iterable[Mapping[str, Any]],
    values: MutableMapping[str, Any],
    *,
    command_handler: Callable[[Mapping[str, Any]], Awaitable[None]] | None = None,
) -> ActionExecutionResult:
    """Execute typed actions sequentially without committing the caller's transaction."""
    original = dict(values)
    directives: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    mutation_types = {"set_value", "clear_value"}
    directive_types = {
        "show",
        "hide",
        "enable",
        "disable",
        "require",
        "make_optional",
        "configure_search_list",
    }
    command_types = {
        "open_query",
        "close_query",
        "set_subject_status",
        "send_notification",
    }
    try:
        for source in actions:
            action = dict(source)
            action_type = action.get("type")
            target = action.get("target") or {}
            item_oid = target.get("itemOID") if isinstance(target, Mapping) else None
            if action_type in mutation_types:
                if not item_oid:
                    raise ValueError(f"{action_type} requires a target item")
                values[item_oid] = action.get("value") if action_type == "set_value" else None
            elif action_type in directive_types:
                directives.append(action)
            elif action_type in command_types:
                if command_handler is None:
                    raise ValueError(f"{action_type} requires a transactional command handler")
                await command_handler(action)
                commands.append(action)
            else:
                raise ValueError(f"Unsupported rule action: {action_type}")
    except Exception:
        values.clear()
        values.update(original)
        raise
    return ActionExecutionResult(values=dict(values), directives=tuple(directives), commands=tuple(commands))


__all__ = [
    "ActionExecutionResult",
    "DerivationSpec",
    "RuleOutcome",
    "evaluate_derivation",
    "evaluate_derivation_plan",
    "evaluate_rule_outcome",
    "execute_rule_actions",
    "validate_derivation_expression",
]
