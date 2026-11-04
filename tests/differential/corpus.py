"""Seeded formula/evidence corpus (plain ``random.Random``, no Hypothesis) + the full pair check.

``corpus(n, seed)`` is a pure function of ``(n, seed)``: the first ``k`` pairs of a bigger
corpus are the pairs of the smaller one, so the 1,000-pair CI test is a prefix of the
10,000-pair release corpus.  The document shapes and operators mirror
``tests/strategies.py`` (2-8 atoms, 1-5 rules, depth <= 4, all operators, declared atoms,
shorthand / document / flat-list forms).
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from askcert import AskCert
from tests.oracles import bruteforce as bf

SEED = 20261104


# ------------------------------------------------------------------ generation


def _leaf(rng: random.Random, leaves: list[str], fresh: list[str]) -> Any:
    kind = rng.randrange(20)
    if kind == 19:
        return rng.random() < 0.5
    name = fresh.pop(0) if fresh and kind % 2 == 0 else rng.choice(leaves)
    return "!" + name if kind >= 13 else name


def _expr(rng: random.Random, leaves: list[str], fresh: list[str], depth: int, top: bool = False) -> Any:
    if depth == 0 or (not top and rng.randrange(8) == 7):
        return _leaf(rng, leaves, fresh)
    op = rng.choice(["all", "any", "not", "xor", "implies", "all", "any"])
    if op == "not":
        return {"not": _expr(rng, leaves, fresh, depth - 1)}
    if op == "implies":
        return {"implies": [_expr(rng, leaves, fresh, depth - 1), _expr(rng, leaves, fresh, depth - 1)]}
    n = rng.choice([0, 1, 2, 2, 2, 3, 3, 3, 4])
    node: dict[str, Any] = {op: [_expr(rng, leaves, fresh, depth - 1) for _ in range(n)]}
    if op in ("all", "any") and rng.randrange(4) == 0:
        node["unless"] = [_expr(rng, leaves, fresh, depth - 1) for _ in range(rng.randrange(3))]
    return node


def _flat_rule(rng: random.Random, name: str, leaves: list[str]) -> dict[str, Any]:
    item: dict[str, Any] = {rng.choice(["name", "name", "p"]): name}
    op = rng.choice(["ALL", "ANY", None])
    if op is not None:
        item["op"] = op
    if rng.randrange(7) != 6:
        item["conditions"] = [rng.choice(leaves) for _ in range(rng.choice([0, 1, 2, 2, 3, 3]))]
    if rng.randrange(3) == 2:
        item["exceptions"] = [rng.choice(leaves) for _ in range(rng.randrange(3))]
    return item


def random_document(rng: random.Random) -> dict:
    """One random acyclic rule document in a random shape (document / declared / shorthand / flat)."""
    pool = [f"x{i}" for i in range(rng.randint(2, 8))]
    names = [f"r{i}" for i in range(rng.randint(1, 5))]
    shape = rng.choice(["document", "document", "declared", "shorthand", "flat", "flat_declared"])
    flat = shape.startswith("flat")
    fresh = rng.sample(pool, len(pool))
    rules: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        leaves = pool + names[:i] * 2
        if flat:
            items.append(_flat_rule(rng, name, leaves))
        else:
            rules[name] = _expr(rng, leaves, fresh, rng.choice([3, 1, 2, 3, 3, 4, 4, 4, 0]), top=True)
    body: Any = items if flat else rules
    if shape == "shorthand":
        return rules
    spec: dict[str, Any] = {}
    if rng.random() < 0.5:
        spec["schema_version"] = "1"
    if shape in ("declared", "flat_declared"):
        used = bf.Oracle({"rules": body}).atoms
        declared = sorted({*used, *(a for a in pool if rng.random() < 0.5)})
        if rng.random() < 0.5:
            rng.shuffle(declared)
        spec["atoms"] = declared
    spec["rules"] = body
    return spec


def random_evidence(rng: random.Random, atoms: list[str]) -> dict[str, bool | None]:
    """Partial evidence: density drawn per pair; unknown atoms are ``None`` or absent."""
    density = rng.choice([0.0, 0.25, 0.5, 0.5, 0.75, 1.0])
    ev: dict[str, bool | None] = {}
    for a in atoms:
        if rng.random() < density:
            ev[a] = rng.random() < 0.5
        elif rng.random() < 0.5:
            ev[a] = None
    return ev


def corpus(n: int, seed: int = SEED):
    """Yield ``n`` (spec, goal, evidence) triples, one fresh formula per pair, in a fixed order."""
    rng = random.Random(seed)
    for _ in range(n):
        spec = random_document(rng)
        o = bf.Oracle(spec)
        goal = (
            rng.choice(list(o.rules)[::-1] + list(o.rules)[-1:] * 2)
            if rng.random() < 0.9
            else rng.choice(o.atoms or list(o.rules))
        )
        yield spec, goal, random_evidence(rng, o.atoms)


# ------------------------------------------------------------------ checking


def check_pair(spec: dict, goal: str, evidence: dict) -> tuple[list[str], dict[str, str]]:
    """Run askcert and the brute-force oracle on one pair.

    Returns ``(failures, facts)``: ``failures`` is a list of human-readable disagreements
    (empty = full agreement on status, certificate validity + minimality, relevance and
    witness validity); ``facts`` summarises the pair for corpus statistics.
    """
    o = bf.Oracle(spec)
    engine = AskCert(spec)
    bad: list[str] = []
    res = engine.certify(goal, evidence)
    status = o.decision(goal, evidence)
    if res.status != status:
        bad.append(f"status {res.status} != oracle {status}")
    if engine.evaluate(goal, evidence) != status:
        bad.append("evaluate() disagrees with oracle")
    known = {a: v for a, v in evidence.items() if v is not None}
    cone = set(o.cone(goal))
    if status == bf.UNKNOWN:
        if res.certificate is not None:
            bad.append("certificate present for UNKNOWN")
        wit = res.witnesses
        if wit is None:
            bad.append("witnesses missing for UNKNOWN")
        else:
            if not o.is_valid_witness(goal, evidence, wit.true_world, True):
                bad.append(f"invalid true witness {dict(wit.true_world)}")
            if not o.is_valid_witness(goal, evidence, wit.false_world, False):
                bad.append(f"invalid false witness {dict(wit.false_world)}")
    else:
        cert = res.certificate
        if cert is None:
            bad.append("certificate missing for decided status")
        else:
            cert = dict(cert)
            if not (set(cert) <= cone and all(known.get(a) is v for a, v in cert.items())):
                bad.append(f"certificate {cert} not a subset of evidence on the cone")
            if not o.is_sufficient(goal, cert, status):
                bad.append(f"certificate {cert} not sufficient")
            if not o.is_subset_minimal(goal, cert, status):
                bad.append(f"certificate {cert} not subset-minimal")
            if cert != o.lexicographic_certificate(goal, evidence):
                bad.append(f"certificate {cert} != lexicographic deletion result")
        if res.witnesses is not None:
            bad.append("witnesses present for decided status")
    expected_rel = o.relevant(goal, evidence)
    if res.relevant_unknowns != expected_rel:
        bad.append(f"relevant {res.relevant_unknowns} != oracle {expected_rel}")
    facts = {
        "status": status,
        "cert": "none" if res.certificate is None else ("empty" if not res.certificate else "nonempty"),
    }
    return bad, facts


def run_corpus(n: int, seed: int = SEED) -> tuple[int, int, Counter, list[str]]:
    """Check ``n`` pairs; return ``(total, agreeing, stats, first_failures)``."""
    total = agree = 0
    stats: Counter = Counter()
    failures: list[str] = []
    for spec, goal, evidence in corpus(n, seed):
        total += 1
        bad, facts = check_pair(spec, goal, evidence)
        stats["status_" + facts["status"]] += 1
        stats["cert_" + facts["cert"]] += 1
        stats["flat" if isinstance(spec.get("rules"), list) else "mapping"] += 1
        if bad:
            if len(failures) < 10:
                failures.append(
                    f"pair #{total - 1}: goal={goal!r} evidence={evidence} spec={spec}\n    " + "; ".join(bad)
                )
        else:
            agree += 1
    return total, agree, stats, failures
