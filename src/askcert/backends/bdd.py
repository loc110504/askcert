"""Pure-Python reduced ordered binary decision diagram (ROBDD).

Canonical form: equal Boolean functions have equal node handles, so a restricted function is
constant exactly when its handle is a terminal. Recursion depth is bounded by the number of
variables; deeper structures end in ``ResourceLimitExceeded("recursion")`` at the engine level.
Not thread-safe.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from ..exceptions import ResourceLimitExceeded

_AND, _OR, _XOR, _NOT = 0, 1, 2, 3
_CHECK_MASK = 255  # the deadline is polled every 256 uncached operations


class BDD:
    """ROBDD over a fixed variable order (``variables[0]`` is the root-most level)."""

    def __init__(self, variables: Sequence[str], max_nodes: int = 1_000_000) -> None:
        if type(max_nodes) is not int or max_nodes < 2:
            raise ValueError("max_nodes must be an integer >= 2")
        names = tuple(variables)
        if len(set(names)) != len(names):
            raise ValueError("BDD variable names must be unique")
        self.variables = names
        self.max_nodes = max_nodes
        self.false = 0
        self.true = 1
        self._level = {name: i for i, name in enumerate(names)}
        # Parallel node arrays; the two terminals sit below every variable level.
        self._var = [len(names), len(names)]
        self._low = [0, 0]
        self._high = [0, 0]
        self._unique: dict[tuple[int, int, int], int] = {}
        # Insertion-ordered, so rollback can drop the newest entries from the end.
        self._cache: dict[tuple[int, int, int], int] = {}
        self._marks: list[tuple[int, int]] = []
        self._deadline: float | None = None
        self._timeout: float | None = None
        self._ticks = 0

    @property
    def node_count(self) -> int:
        """Live nodes, terminals included; never exceeds ``max_nodes``."""
        return len(self._var)

    # -- deadline -------------------------------------------------------------------------
    def set_deadline(self, seconds: float | None) -> None:
        """Raise ``ResourceLimitExceeded("timeout")`` from operations running past ``seconds`` from now."""
        self._timeout = seconds
        # perf_counter, not monotonic: monotonic ticks every ~15 ms on Windows, which would let
        # sub-tick timeouts pass unnoticed.
        self._deadline = None if seconds is None else time.perf_counter() + seconds

    def check_deadline(self) -> None:
        if self._deadline is not None and time.perf_counter() > self._deadline:
            raise ResourceLimitExceeded("timeout", self._timeout)

    def _tick(self) -> None:
        self._ticks += 1
        if not self._ticks & _CHECK_MASK:
            self.check_deadline()

    # -- construction ---------------------------------------------------------------------
    def _mk(self, var: int, low: int, high: int) -> int:
        if low == high:
            return low
        key = (var, low, high)
        u = self._unique.get(key)
        if u is None:
            if len(self._var) >= self.max_nodes:
                raise ResourceLimitExceeded("max_nodes", self.max_nodes)
            u = len(self._var)
            self._var.append(var)
            self._low.append(low)
            self._high.append(high)
            self._unique[key] = u
        return u

    def var(self, name: str) -> int:
        """Node of the single variable ``name`` (``KeyError`` if it is not in the order)."""
        return self._mk(self._level[name], 0, 1)

    def level(self, u: int) -> int:
        """Position of ``u``'s top variable in the order; terminals get ``len(variables)``."""
        return self._var[u]

    def negate(self, u: int) -> int:
        if u < 2:
            return 1 - u
        key = (_NOT, u, 0)
        r = self._cache.get(key)
        if r is None:
            self._tick()
            r = self._mk(self._var[u], self.negate(self._low[u]), self.negate(self._high[u]))
            self._cache[key] = r
        return r

    def _apply(self, op: int, a: int, b: int) -> int:
        if a > b:  # all three operators are commutative
            a, b = b, a
        if op == _AND:
            if a == 0:
                return 0
            if a == 1 or a == b:
                return b
        elif op == _OR:
            if a == 1:
                return 1
            if a == 0 or a == b:
                return b
        else:
            if a == b:
                return 0
            if a == 0:
                return b
            if a == 1:
                return self.negate(b)
        key = (op, a, b)
        r = self._cache.get(key)
        if r is None:
            self._tick()
            va, vb = self._var[a], self._var[b]
            top = min(va, vb)
            a0, a1 = (self._low[a], self._high[a]) if va == top else (a, a)
            b0, b1 = (self._low[b], self._high[b]) if vb == top else (b, b)
            r = self._mk(top, self._apply(op, a0, b0), self._apply(op, a1, b1))
            self._cache[key] = r
        return r

    def apply_and(self, a: int, b: int) -> int:
        return self._apply(_AND, a, b)

    def apply_or(self, a: int, b: int) -> int:
        return self._apply(_OR, a, b)

    def apply_xor(self, a: int, b: int) -> int:
        return self._apply(_XOR, a, b)

    # -- queries --------------------------------------------------------------------------
    def restrict(self, u: int, assignment: Mapping[str, bool]) -> int:
        """Cofactor of ``u``: substitute the given variables, keep the rest."""
        known = {self._level[name]: value for name, value in assignment.items()}
        if not known:
            return u
        return self._restrict(u, known, max(known), {})

    def _restrict(self, u: int, known: dict[int, bool], deepest: int, memo: dict[int, int]) -> int:
        var = self._var[u]
        if var > deepest:  # also covers terminals
            return u
        r = memo.get(u)
        if r is None:
            self._tick()
            low, high = self._low[u], self._high[u]
            if var in known:
                r = self._restrict(high if known[var] else low, known, deepest, memo)
            else:
                r = self._mk(
                    var, self._restrict(low, known, deepest, memo), self._restrict(high, known, deepest, memo)
                )
            memo[u] = r
        return r

    def _reachable(self, u: int) -> set[int]:
        seen: set[int] = set()
        stack = [u]
        while stack:
            n = stack.pop()
            if n > 1 and n not in seen:
                seen.add(n)
                stack.append(self._low[n])
                stack.append(self._high[n])
        return seen

    def support(self, u: int) -> tuple[str, ...]:
        """Variables ``u`` depends on, in variable order."""
        levels = {self._var[n] for n in self._reachable(u)}
        return tuple(self.variables[i] for i in sorted(levels))

    def size(self, u: int) -> int:
        """Number of non-terminal nodes reachable from ``u``."""
        return len(self._reachable(u))

    def witness(self, u: int, value: bool) -> dict[str, bool] | None:
        """Path to the ``value`` terminal, trying the False branch first (None if unreachable).

        Only variables on the path are returned. In a reduced diagram every non-terminal node
        reaches both terminals, so the walk never has to backtrack.
        """
        target = int(value)
        path: dict[str, bool] = {}
        while u > 1:
            low = self._low[u]
            take_low = low == target or low > 1
            path[self.variables[self._var[u]]] = not take_low
            u = low if take_low else self._high[u]
        return path if u == target else None

    # -- transactions ---------------------------------------------------------------------
    def checkpoint(self) -> int:
        """Token for :meth:`rollback`; checkpoints nest."""
        self._marks.append((len(self._var), len(self._cache)))
        return len(self._marks) - 1

    def commit(self, mark: int) -> None:
        """Keep everything created since ``mark`` and forget the mark (and any later marks)."""
        if not 0 <= mark < len(self._marks):
            raise ValueError(f"invalid checkpoint {mark}")
        del self._marks[mark:]

    def rollback(self, mark: int) -> None:
        """Delete all nodes and cache entries created since ``mark`` (and any later marks)."""
        if not 0 <= mark < len(self._marks):
            raise ValueError(f"invalid checkpoint {mark}")
        nodes, cached = self._marks[mark]
        del self._marks[mark:]
        for u in range(len(self._var) - 1, nodes - 1, -1):
            self._unique.pop((self._var[u], self._low[u], self._high[u]), None)
        del self._var[nodes:], self._low[nodes:], self._high[nodes:]
        while len(self._cache) > cached:
            self._cache.popitem()
