"""Tests for the safe expression evaluator.

Covers: basic arithmetic, BMI calculation, division by zero handling,
rejection of function calls, rejection of imports, rejection of attribute access.
"""

import math

import pytest

from app.core.expression_evaluator import (
    ExpressionError,
    evaluate_expression,
    validate_expression,
)

# ---------------------------------------------------------------------------
# Basic arithmetic
# ---------------------------------------------------------------------------


class TestBasicArithmetic:
    def test_addition(self):
        assert evaluate_expression("a + b", {"a": 3, "b": 5}) == 8

    def test_subtraction(self):
        assert evaluate_expression("a - b", {"a": 10, "b": 4}) == 6

    def test_multiplication(self):
        assert evaluate_expression("a * b", {"a": 7, "b": 6}) == 42

    def test_division(self):
        assert evaluate_expression("a / b", {"a": 10, "b": 4}) == 2.5

    def test_floor_division(self):
        assert evaluate_expression("a // b", {"a": 10, "b": 3}) == 3

    def test_modulo(self):
        assert evaluate_expression("a % b", {"a": 10, "b": 3}) == 1

    def test_power(self):
        assert evaluate_expression("a ** b", {"a": 2, "b": 10}) == 1024

    def test_negative_unary(self):
        assert evaluate_expression("-a", {"a": 5}) == -5

    def test_positive_unary(self):
        assert evaluate_expression("+a", {"a": 5}) == 5

    def test_complex_expression(self):
        result = evaluate_expression("(a + b) * c - d", {"a": 2, "b": 3, "c": 4, "d": 1})
        assert result == 19

    def test_numeric_literals(self):
        assert evaluate_expression("x + 10", {"x": 5}) == 15

    def test_float_literals(self):
        assert evaluate_expression("x * 1.5", {"x": 4}) == 6.0

    def test_parentheses_grouping(self):
        assert evaluate_expression("(a + b) * (c - d)", {"a": 1, "b": 2, "c": 5, "d": 3}) == 6


# ---------------------------------------------------------------------------
# BMI calculation
# ---------------------------------------------------------------------------


class TestBMICalculation:
    def test_bmi_formula(self):
        # BMI = weight / (height_m) ** 2, with height in cm
        result = evaluate_expression(
            "weight / (height / 100) ** 2",
            {"weight": 85.0, "height": 178.0},
        )
        expected = 85.0 / (178.0 / 100) ** 2
        assert abs(result - expected) < 1e-10

    def test_bmi_normal_weight(self):
        result = evaluate_expression(
            "weight / (height / 100) ** 2",
            {"weight": 70.0, "height": 175.0},
        )
        assert 18.5 < result < 25.0  # normal BMI range

    def test_bmi_underweight(self):
        result = evaluate_expression(
            "weight / (height / 100) ** 2",
            {"weight": 45.0, "height": 170.0},
        )
        assert result < 18.5


# ---------------------------------------------------------------------------
# Division by zero handling
# ---------------------------------------------------------------------------


class TestDivisionByZero:
    def test_division_by_zero_returns_nan(self):
        result = evaluate_expression("a / b", {"a": 10, "b": 0})
        assert math.isnan(result)

    def test_floor_division_by_zero_returns_nan(self):
        result = evaluate_expression("a // b", {"a": 10, "b": 0})
        assert math.isnan(result)

    def test_modulo_by_zero_returns_nan(self):
        result = evaluate_expression("a % b", {"a": 10, "b": 0})
        assert math.isnan(result)


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


class TestComparisons:
    def test_less_than(self):
        assert evaluate_expression("a < b", {"a": 3, "b": 5}) is True

    def test_greater_than(self):
        assert evaluate_expression("a > b", {"a": 10, "b": 5}) is True

    def test_less_equal(self):
        assert evaluate_expression("a <= b", {"a": 5, "b": 5}) is True

    def test_greater_equal(self):
        assert evaluate_expression("a >= b", {"a": 3, "b": 5}) is False

    def test_equal(self):
        assert evaluate_expression("a == b", {"a": 7, "b": 7}) is True

    def test_not_equal(self):
        assert evaluate_expression("a != b", {"a": 3, "b": 5}) is True

    def test_chained_comparison(self):
        assert evaluate_expression("a < b < c", {"a": 1, "b": 5, "c": 10}) is True


