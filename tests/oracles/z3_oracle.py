"""Independent symbolic oracle built on z3 (no askcert imports, no BDDs).

Semantics (paper Sec. 3, completion semantics):

* residual ``f|K`` is obtained by substituting the known atoms;
* ``f|K`` UNSAT                -> FALSE;
* ``not f|K`` UNSAT            -> TRUE;
* otherwise                    -> UNKNOWN;
* unknown atom ``a`` is relevant iff ``f|K[a=0] xor f|K[a=1]`` is SAT.

Only the *structural* unwrapping of the three document forms is shared with the
brute-force oracle (``bruteforce.normalize``); expression semantics are
re-implemented here directly on z3 terms.

Import this module only after ``pytest.importorskip("z3")``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import z3

from tests.oracles.bruteforce import FALSE, OPERATORS, TRUE, UNKNOWN, normalize


class Z3Oracle:
    def __init__(self, spec: Any) -> None:
        self.declared, self.rules = normalize(spec)
        self._formulas: dict[str, z3.BoolRef] = {}
        self._atoms: dict[str, z3.BoolRef] = {}

    # ---- translation
    def _atom(self, name: str) -> z3.BoolRef:
        if name not in self._atoms:
            self._atoms[name] = z3.Bool(name)
        return self._atoms[name]

    def formula(self, goal: str) -> z3.BoolRef:
        """z3 term for ``f_goal`` over the base atoms (rules are inlined)."""
        if goal not in self._formulas:
            self._formulas[goal] = self._ref(goal)
        return self._formulas[goal]

    def _ref(self, name: str) -> z3.BoolRef:
        if name in self.rules:
            if name not in self._formulas:
                self._formulas[name] = self._expr(self.rules[name])
            return self._formulas[name]
        return self._atom(name)

    def _expr(self, e: Any) -> z3.BoolRef:
        if isinstance(e, bool):
            return z3.BoolVal(e)
        if isinstance(e, str):
            return z3.Not(self._ref(e[1:])) if e.startswith("!") else self._ref(e)
        (op,) = [k for k in e if k in OPERATORS]
        if op == "not":
            out = z3.Not(self._expr(e["not"]))
        elif op == "implies":
            left, right = e["implies"]
            out = z3.Implies(self._expr(left), self._expr(right))
        elif op == "xor":
            out = z3.BoolVal(False)
            for sub in e["xor"]:
                out = z3.Xor(out, self._expr(sub))
        elif op == "all":
            out = z3.BoolVal(True)
            for sub in e["all"]:
                out = z3.And(out, self._expr(sub))
        else:
            out = z3.BoolVal(False)
            for sub in e["any"]:
                out = z3.Or(out, self._expr(sub))
        if e.get("unless"):
            exc = z3.BoolVal(False)
            for sub in e["unless"]:
                exc = z3.Or(exc, self._expr(sub))
            out = z3.And(out, z3.Not(exc))
        return out

    # ---- queries
    def residual(self, goal: str, evidence: Mapping[str, Any] | None) -> z3.BoolRef:
        """``f|K``: substitute every known atom that occurs in the formula."""
        f = self.formula(goal)
        subs = [(self._atom(a), z3.BoolVal(bool(v))) for a, v in (evidence or {}).items() if v is not None]
        return z3.substitute(f, *subs) if subs else f

    @staticmethod
    def _sat(term: z3.BoolRef) -> bool:
        solver = z3.Solver()
        solver.add(term)
        result = solver.check()
        assert result != z3.unknown
        return result == z3.sat

    def decision(self, goal: str, evidence: Mapping[str, Any] | None) -> str:
        res = self.residual(goal, evidence)
        if not self._sat(res):
            return FALSE
        if not self._sat(z3.Not(res)):
            return TRUE
        return UNKNOWN

    def relevant(self, goal: str, evidence: Mapping[str, Any] | None) -> tuple[str, ...]:
        res = self.residual(goal, evidence)
        known = {a for a, v in (evidence or {}).items() if v is not None}
        self.formula(goal)  # make sure all atoms of the cone were created
        out = []
        for name in sorted(self._atoms):
            if name in known:
                continue
            atom = self._atoms[name]
            low = z3.substitute(res, (atom, z3.BoolVal(False)))
            high = z3.substitute(res, (atom, z3.BoolVal(True)))
            if self._sat(z3.Xor(low, high)):
                out.append(name)
        return tuple(out)

    def is_subset_minimal(self, goal: str, subset: Mapping[str, bool], status: str) -> bool:
        return all(self.decision(goal, {k: v for k, v in subset.items() if k != a}) != status for a in subset)


def decision(spec: Any, goal: str, evidence: Mapping[str, Any] | None) -> str:
    return Z3Oracle(spec).decision(goal, evidence)


def relevant(spec: Any, goal: str, evidence: Mapping[str, Any] | None) -> tuple[str, ...]:
    return Z3Oracle(spec).relevant(goal, evidence)
