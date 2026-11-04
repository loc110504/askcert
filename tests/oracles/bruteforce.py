"""Independent brute-force oracle for AskCert (paper Sec. 3, definitions only).

This module NEVER imports askcert.  It parses the raw rule document itself
(document form, shorthand form, flat-list form) and answers every question by
literal enumeration of the completions Omega(K) over the goal's cone:

* ``Dec(g, K)``  TRUE / FALSE / UNKNOWN by enumerating Omega(K).
* ``Rel(g, K)``  atom ``a`` unknown and exists ``w`` in Omega(K) with
  ``f(w[a=0]) != f(w[a=1])``  (straight from the paper definition).
* subset-minimal certificate checks and the contract's deterministic
  lexicographic-deletion certificate.
* lexicographically smallest witnesses (what a False-branch-first DFS on an
  ROBDD ordered by sorted atom names must produce).

Statuses are returned as plain strings ``"TRUE" | "FALSE" | "UNKNOWN"`` so they
compare equal to ``askcert.Status`` members (a ``str`` enum).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping
from typing import Any

TRUE, FALSE, UNKNOWN = "TRUE", "FALSE", "UNKNOWN"
RESERVED = ("rules", "atoms", "schema_version")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OPERATORS = ("not", "all", "any", "xor", "implies")


# --------------------------------------------------------------------------- parsing


def normalize(spec: Any) -> tuple[list[str] | None, dict[str, Any]]:
    """Return ``(declared_atoms_or_None, {rule_name: raw_expression})``.

    Raw expressions keep the JSON shape (bool | str | dict).  The flat-list
    form is converted to ``{"all"/"any": conditions, "unless": exceptions}``.
    """
    if not isinstance(spec, Mapping):
        raise TypeError("oracle expects a mapping")
    declared = None
    if "rules" in spec:
        declared = list(spec["atoms"]) if "atoms" in spec else None
        body = spec["rules"]
    else:
        body = spec
    if isinstance(body, Mapping):
        return declared, dict(body)
    rules: dict[str, Any] = {}
    for item in body:  # flat-list form
        name = item["name"] if "name" in item else item["p"]
        op = item.get("op", "ANY")
        conds = list(item.get("conditions", []))
        excs = list(item.get("exceptions", []))
        expr: dict[str, Any] = {"all" if op == "ALL" else "any": conds}
        if excs:
            expr["unless"] = excs
        rules[name] = expr
    return declared, rules


def _refs(expr: Any) -> Iterable[str]:
    """Yield every referenced name (without the ``!`` prefix) in an expression."""
    if isinstance(expr, bool):
        return
    if isinstance(expr, str):
        yield expr[1:] if expr.startswith("!") else expr
    elif isinstance(expr, Mapping):
        for key, val in expr.items():
            if key == "not":
                yield from _refs(val)
            else:  # all / any / xor / implies / unless : lists of expressions
                for sub in val:
                    yield from _refs(sub)
    else:  # pragma: no cover - oracle only sees valid documents
        raise TypeError(f"bad expression {expr!r}")


class Oracle:
    """Parsed rule document with memoised truth-table evaluation."""

    def __init__(self, spec: Any) -> None:
        self.declared, self.rules = normalize(spec)
        referenced = {n for e in self.rules.values() for n in _refs(e)}
        self.atoms = sorted(({*referenced, *(self.declared or [])}) - set(self.rules))
        self._cone: dict[str, tuple[str, ...]] = {}
        self._table: dict[tuple[str, tuple[bool, ...]], bool] = {}

    # ---- structure
    def cone(self, goal: str) -> tuple[str, ...]:
        """Sorted base atoms reachable from ``goal`` (a rule name or an atom)."""
        if goal in self._cone:
            return self._cone[goal]
        if goal in self.rules:
            seen: set[str] = set()
            atoms: set[str] = set()
            stack = [goal]
            while stack:
                name = stack.pop()
                if name in seen:
                    continue
                seen.add(name)
                for ref in _refs(self.rules[name]):
                    if ref in self.rules:
                        stack.append(ref)
                    else:
                        atoms.add(ref)
            result = tuple(sorted(atoms))
        elif goal in self.atoms:
            result = (goal,)
        else:
            raise KeyError(f"unknown goal {goal!r}")
        self._cone[goal] = result
        return result

    # ---- evaluation of one complete world
    def evaluate(self, goal: str, world: Mapping[str, bool]) -> bool:
        """``f_goal(world)``; ``world`` must assign every cone atom."""
        memo: dict[str, bool] = {}

        def ref(name: str) -> bool:
            if name in self.rules:
                if name not in memo:
                    memo[name] = ev(self.rules[name])
                return memo[name]
            return bool(world[name])

        def ev(e: Any) -> bool:
            if isinstance(e, bool):
                return e
            if isinstance(e, str):
                return (not ref(e[1:])) if e.startswith("!") else ref(e)
            ops = [k for k in e if k in OPERATORS]
            assert len(ops) == 1, e
            op = ops[0]
            if op == "not":
                val = not ev(e["not"])
            elif op == "implies":
                left, right = e["implies"]
                val = (not ev(left)) or ev(right)
            elif op == "xor":
                val = sum(ev(x) for x in e["xor"]) % 2 == 1
            elif op == "all":
                val = all([ev(x) for x in e["all"]])
            else:
                val = any([ev(x) for x in e["any"]])
            if e.get("unless"):
                val = val and not any([ev(x) for x in e["unless"]])
            return val

        if goal in self.rules:
            return ref(goal)
        return bool(world[goal])

    def value(self, goal: str, cone: tuple[str, ...], bits: tuple[bool, ...]) -> bool:
        """Memoised ``f_goal`` on the complete cone assignment ``bits``."""
        key = (goal, bits)
        if key not in self._table:
            self._table[key] = self.evaluate(goal, dict(zip(cone, bits, strict=True)))
        return self._table[key]

    # ---- evidence handling
    def known(self, goal: str, evidence: Mapping[str, Any] | None) -> dict[str, bool]:
        """Known facts of ``evidence`` restricted to the cone of ``goal``."""
        cone = set(self.cone(goal))
        return {a: v for a, v in (evidence or {}).items() if v is not None and a in cone}

    def omega(self, goal: str, evidence: Mapping[str, Any] | None) -> Iterable[tuple[bool, ...]]:
        """Enumerate Omega(K): complete cone assignments agreeing with K (lexicographic)."""
        cone = self.cone(goal)
        known = self.known(goal, evidence)
        choices = [(known[a],) if a in known else (False, True) for a in cone]
        return itertools.product(*choices)

    # ---- the paper's notions
    def decision(self, goal: str, evidence: Mapping[str, Any] | None) -> str:
        """Dec(g, K) by enumerating every completion."""
        cone = self.cone(goal)
        outcomes = {self.value(goal, cone, w) for w in self.omega(goal, evidence)}
        if outcomes == {True}:
            return TRUE
        if outcomes == {False}:
            return FALSE
        return UNKNOWN

    def relevant(self, goal: str, evidence: Mapping[str, Any] | None) -> tuple[str, ...]:
        """Rel(g, K) straight from the definition (empty when decided)."""
        cone = self.cone(goal)
        known = self.known(goal, evidence)
        out = []
        for i, a in enumerate(cone):
            if a in known:
                continue
            for w in self.omega(goal, evidence):
                if w[i]:  # visit each pair {w[a=0], w[a=1]} once
                    continue
                w1 = (*w[:i], True, *w[i + 1 :])
                if self.value(goal, cone, w) != self.value(goal, cone, w1):
                    out.append(a)
                    break
        return tuple(out)  # cone is sorted, so out is sorted

    def lexicographic_certificate(
        self, goal: str, evidence: Mapping[str, Any] | None
    ) -> dict[str, bool] | None:
        """Contract algorithm: delete atoms in lexicographic order when status is preserved."""
        status = self.decision(goal, evidence)
        if status == UNKNOWN:
            return None
        cert = dict(self.known(goal, evidence))
        for a in sorted(cert):
            trial = {k: v for k, v in cert.items() if k != a}
            if self.decision(goal, trial) == status:
                cert = trial
        return dict(sorted(cert.items()))

    def is_sufficient(self, goal: str, subset: Mapping[str, bool], status: str) -> bool:
        """``Dec(g, S) == status``."""
        return self.decision(goal, subset) == status

    def is_subset_minimal(self, goal: str, subset: Mapping[str, bool], status: str) -> bool:
        """Removing any single fact from ``subset`` changes the decision (paper Def. of certificate)."""
        return all(self.decision(goal, {k: v for k, v in subset.items() if k != a}) != status for a in subset)

    def witnesses(
        self, goal: str, evidence: Mapping[str, Any] | None
    ) -> tuple[dict[str, bool], dict[str, bool]] | None:
        """Lexicographically smallest (False < True, sorted atoms) opposite-outcome worlds."""
        if self.decision(goal, evidence) != UNKNOWN:
            return None
        cone = self.cone(goal)
        true_w = false_w = None
        for w in self.omega(goal, evidence):  # lexicographic order
            val = self.value(goal, cone, w)
            if val and true_w is None:
                true_w = dict(zip(cone, w, strict=True))
            if not val and false_w is None:
                false_w = dict(zip(cone, w, strict=True))
            if true_w is not None and false_w is not None:
                break
        assert true_w is not None and false_w is not None
        return true_w, false_w

    def is_valid_witness(
        self, goal: str, evidence: Mapping[str, Any] | None, world: Mapping[str, bool], outcome: bool
    ) -> bool:
        """World is complete over the cone, agrees with K and gives ``outcome``."""
        cone = self.cone(goal)
        if set(world) != set(cone):
            return False
        if any(world[a] != v for a, v in self.known(goal, evidence).items()):
            return False
        return self.evaluate(goal, world) is outcome


# --------------------------------------------------------------------------- functional API


def cone(spec: Any, goal: str) -> tuple[str, ...]:
    return Oracle(spec).cone(goal)


def evaluate(spec: Any, goal: str, world: Mapping[str, bool]) -> bool:
    return Oracle(spec).evaluate(goal, world)


def decision(spec: Any, goal: str, evidence: Mapping[str, Any] | None) -> str:
    return Oracle(spec).decision(goal, evidence)


def relevant(spec: Any, goal: str, evidence: Mapping[str, Any] | None) -> tuple[str, ...]:
    return Oracle(spec).relevant(goal, evidence)


def is_sufficient(spec: Any, goal: str, subset: Mapping[str, bool], status: str) -> bool:
    return Oracle(spec).is_sufficient(goal, subset, status)


def is_subset_minimal(spec: Any, goal: str, subset: Mapping[str, bool], status: str) -> bool:
    return Oracle(spec).is_subset_minimal(goal, subset, status)
