"""Compile rule expressions to backend nodes and read a status off a node."""

from __future__ import annotations

from collections.abc import Callable

from ..backends.base import FALSE, TRUE, Backend
from ..models import Status
from ..rules.ast import All, Any, Const, Expr, Implies, Not, Ref, Xor


def status_of(node: int) -> Status:
    """TRUE/FALSE iff the (restricted) function is the constant 1/0, else UNKNOWN."""
    return Status.TRUE if node == TRUE else Status.FALSE if node == FALSE else Status.UNKNOWN


def compile_expr(backend: Backend, expr: Expr, resolve: Callable[[str], int]) -> int:
    """Node of ``expr``; ``resolve`` maps a referenced rule/atom name to its node."""
    match expr:
        case Const(value):
            return TRUE if value else FALSE
        case Ref(name):
            return resolve(name)
        case Not(arg):
            return backend.negate(compile_expr(backend, arg, resolve))
        case Implies(left, right):
            return backend.apply_or(
                backend.negate(compile_expr(backend, left, resolve)), compile_expr(backend, right, resolve)
            )
        case Xor(args):
            return _fold(backend, backend.apply_xor, FALSE, args, resolve)
        case All(args, unless):
            node = _fold(backend, backend.apply_and, TRUE, args, resolve)
            return _except(backend, node, unless, resolve)
        case Any(args, unless):
            node = _fold(backend, backend.apply_or, FALSE, args, resolve)
            return _except(backend, node, unless, resolve)
    raise AssertionError(expr)  # pragma: no cover - Expr is closed


def _fold(
    backend: Backend,
    op: Callable[[int, int], int],
    unit: int,
    args: tuple[Expr, ...],
    resolve: Callable[[str], int],
) -> int:
    """Combine operands deepest-top-variable first.

    The result is the same canonical node in any order, but folding bottom-up lets each step add
    nodes above the accumulated diagram instead of rebuilding it; e.g. ``any`` over n atoms creates
    O(n) intermediate nodes instead of O(n^2).
    """
    nodes = [compile_expr(backend, arg, resolve) for arg in args]
    node = unit
    for child in sorted(nodes, key=backend.level, reverse=True):
        node = op(node, child)
    return node


def _except(backend: Backend, node: int, unless: tuple[Expr, ...], resolve: Callable[[str], int]) -> int:
    """``node AND NOT any(unless)``."""
    if not unless:
        return node
    excluded = _fold(backend, backend.apply_or, FALSE, unless, resolve)
    return backend.apply_and(node, backend.negate(excluded))
