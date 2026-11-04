"""Operator table (paper Sec. 3, completion semantics) with exact outputs.

Every row checks status, certificate, relevant unknowns and witnesses through all
public entry points, once with the unknown atoms *absent* and once with them
explicitly ``None`` (both mean unknown; unknown is never False).
"""

from __future__ import annotations

import pytest

from askcert import AskCert, Status
from tests.oracles.known_answers import OPERATOR_TABLE

ROW_IDS = [row[0] for row in OPERATOR_TABLE]


def _variants(rules, goal, evidence):
    """Evidence with unknowns absent, and with unknowns spelled out as None."""
    from tests.oracles import bruteforce as bf

    cone = bf.cone(rules, goal)
    yield dict(evidence)
    yield {**{a: None for a in cone}, **evidence}


@pytest.mark.parametrize("row", OPERATOR_TABLE, ids=ROW_IDS)
def test_operator_table_row(row):
    """Dec / certificate / Rel / witnesses exactly as derived by hand."""
    _id, rules, goal, evidence, status, cert, rel, wit = row
    for ev in _variants(rules, goal, evidence):
        engine = AskCert(rules)
        res = engine.certify(goal, ev)
        assert res.goal == goal
        assert res.status == status
        assert isinstance(res.status, Status)
        assert res.evidence == evidence  # None dropped
        assert res.certificate == cert
        assert res.relevant_unknowns == rel
        assert res.decided == (status != "UNKNOWN")
        if wit is None:
            assert res.witnesses is None
        else:
            assert res.witnesses is not None
            assert dict(res.witnesses.true_world) == wit[0]
            assert dict(res.witnesses.false_world) == wit[1]
        # the individual entry points agree with certify()
        assert engine.evaluate(goal, ev) == status
        assert engine.find_certificate(goal, ev) == cert
        assert engine.find_relevant_unknowns(goal, ev) == rel
        got = engine.find_witnesses(goal, ev)
        assert (got is None) == (wit is None)
        if wit is not None:
            assert (dict(got.true_world), dict(got.false_world)) == wit


@pytest.mark.parametrize("row", OPERATOR_TABLE, ids=ROW_IDS)
def test_operator_table_without_witnesses(row):
    """``certify(witnesses=False)`` keeps everything but the witnesses."""
    _id, rules, goal, evidence, status, cert, rel, _wit = row
    res = AskCert(rules).certify(goal, evidence, witnesses=False)
    assert (res.status, res.certificate, res.relevant_unknowns) == (status, cert, rel)
    assert res.witnesses is None


def test_decided_example_a_or_not_a_is_true_with_unknown_a():
    """Completion semantics, not Kleene: ``a or not a`` is TRUE although ``a`` is unknown."""
    engine = AskCert({"g": {"any": ["a", {"not": "a"}]}})
    assert engine.evaluate("g", {"a": None}) == "TRUE"
    assert engine.evaluate("g", {}) == Status.TRUE


def test_decided_example_a_and_not_a_is_false_with_unknown_a():
    """``a and not a`` is FALSE although ``a`` is unknown."""
    engine = AskCert({"g": {"all": ["a", "!a"]}})
    assert engine.evaluate("g") == Status.FALSE
