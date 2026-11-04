"""The :class:`AskCert` engine: validated rules + ROBDD backend + certified queries."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from .backends.bdd import BDD
from .exceptions import EvidenceError, ResourceLimitExceeded
from .models import CertificationResult, Status, Witnesses
from .reasoning.certificates import minimal_certificate
from .reasoning.evaluation import compile_expr, status_of
from .reasoning.relevance import rank_questions, relevant_unknowns
from .reasoning.witnesses import build_witnesses
from .rules import RuleSet

Evidence = Mapping[str, "bool | None"]
_RECURSION_HEADROOM = 2000  # caller frames + expression nesting (<= 256 levels) + safety margin


class AskCert:
    """Certified Boolean reasoning over a :class:`RuleSet` under incomplete evidence.

    Evidence maps base atoms to ``True``/``False``; ``None`` or absence means *unknown*, never
    False. A goal is TRUE (FALSE) when it holds (fails) in every completion of the unknown atoms
    of its cone, otherwise UNKNOWN, so ``x or not x`` is TRUE and ``x and not x`` is FALSE even
    if ``x`` is unknown.

    ``max_nodes`` bounds the ROBDD size and ``timeout`` (seconds, per public call; a batch call
    counts as one) bounds the time. Hitting either, or the recursion limit, raises
    :class:`ResourceLimitExceeded`; a computational failure is never reported as UNKNOWN.
    ``variable_order`` (a permutation of ``rules.atoms``) tunes diagram size and may change
    witnesses, but never status, certificates or relevant unknowns.

    Queries leave the engine unchanged: temporary nodes are rolled back, so memory does not grow
    with the number of queries. Compiled goals are cached. Instances are not thread-safe.
    """

    def __init__(
        self,
        rules: RuleSet | Mapping[str, Any],
        *,
        max_nodes: int = 1_000_000,
        timeout: float | None = None,
        variable_order: Sequence[str] | None = None,
    ) -> None:
        self._rules = rules if isinstance(rules, RuleSet) else RuleSet.from_dict(rules)
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not timeout > 0
        ):
            raise ValueError("timeout must be a positive number of seconds or None")
        order = list(self._rules.atoms if variable_order is None else variable_order)
        if not all(isinstance(v, str) for v in order) or sorted(order) != list(self._rules.atoms):
            raise ValueError("variable_order must contain each rule-set atom exactly once")
        self._timeout = timeout
        self._atoms = frozenset(self._rules.atoms)
        self._bdd = BDD(order, max_nodes)
        self._compiled: dict[str, int] = {}

    @property
    def rules(self) -> RuleSet:
        """The immutable rule set this engine reasons over."""
        return self._rules

    @property
    def node_count(self) -> int:
        """Live ROBDD nodes (terminals included). Queries do not change it; compiling goals grows it."""
        return self._bdd.node_count

    # -- public queries -------------------------------------------------------------------
    def evaluate(self, goal: str, evidence: Evidence | None = None) -> Status:
        """TRUE, FALSE or UNKNOWN for ``goal`` under completion semantics."""
        cone = self._rules.cone(goal)
        known = self._known(evidence)
        with self._guard():
            root = self._compile(goal)
            mark = self._bdd.checkpoint()
            try:
                return status_of(self._bdd.restrict(root, self._in_cone(cone, known)))
            finally:
                self._bdd.rollback(mark)

    def certify(
        self, goal: str, evidence: Evidence | None = None, *, witnesses: bool = True
    ) -> CertificationResult:
        """Status plus, if decided, a subset-minimal certificate; if UNKNOWN, the relevant
        unknowns and (unless ``witnesses=False``) a true-world and a false-world witness."""
        cone = self._rules.cone(goal)
        known = self._known(evidence)
        with self._guard():
            return self._certify(goal, cone, known, witnesses)

    def find_certificate(self, goal: str, evidence: Evidence | None = None) -> dict[str, bool] | None:
        """Subset-minimal sub-evidence that fixes the status (may be ``{}``); ``None`` iff UNKNOWN."""
        certificate = self.certify(goal, evidence, witnesses=False).certificate
        return None if certificate is None else dict(certificate)

    def find_relevant_unknowns(self, goal: str, evidence: Evidence | None = None) -> tuple[str, ...]:
        """Unknown atoms that can still change the outcome, sorted; ``()`` iff decided."""
        return self.certify(goal, evidence, witnesses=False).relevant_unknowns

    def find_witnesses(self, goal: str, evidence: Evidence | None = None) -> Witnesses | None:
        """Opposite-outcome worlds consistent with the evidence; ``None`` iff decided."""
        return self.certify(goal, evidence).witnesses

    def certify_many(
        self, goal: str, evidences: Iterable[Evidence | None], *, witnesses: bool = True
    ) -> list[CertificationResult]:
        """:meth:`certify` for each evidence body in order, with bounded working memory."""
        cone = self._rules.cone(goal)
        results = []
        with self._guard():
            for evidence in evidences:
                results.append(self._certify(goal, cone, self._known(evidence), witnesses))
        return results

    def compile(self, *goals: str) -> AskCert:
        """Compile ``goals`` (every rule if none) ahead of time and return ``self``."""
        for goal in goals:
            self._rules.cone(goal)
        with self._guard():
            if goals:
                for goal in goals:
                    self._compile(goal)
            else:
                self._compile_rules(self._rules.rule_order())
        return self

    # -- internals ------------------------------------------------------------------------
    @contextmanager
    def _guard(self) -> Iterator[None]:
        """Apply the per-call timeout and turn stack exhaustion into ResourceLimitExceeded."""
        self._bdd.set_deadline(self._timeout)
        # ROBDD recursion depth grows with the number of variables (about 3 frames per level), so
        # large cones would hit Python's default limit of 1000. Since 3.11, Python-to-Python calls
        # do not consume C stack, so raising the limit for the duration of the call is safe.
        old_limit = sys.getrecursionlimit()
        needed = _RECURSION_HEADROOM + 4 * len(self._bdd.variables)
        raised = needed > old_limit
        if raised:
            sys.setrecursionlimit(needed)
        try:
            self._bdd.check_deadline()  # a tiny timeout counts as already expired
            yield
        except RecursionError as exc:
            raise ResourceLimitExceeded("recursion", sys.getrecursionlimit()) from exc
        finally:
            self._bdd.set_deadline(None)
            if raised and sys.getrecursionlimit() == needed:
                sys.setrecursionlimit(old_limit)

    def _known(self, evidence: Evidence | None) -> dict[str, bool]:
        if evidence is None:
            return {}
        if not isinstance(evidence, Mapping):
            raise EvidenceError(f"evidence must be a mapping, got {type(evidence).__name__}")
        known: dict[str, bool] = {}
        for atom, value in evidence.items():
            if atom in self._rules.rules:
                raise EvidenceError(f"cannot assign derived rule {atom!r}; evidence must name base atoms")
            if atom not in self._atoms:
                raise EvidenceError(f"unknown atom {atom!r}")
            if value is None:
                continue
            if type(value) is not bool:
                raise EvidenceError(f"evidence value for {atom!r} must be True, False or None, got {value!r}")
            known[atom] = value
        return dict(sorted(known.items()))

    @staticmethod
    def _in_cone(cone: Sequence[str], known: Mapping[str, bool]) -> dict[str, bool]:
        return {atom: known[atom] for atom in cone if atom in known}

    def _resolve(self, name: str) -> int:
        node = self._compiled.get(name)
        return self._bdd.var(name) if node is None else node

    def _compile_rules(self, order: Iterable[str]) -> None:
        """Compile rules (dependencies first); on failure the engine is left as it was."""
        mark = self._bdd.checkpoint()
        added: list[str] = []
        try:
            for name in order:
                if name not in self._compiled:
                    self._bdd.check_deadline()
                    self._compiled[name] = compile_expr(self._bdd, self._rules.rules[name], self._resolve)
                    added.append(name)
        except BaseException:
            for name in added:
                del self._compiled[name]
            self._bdd.rollback(mark)
            raise
        self._bdd.commit(mark)

    def _compile(self, goal: str) -> int:
        node = self._compiled.get(goal)
        if node is None:
            if goal in self._rules.rules:
                self._compile_rules(self._rules.cone_rules(goal))
                node = self._compiled[goal]
            else:
                node = self._bdd.var(goal)
        return node

    def _certify(
        self, goal: str, cone: Sequence[str], known: Mapping[str, bool], witnesses: bool
    ) -> CertificationResult:
        root = self._compile(goal)
        in_cone = self._in_cone(cone, known)
        mark = self._bdd.checkpoint()
        try:
            restricted = self._bdd.restrict(root, in_cone)
            status = status_of(restricted)
            if status is Status.UNKNOWN:
                found = build_witnesses(self._bdd, restricted, cone, in_cone) if witnesses else None
                return CertificationResult(
                    goal, status, known, None, relevant_unknowns(self._bdd, restricted), found
                )
            certificate = minimal_certificate(self._bdd, root, in_cone, restricted)
            return CertificationResult(goal, status, known, certificate, (), None)
        finally:
            self._bdd.rollback(mark)

    def _rank_questions(
        self, goal: str, evidence: Evidence | None, costs: Mapping[str, float]
    ) -> list[tuple[str, float, float, tuple[bool, ...]]]:
        """Relevant unknowns ranked for asking (used by the session API)."""
        cone = self._rules.cone(goal)
        known = self._known(evidence)
        with self._guard():
            root = self._compile(goal)
            mark = self._bdd.checkpoint()
            try:
                restricted = self._bdd.restrict(root, self._in_cone(cone, known))
                return rank_questions(self._bdd, restricted, costs)
            finally:
                self._bdd.rollback(mark)


def compile_rules(
    spec: RuleSet | Mapping[str, Any], *, goals: Iterable[str] | None = None, **engine_kwargs: Any
) -> AskCert:
    """Build an :class:`AskCert` and compile ``goals`` (every rule if ``None``) up front."""
    return AskCert(spec, **engine_kwargs).compile(*(goals or ()))
