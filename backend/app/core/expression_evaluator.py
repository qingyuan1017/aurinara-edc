"""Safe expression evaluator for calculated fields and edit checks.

Evaluates declarative arithmetic/comparison expressions without executing
arbitrary user-provided code. Uses Python's `ast` module to parse and walk
the expression tree, rejecting anything not in a strict allowlist.

Allowed constructs:
- Arithmetic operators: +, -, *, /, **, %, //
- Comparison operators: <, >, <=, >=, ==, !=
- Boolean operators: and, or, not
- Parentheses (grouping)
- Numeric literals (int, float)
- String literals (for comparisons)
- Boolean literals (True, False)
- None literal
- Field references (bare names resolved from context)

Disallowed (raises ExpressionError):
- Function calls
- Imports
- Attribute access
- Subscripts (indexing)
- Assignments
- Comprehensions
- Lambda, yield, await
- Any statement (only expressions allowed)
"""

import ast
import math
import operator
from typing import Any


class ExpressionError(Exception):
    """Raised when an expression is invalid or uses disallowed constructs."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


# Mapping of AST binary operator nodes to Python operator functions
_BINARY_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

# Mapping of AST unary operator nodes to Python operator functions
_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

# Mapping of AST comparison operator nodes to Python operator functions
_COMPARE_OPS: dict[type, Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def validate_expression(expression: str) -> bool:
    """Validate that an expression is safe to evaluate.

    Returns True if the expression only uses allowed constructs.
    Returns False if the expression is invalid or uses disallowed constructs.
    """
    try:
        _validate_ast(expression)
        return True
    except ExpressionError:
        return False


def evaluate_expression(expression: str, context: dict[str, Any]) -> Any:
    """Evaluate a safe arithmetic/comparison expression.

    Args:
        expression: The expression string (e.g., "weight / (height / 100) ** 2").
        context: A dict mapping field names to their values
                 (e.g., {"weight": 85.0, "height": 178.0}).

    Returns:
        The computed result.

    Raises:
        ExpressionError: If the expression is invalid, uses disallowed constructs,
                         or references undefined fields.
    """
    tree = _validate_ast(expression)
    return _eval_node(tree, context)


def _validate_ast(expression: str) -> ast.expr:
    """Parse and validate an expression, returning the AST expression node.

    Raises ExpressionError if the expression is syntactically invalid or
    uses disallowed constructs.
    """
    if not expression or not expression.strip():
        raise ExpressionError("Expression cannot be empty")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(
            f"Invalid expression syntax: {e.msg}",
            details={"line": e.lineno, "offset": e.offset},
        ) from e

    # Walk the tree and validate every node
    _check_node(tree.body)
    return tree.body


def _check_node(node: ast.AST) -> None:
    """Recursively validate that an AST node uses only allowed constructs."""
    match node:
        # Numeric and string literals
        case ast.Constant(value=v) if isinstance(v, (int, float, str, bool, type(None))):
            return

        # Field references (bare names)
        case ast.Name():
            return

        # Binary operations: a + b, a * b, etc.
        case ast.BinOp(op=op) if type(op) in _BINARY_OPS:
            _check_node(node.left)  # type: ignore[attr-defined]
            _check_node(node.right)  # type: ignore[attr-defined]
            return

        # Unary operations: -x, +x, not x
        case ast.UnaryOp(op=op) if type(op) in _UNARY_OPS:
            _check_node(node.operand)  # type: ignore[attr-defined]
            return

        # Comparisons: a < b, a == b, chained comparisons
        case ast.Compare():
            compare_node: ast.Compare = node  # type: ignore[assignment]
            for op in compare_node.ops:
                if type(op) not in _COMPARE_OPS:
                    raise ExpressionError(
                        f"Disallowed comparison operator: {type(op).__name__}",
                        details={"node_type": type(op).__name__},
                    )
            _check_node(compare_node.left)
            for comparator in compare_node.comparators:
                _check_node(comparator)
            return

        # Boolean operations: a and b, a or b
        case ast.BoolOp():
            bool_node: ast.BoolOp = node  # type: ignore[assignment]
            for value in bool_node.values:
                _check_node(value)
            return

        # Ternary: a if condition else b
        case ast.IfExp():
            ifexp_node: ast.IfExp = node  # type: ignore[assignment]
            _check_node(ifexp_node.test)
            _check_node(ifexp_node.body)
            _check_node(ifexp_node.orelse)
            return

        # Everything else is disallowed
        case ast.Call():
            raise ExpressionError(
                "Function calls are not allowed in expressions",
                details={"node_type": "Call"},
            )

        case ast.Attribute():
            raise ExpressionError(
                "Attribute access is not allowed in expressions",
                details={"node_type": "Attribute"},
            )

        case ast.Subscript():
            raise ExpressionError(
                "Subscript/indexing is not allowed in expressions",
                details={"node_type": "Subscript"},
            )

        case ast.Import() | ast.ImportFrom():
            raise ExpressionError(
                "Imports are not allowed in expressions",
                details={"node_type": "Import"},
            )

        case _:
            raise ExpressionError(
                f"Disallowed construct: {type(node).__name__}",
                details={"node_type": type(node).__name__},
            )


def _eval_node(node: ast.AST, context: dict[str, Any]) -> Any:
    """Recursively evaluate an already-validated AST node."""
    match node:
        case ast.Constant(value=v):
            return v

        case ast.Name(id=name):
            if name == "True":
                return True
            if name == "False":
                return False
            if name == "None":
                return None
            if name not in context:
                raise ExpressionError(
                    f"Undefined field: '{name}'",
                    details={"field": name},
                )
            return context[name]

        case ast.BinOp(left=left, right=right, op=op):
            left_val = _eval_node(left, context)
            right_val = _eval_node(right, context)
            if left_val is None or right_val is None:
                return None
            op_func = _BINARY_OPS[type(op)]
            try:
                result = op_func(left_val, right_val)
            except ZeroDivisionError:
                return math.nan
            except OverflowError:
                return math.inf
            return result

        case ast.UnaryOp(op=op, operand=operand):
            operand_val = _eval_node(operand, context)
            if operand_val is None and not isinstance(op, ast.Not):
                return None
            op_func = _UNARY_OPS[type(op)]
            return op_func(operand_val)

        case ast.Compare(left=left, ops=ops, comparators=comparators):
            left_val = _eval_node(left, context)
            for op, comparator in zip(ops, comparators, strict=True):
                right_val = _eval_node(comparator, context)
                if left_val is None or right_val is None:
                    return None
                op_func = _COMPARE_OPS[type(op)]
                if not op_func(left_val, right_val):
                    return False
                left_val = right_val
            return True

        case ast.BoolOp(op=ast.And(), values=values):
            for value in values:
                result = _eval_node(value, context)
                if not result:
                    return result
            return result  # type: ignore[possibly-undefined]

        case ast.BoolOp(op=ast.Or(), values=values):
            for value in values:
                result = _eval_node(value, context)
                if result:
                    return result
            return result  # type: ignore[possibly-undefined]

        case ast.IfExp(test=test, body=body, orelse=orelse):
            if _eval_node(test, context):
                return _eval_node(body, context)
            return _eval_node(orelse, context)

        case _:  # pragma: no cover
            raise ExpressionError(
                f"Cannot evaluate node: {type(node).__name__}",
                details={"node_type": type(node).__name__},
            )
