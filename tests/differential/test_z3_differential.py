"""z3 vs askcert on the same Hypothesis inputs (independent symbolic oracle, no BDDs).

residual ``f|K`` UNSAT -> FALSE; ``not f|K`` UNSAT -> TRUE; else UNKNOWN; relevance by
SAT of ``f|K[a=0] xor f|K[a=1]``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("z3")

from hypothesis import given

from askcert import AskCert
from tests.oracles import bruteforce as bf
from tests.oracles import z3_oracle
from tests.strategies import cases

pytestmark = pytest.mark.z3


@given(cases())
def test_z3_agrees_with_askcert_on_status_and_relevant_unknowns(case):
    z = z3_oracle.Z3Oracle(case.spec)
    res = AskCert(case.spec).certify(case.goal, case.evidence)
    assert res.status == z.decision(case.goal, case.evidence)
    assert res.relevant_unknowns == z.relevant(case.goal, case.evidence)


@given(cases())
def test_z3_confirms_certificate_is_sufficient_and_minimal(case):
    z = z3_oracle.Z3Oracle(case.spec)
    res = AskCert(case.spec).certify(case.goal, case.evidence, witnesses=False)
    if res.certificate is None:
        assert z.decision(case.goal, case.evidence) == bf.UNKNOWN
        return
    cert = dict(res.certificate)
    assert z.decision(case.goal, cert) == res.status  # sufficiency
    assert z.is_subset_minimal(case.goal, cert, res.status)  # subset-minimality


@given(cases())
def test_z3_confirms_witnesses(case):
    z = z3_oracle.Z3Oracle(case.spec)
    wit = AskCert(case.spec).find_witnesses(case.goal, case.evidence)
    if wit is None:
        assert z.decision(case.goal, case.evidence) != bf.UNKNOWN
        return
    # a complete assignment is a (decided) evidence: z3 must evaluate it to the stated outcome
    assert z.decision(case.goal, dict(wit.true_world)) == bf.TRUE
    assert z.decision(case.goal, dict(wit.false_world)) == bf.FALSE
    known = {a: v for a, v in case.evidence.items() if v is not None}
    for world in (wit.true_world, wit.false_world):
        assert all(world[a] == v for a, v in known.items() if a in world)


@given(cases())
def test_the_two_oracles_agree_with_each_other(case):
    """Cross-check of the oracles themselves (brute force vs z3) on every generated input."""
    o, z = bf.Oracle(case.spec), z3_oracle.Z3Oracle(case.spec)
    assert o.decision(case.goal, case.evidence) == z.decision(case.goal, case.evidence)
    assert o.relevant(case.goal, case.evidence) == z.relevant(case.goal, case.evidence)
