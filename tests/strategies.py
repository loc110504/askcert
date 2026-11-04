"""Hypothesis strategies for random acyclic rule documents and partial evidence.

* atoms are ``x0..x{n-1}`` (2-8 of them), rules are ``r0..r{m-1}`` (1-5 of them);
  rule ``i`` may reference atoms and the *earlier* rules ``r0..r{i-1}`` only, so every
  document is acyclic by construction (rule declaration order is free: shuffling the
  mapping/list never changes the semantics);
* expression nesting depth <= 4; operators: constants, refs, ``"!x"``, ``not``, ``all``,
  ``any``, ``xor``, ``implies``, ``unless`` (empty and non-empty), empty operand lists;
* document shapes: document form (with/without ``schema_version``), document form
  with declared ``atoms`` (including declared-but-unused ones), shorthand form and the
  flat-list form (``name``/``p`` alias, ``ALL``/``ANY``/default op).

``cases()`` yields ``Case(spec, goal, evidence)``; ``evidence`` mixes True / False /
None / absent over the atoms of the rule set.  The ``spec`` is plain JSON data, so a
failing example can be pasted straight into ``tests/regression/cases.json``.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

from hypothesis import strategies as st

from tests.oracles import bruteforce as bf


class Case(NamedTuple):
    spec: dict
    goal: str
    evidence: dict

    def as_json(self) -> str:
        """Paste-ready text for ``tests/regression/cases.json``."""
        return json.dumps(
            {"rules": self.spec, "goal": self.goal, "evidence": self.evidence}, indent=1, sort_keys=False
        )


# ------------------------------------------------------------------ expressions


def _leaf(draw: Any, leaves: list[str], fresh: list[str], allow_bang: bool = True) -> Any:
    kind = draw(st.integers(0, 19))
    if kind == 19:  # constants are rare so that the "simplest" draw is still a real reference
        return draw(st.booleans())
    # half of the references use a not-yet-used atom: bigger cones, more distinct atoms per formula
    name = fresh.pop(0) if fresh and kind % 2 == 0 else draw(st.sampled_from(leaves))
    if allow_bang and kind >= 13:
        return "!" + name
    return name


_ARITY = [2, 3, 2, 3, 0, 1, 2, 4, 3]


def _expr(draw: Any, leaves: list[str], fresh: list[str], depth: int, top: bool = False) -> Any:
    # inner nodes become leaves ~12% of the time; the root of a rule is a leaf only at depth 0
    if depth == 0 or (not top and draw(st.integers(0, 7)) == 7):
        return _leaf(draw, leaves, fresh)
    op = draw(st.sampled_from(["all", "any", "not", "xor", "implies", "all", "any"]))
    if op == "not":
        return {"not": _expr(draw, leaves, fresh, depth - 1)}
    if op == "implies":
        return {"implies": [_expr(draw, leaves, fresh, depth - 1), _expr(draw, leaves, fresh, depth - 1)]}
    n = draw(st.sampled_from(_ARITY))
    node: dict[str, Any] = {op: [_expr(draw, leaves, fresh, depth - 1) for _ in range(n)]}
    if op in ("all", "any") and draw(st.integers(0, 3)) == 0:  # unless, sometimes empty
        node["unless"] = [_expr(draw, leaves, fresh, depth - 1) for _ in range(draw(st.integers(0, 2)))]
    return node


def _flat_rule(draw: Any, name: str, leaves: list[str]) -> dict[str, Any]:
    item: dict[str, Any] = {draw(st.sampled_from(["name", "name", "p"])): name}
    op = draw(st.sampled_from(["ALL", "ANY", None]))
    if op is not None:
        item["op"] = op
    if draw(st.integers(0, 6)) != 6:  # `conditions` key sometimes omitted (defaults to [])
        n = draw(st.sampled_from([2, 3, 1, 2, 3, 0]))
        item["conditions"] = [draw(st.sampled_from(leaves)) for _ in range(n)]
    if draw(st.integers(0, 2)) == 2:
        n = draw(st.sampled_from([1, 2, 0]))
        item["exceptions"] = [draw(st.sampled_from(leaves)) for _ in range(n)]
    return item


# ------------------------------------------------------------------ documents


@st.composite
def rule_documents(
    draw: Any, min_atoms: int = 2, max_atoms: int = 8, max_rules: int = 5, max_depth: int = 4
) -> dict:
    """Random acyclic raw rule document (plain dict, JSON-serialisable)."""
    n_atoms = draw(st.integers(min_atoms, max_atoms))
    pool = [f"x{i}" for i in range(n_atoms)]
    n_rules = draw(st.integers(1, max_rules))
    names = [f"r{i}" for i in range(n_rules)]
    shape = draw(st.sampled_from(["document", "document", "declared", "shorthand", "flat", "flat_declared"]))
    flat = shape.startswith("flat")
    fresh = list(draw(st.permutations(pool)))

    rules: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        leaves = pool + names[:i] + names[:i]  # earlier rules are as likely as atoms in aggregate
        if flat:
            items.append(_flat_rule(draw, name, leaves))
        else:
            depth = draw(st.sampled_from([3, 1, 2, 3, 3, 4, 4, 4, 0])) if max_depth >= 4 else max_depth
            rules[name] = _expr(draw, leaves, fresh, min(depth, max_depth), top=True)

    spec: dict[str, Any]
    body: Any = items if flat else rules
    if shape == "shorthand":
        spec = rules
    else:
        spec = {}
        if draw(st.booleans()):
            spec["schema_version"] = "1"
        if shape in ("declared", "flat_declared"):
            probe = bf.Oracle({"rules": body})
            extra = [a for a in pool if draw(st.booleans())]
            declared = sorted({*probe.atoms, *extra})
            if draw(st.booleans()):
                declared = draw(st.permutations(declared))
            spec["atoms"] = list(declared)
        spec["rules"] = body

    # randomise rule declaration order (references to later rules are legal)
    if draw(st.booleans()):
        if flat:
            items = draw(st.permutations(items))
            spec["rules"] = list(items)
        elif shape == "shorthand":
            spec = {k: rules[k] for k in draw(st.permutations(list(rules)))}
        else:
            spec["rules"] = {k: rules[k] for k in draw(st.permutations(list(rules)))}
    return spec


# ------------------------------------------------------------------ evidence


@st.composite
def evidences(draw: Any, atoms: list[str]) -> dict[str, bool | None]:
    """Partial assignment over ``atoms``: each atom True / False / None / absent."""
    if not atoms:
        return {}
    known = draw(st.lists(st.sampled_from(atoms), unique=True, max_size=len(atoms)))
    ev: dict[str, bool | None] = {a: draw(st.booleans()) for a in known}
    for a in atoms:
        if a not in ev and draw(st.booleans()):
            ev[a] = None
    items = list(ev.items())
    return dict(draw(st.permutations(items)))


@st.composite
def cases(draw: Any, **doc_kwargs: Any) -> Case:
    """(spec, goal, evidence) with the goal a rule name (mostly) or a base atom."""
    spec = draw(rule_documents(**doc_kwargs))
    oracle = bf.Oracle(spec)
    rule_names = list(oracle.rules)
    if draw(st.integers(0, 9)) < 9:  # later rules have the biggest cones: favour them
        goal = draw(st.sampled_from(rule_names[::-1] + rule_names[-1:] * 2))
    else:
        goal = draw(st.sampled_from(oracle.atoms)) if oracle.atoms else rule_names[0]
    evidence = draw(evidences(list(oracle.atoms)))
    return Case(spec, goal, evidence)


def known_only(evidence: dict[str, bool | None]) -> dict[str, bool]:
    """The facts of ``evidence`` (``None`` dropped)."""
    return {a: v for a, v in evidence.items() if v is not None}
