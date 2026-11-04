"""Immutable, hashable expression nodes. Structural equality; construction validates its fields."""

from __future__ import annotations

from dataclasses import dataclass

from ..exceptions import RuleError
from .validation import check_name


def _exprs(items: object, what: str) -> tuple[Expr, ...]:
    if not isinstance(items, (tuple, list)):
        raise RuleError(f"{what} must be a list of expressions, got {type(items).__name__}")
    for item in items:
        _expr(item, what)
    return tuple(items)


def _expr(item: object, what: str) -> Expr:
    if not isinstance(item, _NODE_TYPES):
        raise RuleError(f"{what} must be an expression node, got {type(item).__name__}")
    return item


@dataclass(frozen=True, slots=True)
class Const:
    """Boolean constant."""

    value: bool

    def __post_init__(self) -> None:
        if type(self.value) is not bool:
            raise RuleError(f"constant must be a bool, got {self.value!r}")


@dataclass(frozen=True, slots=True)
class Ref:
    """Reference to a rule or a base atom."""

    name: str

    def __post_init__(self) -> None:
        check_name(self.name, "reference")


@dataclass(frozen=True, slots=True)
class Not:
    """Classical negation."""

    arg: Expr

    def __post_init__(self) -> None:
        _expr(self.arg, "not operand")


@dataclass(frozen=True, slots=True)
class All:
    """Conjunction (empty is TRUE) of ``args``, AND NOT any of ``unless``."""

    args: tuple[Expr, ...]
    unless: tuple[Expr, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", _exprs(self.args, "all operands"))
        object.__setattr__(self, "unless", _exprs(self.unless, "unless operands"))


@dataclass(frozen=True, slots=True)
class Any:
    """Disjunction (empty is FALSE) of ``args``, AND NOT any of ``unless``."""

    args: tuple[Expr, ...]
    unless: tuple[Expr, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", _exprs(self.args, "any operands"))
        object.__setattr__(self, "unless", _exprs(self.unless, "unless operands"))


@dataclass(frozen=True, slots=True)
class Xor:
    """Odd parity of ``args`` (empty is FALSE)."""

    args: tuple[Expr, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", _exprs(self.args, "xor operands"))


@dataclass(frozen=True, slots=True)
class Implies:
    """``NOT left OR right``."""

    left: Expr
    right: Expr

    def __post_init__(self) -> None:
        _expr(self.left, "implies operand")
        _expr(self.right, "implies operand")


Expr = Const | Ref | Not | All | Any | Xor | Implies
_NODE_TYPES = (Const, Ref, Not, All, Any, Xor, Implies)


def children(expr: Expr) -> tuple[Expr, ...]:
    """Direct sub-expressions in left-to-right order (``unless`` operands last)."""
    match expr:
        case Const() | Ref():
            return ()
        case Not(arg):
            return (arg,)
        case All(args, unless) | Any(args, unless):
            return args + unless
        case Xor(args):
            return args
        case Implies(left, right):
            return (left, right)
    raise AssertionError(expr)  # pragma: no cover - Expr is closed
