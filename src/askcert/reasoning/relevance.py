"""Decision-relevant unknowns and question ranking."""

from __future__ import annotations

from collections.abc import Mapping

from ..backends.base import Backend


def relevant_unknowns(backend: Backend, restricted: int) -> tuple[str, ...]:
    """Unknown atoms the restricted function depends on, sorted by name (``()`` if constant)."""
    return tuple(sorted(backend.support(restricted)))


Ranked = tuple[str, float, float, tuple[bool, ...]]


def rank_questions(backend: Backend, restricted: int, costs: Mapping[str, float]) -> list[Ranked]:
    """Rank relevant unknowns as ``(atom, cost, score, resolving_answers)``, best first.

    The score rewards answers that decide the goal outright and answers that shrink the
    restricted diagram, divided by the question's cost (default 1.0). Ties break on cost, then name.
    """
    if restricted < 2:
        return []
    count = backend.size(restricted)
    ranked: list[Ranked] = []
    for atom in relevant_unknowns(backend, restricted):
        low = backend.restrict(restricted, {atom: False})
        high = backend.restrict(restricted, {atom: True})
        terminal = int(low < 2) + int(high < 2)
        decrease = count - (backend.size(low) + backend.size(high)) / 2
        cost = float(costs.get(atom, 1.0))
        score = (2.0 * terminal + max(0, decrease) / max(1, count)) / cost
        resolving = tuple(answer for answer, child in ((False, low), (True, high)) if child < 2)
        ranked.append((atom, cost, score, resolving))
    return sorted(ranked, key=lambda q: (-q[2], q[1], q[0]))
