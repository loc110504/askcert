"""Golden regression corpus (``cases.json``) with exact expected outputs.

Each entry holds a rule document, a goal, partial evidence and the exact expected
``status`` / ``certificate`` / ``relevant_unknowns`` / ``witnesses`` (witnesses are the
lexicographically smallest worlds under the default variable order).  The expectations
were derived by hand from the paper definitions and cross-checked against the brute-force
oracle when the file was written.

RULE FOR CONTRIBUTORS: every counterexample ever found by Hypothesis (or by a user, or by
the seeded corpus) MUST be appended to ``cases.json`` together with its correct expected
output, so that the bug can never silently come back.  ``Case.as_json()`` in
``tests/strategies.py`` prints a paste-ready fragment; the oracle in
``tests/oracles/bruteforce.py`` (``decision``, ``relevant``, ``lexicographic_certificate``,
``witnesses``) gives the expected values.  Keep ids unique and descriptions short.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from askcert import AskCert, CertificationResult, RuleSet
from tests.oracles import bruteforce as bf

CASES = json.loads((Path(__file__).with_name("cases.json")).read_text(encoding="utf-8"))["cases"]
IDS = [c["id"] for c in CASES]
RESULT_KEYS = [
    "schema_version",
    "goal",
    "status",
    "evidence",
    "certificate",
    "relevant_unknowns",
    "witnesses",
]


def expected_dict(case):
    """The full ``to_dict()`` the engine must produce for this entry."""
    exp = case["expected"]
    known = {a: v for a, v in case["evidence"].items() if v is not None}
    return {
        "schema_version": "1",
        "goal": case["goal"],
        "status": exp["status"],
        "evidence": dict(sorted(known.items())),
        "certificate": exp["certificate"] and dict(sorted(exp["certificate"].items())),
        "relevant_unknowns": exp["relevant_unknowns"],
        "witnesses": exp["witnesses"],
    }


def test_corpus_is_well_formed():
    assert len(CASES) >= 30
    assert len(set(IDS)) == len(IDS), "duplicate case ids"
    for case in CASES:
        assert set(case) == {"id", "description", "rules", "goal", "evidence", "expected"}, case["id"]
        assert set(case["expected"]) == {"status", "certificate", "relevant_unknowns", "witnesses"}
        assert case["expected"]["status"] in {"TRUE", "FALSE", "UNKNOWN"}
        decided = case["expected"]["status"] != "UNKNOWN"
        assert (case["expected"]["certificate"] is not None) == decided, case["id"]
        assert (case["expected"]["relevant_unknowns"] == []) == decided, case["id"]
        assert (case["expected"]["witnesses"] is None) == decided, case["id"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_golden_case_exact_outputs(case):
    engine = AskCert(case["rules"])
    res = engine.certify(case["goal"], case["evidence"])
    exp = case["expected"]
    assert res.status == exp["status"]
    assert (None if res.certificate is None else dict(res.certificate)) == exp["certificate"]
    assert list(res.relevant_unknowns) == exp["relevant_unknowns"]
    assert (None if res.witnesses is None else res.witnesses.to_dict()) == exp["witnesses"]
    # whole result document, byte for byte (key order included)
    got = res.to_dict()
    assert list(got) == RESULT_KEYS
    assert json.dumps(got) == json.dumps(expected_dict(case))
    # individual entry points
    assert engine.evaluate(case["goal"], case["evidence"]) == exp["status"]
    cert = engine.find_certificate(case["goal"], case["evidence"])
    assert (None if cert is None else dict(cert)) == exp["certificate"]
    assert list(engine.find_relevant_unknowns(case["goal"], case["evidence"])) == exp["relevant_unknowns"]
    wit = engine.find_witnesses(case["goal"], case["evidence"])
    assert (None if wit is None else wit.to_dict()) == exp["witnesses"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_golden_case_survives_serialization(case):
    rs = RuleSet.from_dict(case["rules"])
    assert RuleSet.from_dict(rs.to_dict()) == rs
    assert RuleSet.from_json(json.dumps(case["rules"])) == rs
    res = AskCert(RuleSet.from_json(rs.to_json())).certify(case["goal"], case["evidence"])
    assert res.to_dict() == expected_dict(case)
    assert CertificationResult.from_dict(json.loads(res.to_json())) == res


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_golden_case_is_independent_of_variable_order(case):
    rs = RuleSet.from_dict(case["rules"])
    engine = AskCert(rs, variable_order=list(reversed(rs.atoms)))
    res = engine.certify(case["goal"], case["evidence"])
    exp = case["expected"]
    assert res.status == exp["status"]
    assert (None if res.certificate is None else dict(res.certificate)) == exp["certificate"]
    assert list(res.relevant_unknowns) == exp["relevant_unknowns"]
    if res.witnesses is not None:  # witnesses may differ with the order but must be valid
        o = bf.Oracle(case["rules"])
        assert o.is_valid_witness(case["goal"], case["evidence"], res.witnesses.true_world, True)
        assert o.is_valid_witness(case["goal"], case["evidence"], res.witnesses.false_world, False)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_golden_expectations_agree_with_brute_force_oracle(case):
    """Guards the corpus itself against typos: the oracle must reproduce every expected value."""
    o = bf.Oracle(case["rules"])
    g, ev, exp = case["goal"], case["evidence"], case["expected"]
    assert o.decision(g, ev) == exp["status"]
    assert list(o.relevant(g, ev)) == exp["relevant_unknowns"]
    assert o.lexicographic_certificate(g, ev) == exp["certificate"]
    cert = exp["certificate"]
    if cert is not None:
        assert o.is_sufficient(g, cert, exp["status"]) and o.is_subset_minimal(g, cert, exp["status"])
    w = o.witnesses(g, ev)
    assert (None if w is None else {"true": w[0], "false": w[1]}) == exp["witnesses"]


def test_corpus_covers_the_headline_scenarios():
    """The scenarios the paper and contract call out must stay in the corpus."""
    ids = set(IDS)
    for needed in (
        "paper_and3_unknown",
        "paper_and3_false",
        "tautology_unknown_atom",
        "contradiction_unknown_atom",
        "alt_or_both_true",
        "exception_unknown_is_not_false",
        "repeated_fact_outer_true",
        "contract_example",
    ):
        assert needed in ids
