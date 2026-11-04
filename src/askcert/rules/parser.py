"""Rule documents (dict / JSON-compatible) <-> AST."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any as AnyValue

from ..exceptions import RuleError
from .ast import All, Any, Const, Expr, Implies, Not, Ref, Xor, children
from .validation import MAX_DEPTH, check_name

_LIST_OPS = ("all", "any", "xor")
_OPERATORS = ("not", "implies", *_LIST_OPS)
_ENTRY_KEYS = frozenset({"name", "p", "op", "conditions", "exceptions"})


def parse_expr(spec: object, rule: str = "?") -> Expr:
    """Parse one expression (bool, ``"name"``, ``"!name"``, operator dict or AST node).

    Errors are :class:`RuleError` mentioning ``rule``.
    """
    try:
        return _parse(spec, 0, rule)
    except RecursionError:
        raise RuleError(f"rule {rule!r}: expression nested too deeply (limit {MAX_DEPTH})") from None


def _parse(spec: object, depth: int, rule: str) -> Expr:
    if type(spec) is bool:
        return Const(spec)
    if isinstance(spec, str):
        if not spec.startswith("!"):
            return _ref(spec, rule)
        _enter(depth, rule)
        return Not(_ref(spec[1:], rule))
    if isinstance(spec, Mapping):
        _enter(depth, rule)
        return _parse_node(spec, depth + 1, rule)
    if isinstance(spec, (Const, Ref, Not, All, Any, Xor, Implies)):
        _check_ast_depth(spec, MAX_DEPTH - depth, rule)
        return spec
    raise RuleError(f"rule {rule!r}: invalid expression {spec!r} (expected bool, string or operator object)")


def _enter(depth: int, rule: str) -> None:
    if depth >= MAX_DEPTH:
        raise RuleError(f"rule {rule!r}: expression nested deeper than {MAX_DEPTH} levels")


def _ref(name: str, rule: str) -> Ref:
    try:
        return Ref(name)
    except RuleError as exc:
        raise RuleError(f"rule {rule!r}: {exc}") from None


def _items(value: object, op: str, rule: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise RuleError(f"rule {rule!r}: operand of {op!r} must be a list, got {type(value).__name__}")
    return list(value)


def _parse_node(node: Mapping[AnyValue, AnyValue], depth: int, rule: str) -> Expr:
    ops = [key for key in node if key in _OPERATORS]
    extra = [key for key in node if key not in _OPERATORS and key != "unless"]
    if extra:
        raise RuleError(f"rule {rule!r}: unknown key {extra[0]!r}")
    if len(ops) != 1:
        found = ", ".join(map(repr, ops)) or "none"
        raise RuleError(f"rule {rule!r}: an expression needs exactly one operator key, found {found}")
    op = ops[0]
    if "unless" in node and op not in ("all", "any"):
        raise RuleError(f"rule {rule!r}: 'unless' is only allowed with 'all' or 'any'")
    if op == "not":
        return Not(_parse(node["not"], depth, rule))
    # Plain loops (no comprehension frames) keep the recursion cost at two frames per level.
    args: list[Expr] = []
    for item in _items(node[op], op, rule):
        args.append(_parse(item, depth, rule))
    if op == "implies":
        if len(args) != 2:
            raise RuleError(f"rule {rule!r}: 'implies' takes exactly 2 operands, got {len(args)}")
        return Implies(args[0], args[1])
    if op == "xor":
        return Xor(tuple(args))
    unless: list[Expr] = []
    for item in _items(node.get("unless", []), "unless", rule):
        unless.append(_parse(item, depth, rule))
    return All(tuple(args), tuple(unless)) if op == "all" else Any(tuple(args), tuple(unless))


def _check_ast_depth(expr: Expr, limit: int, rule: str) -> None:
    """Iterative depth check for pre-built AST nodes (operators count, leaves do not)."""
    stack = [(expr, 0)]
    while stack:
        node, depth = stack.pop()
        kids = children(node)
        if not isinstance(node, (Const, Ref)):
            depth += 1
            if depth > limit:
                raise RuleError(f"rule {rule!r}: expression nested deeper than {MAX_DEPTH} levels")
        stack.extend((kid, depth) for kid in kids)


def parse_flat_rules(entries: object) -> dict[str, Expr]:
    """Flat-list form ``[{"name"|"p": ..., "op": "ALL"|"ANY", "conditions": [...], "exceptions": [...]}]``."""
    if not isinstance(entries, (list, tuple)):
        raise RuleError(f"'rules' must be an object or a list, got {type(entries).__name__}")
    rules: dict[str, Expr] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RuleError(f"flat rule entries must be objects, got {type(entry).__name__}")
        unknown = sorted(str(key) for key in entry if key not in _ENTRY_KEYS)
        if unknown:
            raise RuleError(f"flat rule entry has unknown key {unknown[0]!r}")
        if "name" in entry and "p" in entry:
            raise RuleError("flat rule entry has both 'name' and 'p'")
        name = check_name(entry["name"] if "name" in entry else entry.get("p"), "rule name")
        if name in rules:
            raise RuleError(f"Duplicate rule name {name!r}")
        op = entry.get("op", "ANY")
        if op not in ("ALL", "ANY"):
            raise RuleError(f"rule {name!r}: op must be 'ALL' or 'ANY', got {op!r}")
        parts = []
        for key in ("conditions", "exceptions"):
            items = entry.get(key, [])
            if not isinstance(items, (list, tuple)) or not all(isinstance(i, str) for i in items):
                raise RuleError(f"rule {name!r}: '{key}' must be a list of strings")
            parts.append(tuple(_parse(item, 0, name) for item in items))
        rules[name] = All(*parts) if op == "ALL" else Any(*parts)
    return rules


def expr_to_dict(expr: Expr) -> bool | str | dict[str, AnyValue]:
    """Canonical JSON-compatible form: bools, bare names, ``{"not": e}``, operand lists."""
    match expr:
        case Const(value):
            return value
        case Ref(name):
            return name
        case Not(arg):
            return {"not": expr_to_dict(arg)}
        case Implies(left, right):
            return {"implies": [expr_to_dict(left), expr_to_dict(right)]}
        case Xor(args):
            return {"xor": [expr_to_dict(a) for a in args]}
        case All(args, unless) | Any(args, unless):
            key = "all" if isinstance(expr, All) else "any"
            out: dict[str, AnyValue] = {key: [expr_to_dict(a) for a in args]}
            if unless:
                out["unless"] = [expr_to_dict(a) for a in unless]
            return out
    raise AssertionError(expr)  # pragma: no cover - Expr is closed
