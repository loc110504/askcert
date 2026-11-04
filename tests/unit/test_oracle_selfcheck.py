"""The oracles must themselves be right: check them against hand-derived answers.

No askcert import here.  If these fail the release gate is meaningless.
"""

from __future__ import annotations

import pytest

from tests.oracles import bruteforce as bf
from tests.oracles.known_answers import OPERATOR_TABLE

ROW_IDS = [row[0] for row in OPERATOR_TABLE]


@pytest.mark.parametrize("row", OPERATOR_TABLE, ids=ROW_IDS)
def test_bruteforce_matches_hand_derived_table(row):
    _id, rules, goal, evidence, status, cert, rel, wit = row
    o = bf.Oracle(rules)
    assert o.decision(goal, evidence) == status
    assert o.relevant(goal, evidence) == rel
    assert o.lexicographic_certificate(goal, evidence) == cert
    got = o.witnesses(goal, evidence)
    assert (got is None) == (wit is None)
    if wit is not None:
        assert got == wit
    if cert is not None:
        assert o.is_sufficient(goal, cert, status)
        assert o.is_subset_minimal(goal, cert, status)


@pytest.mark.z3
@pytest.mark.parametrize("row", OPERATOR_TABLE, ids=ROW_IDS)
def test_z3_matches_hand_derived_table(row):
    pytest.importorskip("z3")
    from tests.oracles import z3_oracle

    _id, rules, goal, evidence, status, cert, rel, _wit = row
    assert z3_oracle.decision(rules, goal, evidence) == status
    assert z3_oracle.relevant(rules, goal, evidence) == rel
    if cert is not None:
        assert z3_oracle.Z3Oracle(rules).is_subset_minimal(goal, cert, status)


def test_bruteforce_unknown_is_not_false():
    """Unknown evidence is never treated as False (paper Sec. 3)."""
    assert bf.decision({"g": {"any": ["a"]}}, "g", {}) == "UNKNOWN"
    assert bf.decision({"g": {"all": ["!a"]}}, "g", {}) == "UNKNOWN"
    assert bf.decision({"g": {"all": ["!a"]}}, "g", {"a": None}) == "UNKNOWN"


def test_bruteforce_parses_all_three_forms_identically():
    doc = {
        "schema_version": "1",
        "atoms": ["a", "b", "c"],
        "rules": {"g": {"any": ["a", "b"], "unless": ["c"]}},
    }
    short = {"g": {"any": ["a", "b"], "unless": ["c"]}}
    flat = {"rules": [{"p": "g", "op": "ANY", "conditions": ["a", "b"], "exceptions": ["c"]}]}
    for spec in (doc, short, flat):
        o = bf.Oracle(spec)
        assert o.atoms == ["a", "b", "c"]
        assert o.cone("g") == ("a", "b", "c")
        assert o.decision("g", {"c": True}) == "FALSE"
        assert o.decision("g", {"c": False, "b": True}) == "TRUE"
        assert o.relevant("g", {"c": False}) == ("a", "b")


def test_bruteforce_flat_list_defaults():
    o = bf.Oracle({"rules": [{"name": "g"}, {"name": "h", "op": "ALL"}]})
    assert o.decision("g", {}) == "FALSE"  # default op ANY, no conditions -> empty any
    assert o.decision("h", {}) == "TRUE"  # ALL over nothing


def test_bruteforce_cone_and_atom_goal():
    o = bf.Oracle({"atoms": ["a", "b", "z"], "rules": {"r": "a", "s": {"all": ["r", "!b"]}}})
    assert o.cone("s") == ("a", "b")
    assert o.cone("z") == ("z",)  # declared but unused atom is a valid goal
    assert o.decision("z", {"z": True}) == "TRUE"
    assert o.relevant("z", {}) == ("z",)
