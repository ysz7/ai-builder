"""Work out a sum, without letting a model do the arithmetic."""

from __future__ import annotations

import ast
import operator

_OPERATIONS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression: `calculate("2 * (3 + 4)")`.

    Parsed rather than `eval`ed, because the argument comes from a model and `eval` on a
    model's output is somebody else's shell.
    """
    try:
        return str(_value(ast.parse(expression, mode="eval").body))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as failure:
        return f"that is not arithmetic I can do: {failure}"


def _value(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_value(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATIONS:
        return float(_OPERATIONS[type(node.op)](_value(node.left), _value(node.right)))
    raise ValueError("only + - * / ** on numbers")
