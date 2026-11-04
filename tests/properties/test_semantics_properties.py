"""Hypothesis properties of the core semantics, each checked against the brute-force oracle.

Paper references: Dec(g,K) (Sec. 3), supporting certificate (subset-minimal S subset of K),
relevant unknowns Rel(g,K), opposite-outcome witnesses, Prop. 1(i) decision stability and
Prop. 1(ii) resolution completeness.
"""

from __future__ import annotations

import itertools

from hypothesis import event, given
from hypothesis import strategies as st

from askcert import AskCert, Status
from tests.oracles import bruteforce as bf
from tests.strategies import cases, evidences, known_only


def _setup(case):
    return AskCert(case.spec), bf.Oracle(case.spec)


@given(cases())
def test_structure_atoms_and_cone_match_oracle(case):
    """``RuleSet.atoms`` / ``cone(goal)`` are the declared-or-referenced base atoms / reachable atoms."""
    engine, o = _setup(case)
    assert engine.rules.atoms == tuple(o.atoms)
    assert engine.rules.cone(case.goal) == o.cone(case.goal)
    assert list(engine.rules.rules) == list(o.rules)


@given(cases())
def test_decision_equals_completion_semantics(case):
    """Dec(g,K) = TRUE / FALSE / UNKNOWN over Omega(K), unknown never False (paper Sec. 3)."""
    engine, o = _setup(case)
    expected = o.decision(case.goal, case.evidence)
    event(f"status={expected}")
    assert engine.evaluate(case.goal, case.evidence) == expected
    assert engine.certify(case.goal, case.evidence).status == expected
    assert isinstance(engine.evaluate(case.goal, case.evidence), Status)


@given(cases())
def test_certificate_sufficient_minimal_and_consistent(case):
    """S subset of K on the cone, Dec(g,S)=Dec(g,K), and removing any single fact breaks it."""
    engine, o = _setup(case)
    status = o.decision(case.goal, case.evidence)
    res = engine.certify(case.goal, case.evidence, witnesses=False)
    if status == bf.UNKNOWN:
        assert res.certificate is None
        return
    assert res.certificate is not None
    cert = dict(res.certificate)
    known, cone = known_only(case.evidence), set(o.cone(case.goal))
    event(f"certificate_size={min(len(cert), 5)}")
    # consistency: certificate subset of (evidence restricted to cone), same values
    assert set(cert) <= cone
    assert all(a in known and known[a] is v for a, v in cert.items())
    assert all(type(v) is bool for v in cert.values())
    # sufficiency
    assert o.is_sufficient(case.goal, cert, status)
    # subset-minimality (NOT minimum cardinality)
    assert o.is_subset_minimal(case.goal, cert, status)
    # the certificate certifies itself
    assert dict(engine.certify(case.goal, cert, witnesses=False).certificate) == cert


@given(cases())
def test_certificate_is_the_lexicographic_deletion_result(case):
    """Contract Sec. 1: S=K∩cone, then drop atoms in sorted order while the decision is preserved."""
    engine, o = _setup(case)
    expected = o.lexicographic_certificate(case.goal, case.evidence)
    got = engine.find_certificate(case.goal, case.evidence)
    assert (got is None) == (expected is None)
    if expected is not None:
        assert dict(got) == expected


@given(cases())
def test_relevant_unknowns_sound_and_complete(case):
    """Rel(g,K): exactly the unknown atoms a with f(w[a=0]) != f(w[a=1]) for some w in Omega(K)."""
    engine, o = _setup(case)
    expected = o.relevant(case.goal, case.evidence)
    got = engine.find_relevant_unknowns(case.goal, case.evidence)
    event(f"relevant={min(len(expected), 4)}")
    assert not (set(got) - set(expected)), "unsound: reported an irrelevant atom"
    assert not (set(expected) - set(got)), "incomplete: missed a relevant atom"
    assert got == expected and got == tuple(sorted(got))
    known = known_only(case.evidence)
    assert all(a not in known and a in o.cone(case.goal) for a in got)
    assert (got == ()) == (o.decision(case.goal, case.evidence) != bf.UNKNOWN)
    assert engine.certify(case.goal, case.evidence, witnesses=False).relevant_unknowns == got


