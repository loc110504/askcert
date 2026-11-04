"""Opposite-outcome witnesses for UNKNOWN decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..backends.base import Backend
from ..models import Witnesses


def build_witnesses(
    backend: Backend, restricted: int, cone: Sequence[str], known: Mapping[str, bool]
) -> Witnesses:
    """Complete worlds over ``cone`` that agree with ``known`` and give the goal 1 and 0.

    ``restricted`` must be a non-terminal node. Each world follows the backend's False-first path
    on the restricted function; known atoms keep their value, all other atoms are False.
    """
    worlds = []
    for value in (True, False):
        path = backend.witness(restricted, value)
        if path is None:  # pragma: no cover - a non-terminal node reaches both terminals
            raise AssertionError("no witness for a non-terminal node")
        worlds.append({a: known[a] if a in known else path.get(a, False) for a in cone})
    return Witnesses(true_world=worlds[0], false_world=worlds[1])
