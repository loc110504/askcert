"""Backend protocol: a canonical Boolean-function store with opaque integer node handles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

FALSE = 0
TRUE = 1


class Backend(Protocol):
    """Canonical (reduced, ordered) Boolean decision graphs.

    Nodes are ints; ``false`` (0) and ``true`` (1) are the terminals. Equal functions get equal
    handles. Limits raise :class:`askcert.ResourceLimitExceeded`.
    """

    false: int
    true: int

    @property
    def node_count(self) -> int:
        """Live nodes including the two terminals."""

    def var(self, name: str) -> int: ...

    def level(self, u: int) -> int:
        """Position of ``u``'s top variable in the order (terminals sort below every variable)."""

    def negate(self, u: int) -> int: ...
    def apply_and(self, a: int, b: int) -> int: ...
    def apply_or(self, a: int, b: int) -> int: ...
    def apply_xor(self, a: int, b: int) -> int: ...

    def restrict(self, u: int, assignment: Mapping[str, bool]) -> int:
        """Cofactor of ``u`` under a partial assignment."""

    def support(self, u: int) -> tuple[str, ...]:
        """Variables ``u`` depends on, in variable order."""

    def size(self, u: int) -> int:
        """Number of non-terminal nodes reachable from ``u``."""

    def witness(self, u: int, value: bool) -> dict[str, bool] | None:
        """Partial assignment (False branch first) forcing ``u`` to ``value``; None if impossible."""

    def checkpoint(self) -> int:
        """Mark the current state; pass the token to :meth:`rollback`."""

    def commit(self, mark: int) -> None:
        """Keep everything created since ``mark`` and forget the mark."""

    def rollback(self, mark: int) -> None:
        """Discard every node created since ``mark`` (and invalidate later marks)."""

    def set_deadline(self, seconds: float | None) -> None:
        """Abort work with ``ResourceLimitExceeded("timeout")`` after ``seconds`` (None clears)."""

    def check_deadline(self) -> None: ...