@given(cases())
def test_witnesses_agree_with_evidence_complete_and_opposite(case):
    """Two complete cone worlds agreeing with K, with f=1 and f=0 respectively."""
    engine, o = _setup(case)
    status = o.decision(case.goal, case.evidence)
    wit = engine.find_witnesses(case.goal, case.evidence)
    if status != bf.UNKNOWN:
        assert wit is None
        return
    assert wit is not None
    assert o.is_valid_witness(case.goal, case.evidence, wit.true_world, True)
    assert o.is_valid_witness(case.goal, case.evidence, wit.false_world, False)
    assert list(wit.true_world) == list(wit.false_world) == list(o.cone(case.goal))
    assert dict(wit.true_world) != dict(wit.false_world)
    assert engine.certify(case.goal, case.evidence).witnesses == wit


@given(cases())
def test_witnesses_are_lexicographically_smallest_under_default_order(case):
    """Contract: False-branch-first DFS over the ROBDD (default order = sorted atoms), unfixed atoms False."""
    engine, o = _setup(case)
    expected = o.witnesses(case.goal, case.evidence)
    wit = engine.find_witnesses(case.goal, case.evidence)
    assert (wit is None) == (expected is None)
    if expected is not None:
        assert (dict(wit.true_world), dict(wit.false_world)) == expected


@given(case=cases(), data=st.data())
def test_decision_stability_prop1_i(case, data):
    """Prop. 1(i): any evidence extending the certificate keeps the status."""
    engine, o = _setup(case)
    res = engine.certify(case.goal, case.evidence, witnesses=False)
    if res.certificate is None:
        return
    cert = dict(res.certificate)
    extra = known_only(data.draw(evidences(o.atoms)))
    # (a) arbitrary extra facts overridden by the certificate (may even contradict the old evidence)
    assert engine.evaluate(case.goal, {**extra, **cert}) == res.status
    # (b) extra facts consistent with the old evidence
    assert engine.evaluate(case.goal, {**extra, **known_only(case.evidence)}) == res.status
    # (c) the oracle agrees that the proposition holds (guards the test itself)
    assert o.decision(case.goal, {**extra, **cert}) == res.status


@given(case=cases(), data=st.data())
def test_resolution_completeness_prop1_ii(case, data):
    """Prop. 1(ii): assigning every relevant unknown (any values) yields a decided status."""
    engine, o = _setup(case)
    res = engine.certify(case.goal, case.evidence, witnesses=False)
    if res.status != Status.UNKNOWN:
        return
    rel = res.relevant_unknowns
    assert rel
    base = known_only(case.evidence)
    if len(rel) <= 3:
        assignments = [
            dict(zip(rel, bits, strict=True)) for bits in itertools.product([False, True], repeat=len(rel))
        ]
    else:
        assignments = [{a: data.draw(st.booleans()) for a in rel} for _ in range(3)]
    for values in assignments:
        full = {**base, **values}
        got = engine.evaluate(case.goal, full)
        assert got != Status.UNKNOWN
        assert got == o.decision(case.goal, full)
        assert o.decision(case.goal, full) != bf.UNKNOWN


@given(cases())
def test_none_and_absent_are_the_same_unknown(case):
    """``None`` and a missing key both mean unknown; evidence on atoms outside the cone is ignored."""
    engine, o = _setup(case)
    known = known_only(case.evidence)
    r1 = engine.certify(case.goal, case.evidence)
    r2 = engine.certify(case.goal, known)
    r3 = engine.certify(case.goal, {**{a: None for a in o.atoms}, **known})
    assert r1.to_dict() == r2.to_dict() == r3.to_dict()
    cone = set(o.cone(case.goal))
    in_cone = {a: v for a, v in known.items() if a in cone}
    r4 = engine.certify(case.goal, in_cone)
    assert (r4.status, r4.certificate, r4.relevant_unknowns, r4.witnesses) == (
        r1.status,
        r1.certificate,
        r1.relevant_unknowns,
        r1.witnesses,
    )
