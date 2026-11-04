"""Subset-minimal supporting certificates by deletion."""

from __future__ import annotations

from collections.abc import Mapping

from ..backends.base import Backend


def minimal_certificate(
    backend: Backend, root: int, evidence: Mapping[str, bool], target: int
) -> dict[str, bool]:
    """Subset-minimal part of ``evidence`` that still forces ``root`` to the terminal ``target``.

    ``root`` is the unrestricted goal node and ``evidence`` the known cone atoms. Atoms are tried
    for deletion in lexicographic name order, so the result is deterministic (and independent of
    the variable order). It is subset-minimal, not minimum-cardinality, and may be empty.
    """
    kept = dict(sorted(evidence.items()))
    for atom in list(kept):
        trial = {a: v for a, v in kept.items() if a != atom}
        backend.check_deadline()
        mark = backend.checkpoint()
        try:
            still_forced = backend.restrict(root, trial) == target
        finally:
            backend.rollback(mark)  # keep the footprint of each trial bounded
        if still_forced:
            kept = trial
    return kept
