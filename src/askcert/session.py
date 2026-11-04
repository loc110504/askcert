"""Stateful, backward-compatible API (``Rule``/``Reasoner``) built on :class:`AskCert`.

A :class:`Reasoner` holds rules plus a mutable fact base (``True``/``False``/``None`` = unknown)
and answers every query against the current facts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from math import isfinite
from types import MappingProxyType
from typing import Any

from .api import AskCert
from .exceptions import EvidenceError, ObservationConflictError, RuleError
from .models import Status
from .rules import ast as ex
from .rules.parser import parse_expr
from .rules.ruleset import RuleSet
from .rules.validation import check_name


def _literal(name: object) -> str:
    if not isinstance(name, str):
        raise RuleError(f"Conditions must be strings, received {type(name).__name__}")
    check_name(name.removeprefix("!"), "proposition name")
    return name


@dataclass(frozen=True, init=False)
class Rule:
    """Acyclic rule: (ALL or ANY of ``conditions``) AND NOT (ANY of ``exceptions``).

    Conditions and exceptions are names of rules or base atoms; ``"!name"`` is classical
    negation. ``Rule("p", op="ALL", conditions=["a"])`` and the sugar
    ``Rule("p", ALL=["a"], UNLESS=["b"])`` are equivalent forms.
    """

    name: str
    op: str
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]

    def __init__(
        self,
        name: str,
        op: str = "ANY",
        conditions: Sequence[str] = (),
        exceptions: Sequence[str] = (),
        *,
        ALL: Sequence[str] | None = None,
        ANY: Sequence[str] | None = None,
        UNLESS: Sequence[str] | None = None,
    ) -> None:
        check_name(name, "proposition name")
        if ALL is not None and ANY is not None:
            raise RuleError("Use ALL or ANY, not both")
        if (ALL is not None or ANY is not None) and (conditions or op != "ANY"):
            raise RuleError("Do not mix ALL/ANY sugar with op/conditions")
        if UNLESS is not None and exceptions:
            raise RuleError("Do not provide both UNLESS and exceptions")
        if ALL is not None:
            op, conditions = "ALL", ALL
        elif ANY is not None:
            op, conditions = "ANY", ANY
        if UNLESS is not None:
            exceptions = UNLESS
        if op not in ("ALL", "ANY"):
            raise RuleError("op must be ALL or ANY")
        if isinstance(conditions, (str, bytes)) or isinstance(exceptions, (str, bytes)):
            raise RuleError("conditions and exceptions must be lists of proposition names")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "op", op)
        object.__setattr__(self, "conditions", tuple(_literal(x) for x in conditions))
        object.__setattr__(self, "exceptions", tuple(_literal(x) for x in exceptions))

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any]) -> Rule:
        """Accepts ``name`` or its alias ``p``; ``op`` defaults to ``"ANY"``."""
        return cls(
            name=spec.get("name", spec.get("p")),
            op=spec.get("op", "ANY"),
            conditions=spec.get("conditions", ()),
            exceptions=spec.get("exceptions", ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "op": self.op,
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
        }

    def to_expr(self) -> ex.Expr:
        """The equivalent :mod:`askcert.rules` expression."""
        args = tuple(parse_expr(c, self.name) for c in self.conditions)
        unless = tuple(parse_expr(c, self.name) for c in self.exceptions)
        return ex.All(args, unless) if self.op == "ALL" else ex.Any(args, unless)


@dataclass(frozen=True)
class Decision:
    """Result of :meth:`Reasoner.certify`.

    Decided: ``evidence`` names a subset-minimal sufficient set of facts. UNKNOWN:
    ``relevant_unknown`` lists the facts that could change the outcome and ``counterexamples``
    is ``(true_world, false_world)``, complete over all atoms and consistent with the facts.
    """

    target: str
    status: Status
    relevant_unknown: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    counterexamples: tuple[dict[str, bool], dict[str, bool]] | None = None

    @property
    def is_certified(self) -> bool:
        return self.status is not Status.UNKNOWN


@dataclass(frozen=True)
class Question:
    """A fact worth asking about; higher ``score`` is better (benefit divided by ``cost``)."""

    fact: str
    text: str
    cost: float
    score: float
    resolving_answers: tuple[bool, ...]


class Reasoner:
    """Goal-directed decisions and questions over rules and a mutable fact base.

    Absent facts are never treated as False and negation is classical. Rule validation errors
    are :class:`RuleError`; invalid fact values are :class:`EvidenceError`; exceeding
    ``max_nodes`` raises :class:`ResourceLimitExceeded`.
    """

    def __init__(
        self,
        rules: Sequence[Rule | Mapping[str, Any]],
        facts: Mapping[str, bool | None] | None = None,
        *,
        questions: Mapping[str, str] | None = None,
        costs: Mapping[str, float] | None = None,
        max_nodes: int = 100_000,
    ) -> None:
        parsed = [r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules]
        # Private tables; public access is through read-only views (see properties below).
        self._rules: dict[str, Rule] = {r.name: r for r in parsed}
        if len(self._rules) != len(parsed):
            raise RuleError("Duplicate rule head (one rule per derived proposition)")
        self._questions = dict(questions or {})
        self._costs = dict(costs or {})
        self._facts: dict[str, bool | None] = {}
        for name, text in self._questions.items():
            check_name(name, "proposition name")
            if not isinstance(text, str) or not text.strip():
                raise RuleError(f"Question text for {name} must be a nonempty string")
        for name, cost in self._costs.items():
            check_name(name, "proposition name")
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not isfinite(cost)
                or cost <= 0
            ):
                raise RuleError(f"Cost for {name} must be finite and positive")
        ruleset = RuleSet({r.name: r.to_expr() for r in parsed})
        self._atoms = ruleset.atoms
        for name in sorted(self._questions.keys() | self._costs.keys()):
            if name not in self._atoms:
                raise RuleError(f"Question metadata must refer to a base fact: {name}")
        self._engine = AskCert(ruleset, max_nodes=max_nodes)
        for key, value in (facts or {}).items():
            self.set_fact(key, value)

    # Read-only views: facts must pass validation and rules are fixed once compiled.
    @property
    def rules(self) -> Mapping[str, Rule]:
        return MappingProxyType(self._rules)

    @property
    def facts(self) -> Mapping[str, bool | None]:
        return MappingProxyType(self._facts)

    @property
    def questions(self) -> Mapping[str, str]:
        return MappingProxyType(self._questions)

    @property
    def costs(self) -> Mapping[str, float]:
        return MappingProxyType(self._costs)

    @property
    def atoms(self) -> tuple[str, ...]:
        return self._atoms

    def _validate_fact(self, name: str, value: bool | None) -> None:
        check_name(name, "proposition name")
        if name in self._rules:
            raise RuleError(f"Cannot directly set derived proposition {name!r}")
        if name not in self._atoms:
            raise RuleError(f"Unknown base fact {name!r}; declare it in a rule")
        if value is not None and type(value) is not bool:
            raise EvidenceError("Fact values must be True, False, or None")

    def set_fact(self, name: str, value: bool | None) -> None:
        """Legacy assignment: validates, then overwrites any previous value."""
        self._validate_fact(name, value)
        self._facts[name] = value

    add_fact = set_fact

    def observe(self, name: str, value: bool | None, *, replace: bool = False) -> None:
        """Record an observation. None withdraws (marks unknown), never means False.

        Re-observing a known fact with the opposite value raises
        :class:`ObservationConflictError` unless ``replace=True`` (an explicit revision).
        """
        self._validate_fact(name, value)
        old = self._facts.get(name)
        if not replace and value is not None and old is not None and old != value:
            raise ObservationConflictError(
                f"Fact {name!r} already observed as {old}; pass replace=True to revise it"
            )
        self._facts[name] = value

    def evaluate(self, target: str) -> Status:
        """TRUE, FALSE or UNKNOWN for ``target`` under the current facts."""
        return self._engine.evaluate(target, self._facts)

    def certify(self, target: str) -> Decision:
        """Decide ``target`` with a certificate (decided) or relevant unknowns and counterexamples."""
        result = self._engine.certify(target, self._facts)
        if result.certificate is not None:
            return Decision(target, result.status, (), evidence=tuple(result.certificate))
        assert result.witnesses is not None
        worlds = []
        for witness in (result.witnesses.true_world, result.witnesses.false_world):
            world = {name: bool(self._facts.get(name)) for name in self._atoms}
            world.update(witness)
            worlds.append(world)
        return Decision(
            target, result.status, result.relevant_unknowns, counterexamples=(worlds[0], worlds[1])
        )

    def why(self, target: str) -> dict[str, Any]:
        """JSON-friendly explanation of :meth:`certify`."""
        dec = self.certify(target)
        result: dict[str, Any] = {"target": dec.target, "status": dec.status.value}
        if dec.is_certified:
            result["sufficient_evidence"] = {k: self.facts[k] for k in dec.evidence}
            result["evidence_note"] = (
                "subset-minimal sufficient observations; not necessarily minimum-cardinality"
            )
        else:
            assert dec.counterexamples is not None
            result["relevant_unknown"] = list(dec.relevant_unknown)
            result["counterexamples"] = {
                "true_world": dec.counterexamples[0],
                "false_world": dec.counterexamples[1],
            }
        return result

    def ask_all(self, target: str) -> tuple[Question, ...]:
        """Relevant unknown facts as questions, best first; empty once ``target`` is decided."""
        ranked = self._engine._rank_questions(target, self._facts, self._costs)
        return tuple(
            Question(
                atom, self._questions.get(atom, f"Is {atom.replace('_', ' ')} true?"), cost, score, resolving
            )
            for atom, cost, score, resolving in ranked
        )

    def ask(self, target: str) -> Question | None:
        """The best next question, or None if ``target`` is decided."""
        candidates = self.ask_all(target)
        return candidates[0] if candidates else None

    next_question = ask

    def verify_small(self, target: str, decision: Decision | None = None, *, max_unknown: int = 16) -> bool:
        """Independent brute-force check of a decision for small cases only.

        No symbolic operations are used: each rule is evaluated recursively with ordinary
        Python booleans over every completion of the unknown facts.
        """
        decision = decision or self.certify(target)
        if target != decision.target:
            raise ValueError("Decision target mismatch")
        if len(self.atoms) > max_unknown:
            raise ValueError(f"Independent verification limited to {max_unknown} total base atoms")
        missing = [k for k in self.atoms if self.facts.get(k) is None]
        outcomes = set()
        for values in product((False, True), repeat=len(missing)):
            world = {k: bool(v) for k, v in self.facts.items() if v is not None}
            world.update(zip(missing, values, strict=True))
            outcomes.add(self._eval_complete(target, world))
        expected = (
            Status.TRUE if outcomes == {True} else Status.FALSE if outcomes == {False} else Status.UNKNOWN
        )
        if decision.status != expected:
            return False
        if decision.is_certified:
            saved = {k: self.facts[k] for k in decision.evidence}

            def sufficient(fixed: Mapping[str, bool | None]) -> bool:
                free = [k for k in self.atoms if k not in fixed]
                return all(
                    self._eval_complete(target, {**fixed, **dict(zip(free, row, strict=True))})
                    == (expected == Status.TRUE)
                    for row in product((False, True), repeat=len(free))
                )

            return sufficient(saved) and all(
                not sufficient({k: v for k, v in saved.items() if k != fact}) for fact in saved
            )
        assert decision.counterexamples is not None
        pos, neg = decision.counterexamples
        return (
            self._eval_complete(target, pos) is True
            and self._eval_complete(target, neg) is False
            and all(pos.get(k) == v and neg.get(k) == v for k, v in self.facts.items() if v is not None)
        )

    def _eval_complete(self, target: str, world: Mapping[str, Any]) -> bool:
        if target not in self._rules:
            return bool(world[target])
        r = self._rules[target]

        def literal(name: str) -> bool:
            neg = name.startswith("!")
            value = self._eval_complete(name[1:] if neg else name, world)
            return not value if neg else value

        lits = [literal(x) for x in r.conditions]
        cond = all(lits) if r.op == "ALL" else any(lits)
        return cond and not any(literal(x) for x in r.exceptions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": [r.to_dict() for r in self._rules.values()],
            "facts": dict(self._facts),
            "questions": dict(self._questions),
            "costs": dict(self._costs),
        }

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any]) -> Reasoner:
        if not isinstance(spec, Mapping) or "rules" not in spec:
            raise RuleError("Reasoner.from_dict needs an object with a 'rules' list")
        return cls(spec["rules"], spec.get("facts"), questions=spec.get("questions"), costs=spec.get("costs"))
