"""Name, reference and acyclicity checks. Works on plain names only (no AST import)."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping

from ..exceptions import RuleError

RESERVED_NAMES = frozenset({"rules", "atoms", "schema_version"})
MAX_DEPTH = 256
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def check_name(name: object, what: str = "name") -> str:
    """Return ``name`` if it is a valid, non-reserved identifier, else raise :class:`RuleError`."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise RuleError(f"invalid {what} {name!r}: must match [A-Za-z_][A-Za-z0-9_]*")
    if name in RESERVED_NAMES:
        raise RuleError(f"invalid {what} {name!r}: reserved word")
    return name


def check_references(deps: Mapping[str, tuple[str, ...]], declared_atoms: Collection[str] | None) -> None:
    """Strict mode (``declared_atoms`` given): every non-rule reference must be a declared atom."""
    if declared_atoms is None:
        return
    for rule, refs in deps.items():
        for ref in refs:
            if ref not in deps and ref not in declared_atoms:
                raise RuleError(f"undefined reference {ref!r} in rule {rule!r}")


def topological_order(deps: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Rules ordered dependencies-first; raises :class:`RuleError` ``cycle: a -> b -> a`` on a cycle.

    Iterative DFS in insertion order, so deep reference chains cannot overflow the stack and the
    reported cycle is deterministic.
    """
    order: list[str] = []
    done: set[str] = set()
    for start in deps:
        if start in done:
            continue
        path = [start]
        on_path = {start}
        cursors = [iter(deps[start])]
        while path:
            for ref in cursors[-1]:
                if ref in deps and ref not in done:
                    if ref in on_path:
                        cycle = [*path[path.index(ref) :], ref]
                        raise RuleError(f"Cycle detected among rules (cycle: {' -> '.join(cycle)})")
                    path.append(ref)
                    on_path.add(ref)
                    cursors.append(iter(deps[ref]))
                    break
            else:
                node = path.pop()
                on_path.discard(node)
                cursors.pop()
                done.add(node)
                order.append(node)
    return tuple(order)
