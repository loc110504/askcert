"""Hypothesis properties of the engine as a system: serialization, invariance, determinism, no leakage."""

from __future__ import annotations

import copy
import json

from hypothesis import given
from hypothesis import strategies as st

from askcert import AskCert, CertificationResult, RuleSet
from tests.oracles import bruteforce as bf
from tests.strategies import cases, evidences


def _core(res):
    """What must not depend on variable order (witnesses may)."""
    return (res.status, res.certificate, res.relevant_unknowns)


def reordered(spec, data):
    """Same document with the rules (and declared atoms) listed in a different order."""
    spec = copy.deepcopy(spec)
    if "rules" not in spec:  # shorthand form: the mapping itself is the rule list
        return {k: spec[k] for k in data.draw(st.permutations(list(spec)))}
    body = spec["rules"]
    if isinstance(body, list):
        spec["rules"] = list(data.draw(st.permutations(body)))
    else:
        spec["rules"] = {k: body[k] for k in data.draw(st.permutations(list(body)))}
    if "atoms" in spec:
        spec["atoms"] = list(data.draw(st.permutations(spec["atoms"])))
    return spec


# ---------------------------------------------------------------- serialization


@given(cases())
def test_rule_set_serialization_round_trip_preserves_rules_and_decisions(case):
    """from_dict(to_dict(rs)) == rs; JSON round trip too; decisions and certificates unchanged."""
    rs = RuleSet.from_dict(case.spec)
    d = rs.to_dict()
    rs2, rs3 = RuleSet.from_dict(d), RuleSet.from_json(rs.to_json())
    assert rs2 == rs and rs3 == rs
    assert rs2.to_dict() == d and json.loads(json.dumps(d)) == d
    base = AskCert(rs).certify(case.goal, case.evidence)
    assert AskCert(rs2).certify(case.goal, case.evidence) == base
    assert AskCert(rs3).certify(case.goal, case.evidence) == base
    # the oracle reading the *serialised* document agrees with the engine on the original
    o2 = bf.Oracle(d)
    assert o2.decision(case.goal, case.evidence) == base.status
    assert o2.relevant(case.goal, case.evidence) == base.relevant_unknowns


@given(cases())
def test_result_serialization_round_trip(case):
    """CertificationResult.from_dict(r.to_dict()) == r, also through JSON text."""
    engine = AskCert(case.spec)
    for witnesses in (True, False):
        res = engine.certify(case.goal, case.evidence, witnesses=witnesses)
        assert CertificationResult.from_dict(res.to_dict()) == res
        assert CertificationResult.from_dict(json.loads(res.to_json())) == res
        assert list(res.to_dict()) == [
            "schema_version",
            "goal",
            "status",
            "evidence",
            "certificate",
            "relevant_unknowns",
            "witnesses",
        ]


# ---------------------------------------------------------------- invariance


@given(case=cases(), data=st.data())
def test_invariant_to_variable_order(case, data):
    """Status, certificate and relevant unknowns never depend on the BDD variable order."""
    rs = RuleSet.from_dict(case.spec)
    order = data.draw(st.permutations(list(rs.atoms)))
    base = AskCert(rs).certify(case.goal, case.evidence)
    other = AskCert(rs, variable_order=order).certify(case.goal, case.evidence)
    assert _core(other) == _core(base)
    # witnesses may differ with the order, but must still be valid
    o = bf.Oracle(case.spec)
    if other.witnesses is not None:
        assert o.is_valid_witness(case.goal, case.evidence, other.witnesses.true_world, True)
        assert o.is_valid_witness(case.goal, case.evidence, other.witnesses.false_world, False)
    assert (
        AskCert(rs, variable_order=tuple(reversed(rs.atoms))).evaluate(case.goal, case.evidence)
        == base.status
    )


@given(case=cases(), data=st.data())
def test_invariant_to_rule_declaration_order(case, data):
    """Listing the rules (or declared atoms) in another order changes nothing observable."""
    spec2 = reordered(case.spec, data)
    rs1, rs2 = RuleSet.from_dict(case.spec), RuleSet.from_dict(spec2)
    assert rs1.rules == rs2.rules  # mapping equality ignores order
    assert sorted(rs1.declared_atoms or ()) == sorted(rs2.declared_atoms or ())
    assert rs1.atoms == rs2.atoms and rs1.cone(case.goal) == rs2.cone(case.goal)
    r1 = AskCert(rs1).certify(case.goal, case.evidence)
    r2 = AskCert(rs2).certify(case.goal, case.evidence)
    assert r1 == r2  # default variable order is sorted atoms, so even the witnesses coincide


# ---------------------------------------------------------------- determinism / state


@given(case=cases())
def test_determinism_two_engines_same_output(case):
    """Two engines on the same input produce byte-identical result documents."""
    a = AskCert(case.spec).certify(case.goal, case.evidence)
    b = AskCert(case.spec).certify(case.goal, case.evidence)
    assert a.to_dict() == b.to_dict() and a.to_json() == b.to_json()
    engine = AskCert(case.spec)
    assert engine.certify(case.goal, case.evidence).to_json() == a.to_json()
    assert engine.certify(case.goal, case.evidence).to_json() == a.to_json()  # second call, same engine


@given(case=cases(), data=st.data())
def test_no_state_leakage_between_queries(case, data):
    """Repeated and interleaved queries on one engine are identical to fresh-engine answers
    and leave ``node_count`` unchanged (checkpoint/rollback)."""
    o = bf.Oracle(case.spec)
    engine = AskCert(case.spec)
    extra_goals = data.draw(st.lists(st.sampled_from([*o.rules, *o.atoms]), max_size=2))
    goals = list(dict.fromkeys([case.goal, *extra_goals]))
    evs = [case.evidence, *(data.draw(evidences(list(o.atoms))) for _ in range(3))]
    for g in goals:  # first use of a goal may add compiled nodes; do that before measuring
        engine.certify(g, {})
    n0 = engine.node_count
    queries = [(g, e) for g in goals for e in evs]
    first = []
    for g, e in queries:
        first.append(engine.certify(g, e))
        assert engine.node_count == n0
    for i in reversed(range(len(queries))):  # reverse order = interleaved differently
        g, e = queries[i]
        assert engine.certify(g, e) == first[i]
        assert engine.node_count == n0
        assert engine.evaluate(g, e) == first[i].status
        assert engine.find_relevant_unknowns(g, e) == first[i].relevant_unknowns
        assert engine.find_certificate(g, e) == first[i].certificate
        assert engine.find_witnesses(g, e) == first[i].witnesses
        assert engine.node_count == n0
    fresh = AskCert(case.spec)
    for (g, e), res in zip(queries, first, strict=True):
        assert fresh.certify(g, e) == res
    assert engine.certify_many(case.goal, evs) == [engine.certify(case.goal, e) for e in evs]
    assert engine.node_count == n0


@given(case=cases())
def test_queries_do_not_mutate_inputs(case):
    spec, evidence = copy.deepcopy(case.spec), copy.deepcopy(case.evidence)
    engine = AskCert(case.spec)
    engine.certify(case.goal, case.evidence)
    engine.certify_many(case.goal, [case.evidence])
    assert case.spec == spec and case.evidence == evidence