# ---------------------------------------------------------------------------
# Boolean operations
# ---------------------------------------------------------------------------


class TestBooleanOperations:
    def test_and(self):
        assert evaluate_expression("a > 0 and b > 0", {"a": 5, "b": 3}) is True

    def test_or(self):
        assert evaluate_expression("a > 10 or b > 0", {"a": 5, "b": 3}) is True

    def test_not(self):
        assert evaluate_expression("not a", {"a": False}) is True


# ---------------------------------------------------------------------------
# None / null handling
# ---------------------------------------------------------------------------


class TestNullHandling:
    def test_none_in_arithmetic_returns_none(self):
        result = evaluate_expression("a + b", {"a": 5, "b": None})
        assert result is None

    def test_none_in_comparison_returns_none(self):
        result = evaluate_expression("a < b", {"a": None, "b": 5})
        assert result is None


# ---------------------------------------------------------------------------
# Ternary / conditional expressions
# ---------------------------------------------------------------------------


class TestConditionalExpressions:
    def test_ternary_true(self):
        result = evaluate_expression("a if a > 0 else 0", {"a": 5})
        assert result == 5

    def test_ternary_false(self):
        result = evaluate_expression("a if a > 0 else 0", {"a": -3})
        assert result == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_valid_arithmetic(self):
        assert validate_expression("a + b * c") is True

    def test_valid_comparison(self):
        assert validate_expression("a >= b") is True

    def test_valid_bmi(self):
        assert validate_expression("weight / (height / 100) ** 2") is True

    def test_empty_expression(self):
        assert validate_expression("") is False

    def test_whitespace_only(self):
        assert validate_expression("   ") is False

    def test_syntax_error(self):
        assert validate_expression("a +") is False


# ---------------------------------------------------------------------------
# Rejection of function calls
# ---------------------------------------------------------------------------


class TestRejectFunctionCalls:
    def test_rejects_builtin_call(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("abs(x)", {"x": -5})

    def test_rejects_print(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("print(x)", {"x": 1})

    def test_rejects_eval(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("eval('1+1')", {})

    def test_rejects_exec(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("exec('import os')", {})

    def test_rejects_open(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("open('/etc/passwd')", {})

    def test_validate_rejects_function_call(self):
        assert validate_expression("len(x)") is False


# ---------------------------------------------------------------------------
# Rejection of imports
# ---------------------------------------------------------------------------


class TestRejectImports:
    def test_rejects_import_via_call(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("__import__('os')", {})

    def test_validate_rejects_import_construct(self):
        # 'import os' is a statement, not an expression, so it's a syntax error
        assert validate_expression("import os") is False


# ---------------------------------------------------------------------------
# Rejection of attribute access
# ---------------------------------------------------------------------------


class TestRejectAttributeAccess:
    def test_rejects_attribute_access(self):
        with pytest.raises(ExpressionError, match="Attribute access is not allowed"):
            evaluate_expression("x.__class__", {"x": 1})

    def test_rejects_dunder_access(self):
        with pytest.raises(ExpressionError, match="Attribute access is not allowed"):
            evaluate_expression("x.__class__.__mro__", {"x": 1})

    def test_rejects_method_call(self):
        with pytest.raises(ExpressionError, match="Function calls are not allowed"):
            evaluate_expression("x.bit_length()", {"x": 5})

    def test_validate_rejects_attribute(self):
        assert validate_expression("x.__class__") is False


# ---------------------------------------------------------------------------
# Rejection of subscript/indexing
# ---------------------------------------------------------------------------


class TestRejectSubscript:
    def test_rejects_subscript(self):
        with pytest.raises(ExpressionError, match="Subscript/indexing is not allowed"):
            evaluate_expression("x[0]", {"x": [1, 2, 3]})

    def test_validate_rejects_subscript(self):
        assert validate_expression("x[0]") is False


# ---------------------------------------------------------------------------
# Undefined field references
# ---------------------------------------------------------------------------


class TestUndefinedFields:
    def test_raises_on_undefined_field(self):
        with pytest.raises(ExpressionError, match="Undefined field"):
            evaluate_expression("a + b", {"a": 5})

    def test_error_includes_field_name(self):
        with pytest.raises(ExpressionError) as exc_info:
            evaluate_expression("missing_field + 1", {})
        assert exc_info.value.details["field"] == "missing_field"
