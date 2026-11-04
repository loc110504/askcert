"""Validated, immutable rule sets."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any as AnyValue

from ..exceptions import RuleError
from ..serialization import SCHEMA_VERSION, dumps, load_json
from .ast import Expr, Ref, children
from .parser import expr_to_dict, parse_expr, parse_flat_rules
from .validation import check_name, check_references, topological_order

_DOCUMENT_KEYS = ("schema_version", "atoms", "rules")


def _references(expr: Expr) -> tuple[str, ...]:
    """Distinct referenced names in order of first occurrence."""
    seen: dict[str, None] = {}
    stack = [expr]
    while stack:
        node = stack.pop()
        if isinstance(node, Ref):
            seen.setdefault(node.name)
        else:
            stack.extend(reversed(children(node)))
    return tuple(seen)


class RuleSet:
    """Finite, acyclic Boolean rules over base atoms.

    A *rule* is a named expression; a *base atom* is any other referenced name (or a declared
    one). If ``atoms`` is given the set is *strict*: every name that is not a rule must be
    declared. Instances are immutable; equality is on ``(rules, declared_atoms)``.
    """

    def __init__(
        self,
        rules: Mapping[str, Expr | Mapping[str, AnyValue] | str | bool],
        atoms: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(rules, Mapping):
            raise RuleError(f"rules must be a mapping of name -> expression, got {type(rules).__name__}")
        parsed: dict[str, Expr] = {}
        for name, spec in rules.items():
            check_name(name, "rule name")
            parsed[name] = parse_expr(spec, name)
        declared = self._normalize_atoms(atoms, parsed)
        deps = {name: _references(expr) for name, expr in parsed.items()}
        check_references(deps, declared)
        self._order = topological_order(deps)
        self._deps = deps
        self._rules = parsed
        self._declared = declared
        referenced = {ref for refs in deps.values() for ref in refs if ref not in parsed}
        self._atoms = tuple(sorted(referenced.union(declared or ())))
        self._atom_set = frozenset(self._atoms)
        self._cones: dict[str, tuple[str, ...]] = {}

    @staticmethod
    def _normalize_atoms(atoms: Iterable[str] | None, rules: Mapping[str, Expr]) -> tuple[str, ...] | None:
        if atoms is None:
            return None
        if isinstance(atoms, (str, bytes)):
            raise RuleError("atoms must be an iterable of names, not a string")
        names = [check_name(a, "atom name") for a in atoms]
        for name in names:
            if name in rules:
                raise RuleError(f"{name!r} is declared as an atom but also defined as a rule")
        if len(set(names)) != len(names):
            dup = next(n for n in names if names.count(n) > 1)
            raise RuleError(f"duplicate declared atom {dup!r}")
        return tuple(sorted(names))

    @classmethod
    def from_dict(cls, spec: Mapping[str, AnyValue]) -> RuleSet:
        """Build from a document (``{"schema_version", "atoms", "rules"}``), the shorthand
        (a bare ``name -> expression`` mapping) or a document whose ``rules`` is the flat list form."""
        if not isinstance(spec, Mapping):
            raise RuleError(f"rule document must be an object, got {type(spec).__name__}")
        if "rules" not in spec:
            return cls(spec)
        for key in spec:
            if key not in _DOCUMENT_KEYS:
                raise RuleError(f"unknown top-level key {key!r}")
        if "schema_version" in spec and (
            type(spec["schema_version"]) is not str or spec["schema_version"] != SCHEMA_VERSION
        ):
            raise RuleError(f"unsupported schema_version {spec['schema_version']!r}; expected '1'")
        atoms = None
        if "atoms" in spec:
            atoms = spec["atoms"]
            if not isinstance(atoms, (list, tuple)):
                raise RuleError("'atoms' must be a list of names")
        body = spec["rules"]
        return cls(body if isinstance(body, Mapping) else parse_flat_rules(body), atoms)

    @classmethod
    def from_json(cls, text: str) -> RuleSet:
        """Like :meth:`from_dict` on JSON text; duplicate object keys are an error."""
        return cls.from_dict(load_json(text, "rules"))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> RuleSet:
        """Read a UTF-8 (BOM tolerated) JSON file."""
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RuleError(f"{os.fspath(path)}: not valid UTF-8") from exc
        return cls.from_json(text)

    @property
    def rules(self) -> Mapping[str, Expr]:
        """Read-only ``name -> expression``, in definition order."""
        return MappingProxyType(self._rules)

    @property
    def atoms(self) -> tuple[str, ...]:
        """All base atoms (declared plus referenced non-rule names), sorted."""
        return self._atoms

    @property
    def declared_atoms(self) -> tuple[str, ...] | None:
        """Sorted declared atoms, or ``None`` if the rule set is not strict."""
        return self._declared

    def rule_order(self) -> tuple[str, ...]:
        """All rule names, dependencies first (a topological order)."""
        return self._order

    def cone_rules(self, goal: str) -> tuple[str, ...]:
        """Rules reachable from ``goal`` (itself included), dependencies first."""
        reached = self._reach(goal)[0]
        return tuple(rule for rule in self._order if rule in reached)

    def cone(self, goal: str) -> tuple[str, ...]:
        """Sorted base atoms reachable from ``goal`` (the goal itself if it is an atom)."""
        atoms = self._cones.get(goal) if isinstance(goal, str) else None
        if atoms is None:
            atoms = self._cones[goal] = tuple(sorted(self._reach(goal)[1]))
        return atoms

    def _reach(self, goal: str) -> tuple[set[str], set[str]]:
        if not isinstance(goal, str) or not (goal in self._rules or goal in self._atom_set):
            raise RuleError(f"unknown goal {goal!r}")
        reached: set[str] = set()
        atoms: set[str] = set()
        stack = [goal]
        while stack:
            name = stack.pop()
            if name not in self._rules:
                atoms.add(name)
            elif name not in reached:
                reached.add(name)
                stack.extend(self._deps[name])
        return reached, atoms

    def to_dict(self) -> dict[str, AnyValue]:
        """Canonical JSON-compatible document; ``from_dict(rs.to_dict()) == rs``."""
        doc: dict[str, AnyValue] = {"schema_version": SCHEMA_VERSION}
        if self._declared is not None:
            doc["atoms"] = list(self._declared)
        doc["rules"] = {name: expr_to_dict(expr) for name, expr in self._rules.items()}
        return doc

    def to_json(self, **json_kwargs: AnyValue) -> str:
        """:meth:`to_dict` as JSON text (``json_kwargs`` go to ``json.dumps``)."""
        return dumps(self.to_dict(), **json_kwargs)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuleSet):
            return NotImplemented
        return self._rules == other._rules and self._declared == other._declared

    def __hash__(self) -> int:
        return hash((frozenset(self._rules.items()), self._declared))

    def __repr__(self) -> str:
        def show(names: Sequence[str]) -> str:
            more = ", ..." if len(names) > 5 else ""
            return "[" + ", ".join(map(repr, names[:5])) + more + "]"

        return f"RuleSet(rules={show(tuple(self._rules))}, atoms={show(self._atoms)})"
