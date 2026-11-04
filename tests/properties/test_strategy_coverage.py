"""Meta-test: the random generator must exercise what the release gate claims to cover.

If the generator degenerated (e.g. only UNKNOWN outcomes) "100% agreement with the
oracle" would prove little, so we measure the distribution of what it produces.
"""

from __future__ import annotations

import json
from collections import Counter

from hypothesis import given, settings

from tests.oracles import bruteforce as bf
from tests.strategies import cases


def _ops(expr, out):
    if isinstance(expr, bool):
        out["const"] += 1
    elif isinstance(expr, str):
        out["bang" if expr.startswith("!") else "ref"] += 1
    else:
        for key, val in expr.items():
            out[key] += 1
            for sub in [val] if key == "not" else val:
                _ops(sub, out)


def _depth(expr):
    if isinstance(expr, (bool, str)):
        return 0
    kids = []
    for key, val in expr.items():
        kids += [val] if key == "not" else list(val)
    return 1 + max((_depth(k) for k in kids), default=0)


def test_generator_coverage():
    stats: Counter = Counter()

    @settings(max_examples=400, derandomize=True, deadline=None, database=None)
    @given(cases())
    def collect(case):
        spec, goal, evidence = case
        json.dumps(spec)  # plain JSON data
        o = bf.Oracle(spec)
        stats["cases"] += 1
        stats["status_" + o.decision(goal, evidence)] += 1
        stats["form_flat" if isinstance(spec.get("rules"), list) else "form_map"] += 1
        stats["declared" if o.declared is not None else "undeclared"] += 1
        stats["shorthand" if "rules" not in spec else "document"] += 1
        stats["goal_atom" if goal in o.atoms else "goal_rule"] += 1
        stats["unused_atom"] += any(
            a not in {r for e in o.rules.values() for r in bf._refs(e)} for a in o.atoms
        )
        stats["none_evidence"] += any(v is None for v in evidence.values())
        stats["partial_evidence"] += len([a for a in o.cone(goal) if evidence.get(a) is not None]) < len(
            o.cone(goal)
        )
        stats[f"cone_{len(o.cone(goal))}"] += 1
        rules = o.rules.values()
        if not isinstance(spec.get("rules"), list):
            for e in rules:
                _ops(e, stats)
                assert _depth(e) <= 4
        if o.decision(goal, evidence) != "UNKNOWN":
            cert = o.lexicographic_certificate(goal, evidence)
            stats["cert_empty" if not cert else "cert_nonempty"] += 1

    collect()
    n = stats["cases"]
    assert n >= 300
    for st_ in ("TRUE", "FALSE", "UNKNOWN"):
        assert stats["status_" + st_] >= 0.08 * n, (st_, dict(stats))
    for key in (
        "form_flat",
        "form_map",
        "declared",
        "undeclared",
        "shorthand",
        "document",
        "goal_atom",
        "goal_rule",
        "unused_atom",
        "none_evidence",
        "partial_evidence",
        "cert_empty",
        "cert_nonempty",
        "not",
        "all",
        "any",
        "xor",
        "implies",
        "unless",
        "const",
        "ref",
        "bang",
    ):
        assert stats[key] > 0, (key, dict(stats))
    big = sum(stats[f"cone_{k}"] for k in range(4, 9))
    assert big >= 0.2 * n, dict(stats)  # a fifth of the goals depend on >= 4 atoms
    assert stats["cone_8"] > 0 and stats["cone_0"] <= 0.2 * n, dict(stats)
