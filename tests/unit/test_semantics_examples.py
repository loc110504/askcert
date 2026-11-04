"""Hand-checked semantics: constants, empty operators, xor parity, implies, unless,
nested rules, rule/atom goals, repeated atoms, document shapes (paper Sec. 3 + contract Sec. 2)."""

from __future__ import annotations

import itertools

import pytest

from askcert import AskCert, RuleSet

T, F = True, False


def status(rules, goal, evidence=None):
    return AskCert(rules).evaluate(goal, evidence)


# ---------------------------------------------------------------- constants / empty operators


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (True, "TRUE"),
        (False, "FALSE"),
        ({"all": []}, "TRUE"),
        ({"any": []}, "FALSE"),
        ({"xor": []}, "FALSE"),
        ({"not": True}, "FALSE"),
        ({"not": False}, "TRUE"),
        ({"not": {"all": []}}, "FALSE"),
        ({"all": [True, True]}, "TRUE"),
        ({"all": [True, False]}, "FALSE"),
        ({"any": [False, False]}, "FALSE"),
        ({"any": [False, True]}, "TRUE"),
        ({"xor": [True]}, "TRUE"),
        ({"xor": [True, True]}, "FALSE"),
        ({"xor": [True, True, True]}, "TRUE"),
        ({"implies": [True, False]}, "FALSE"),
        ({"implies": [False, False]}, "TRUE"),
        ({"all": [], "unless": []}, "TRUE"),
        ({"any": [], "unless": []}, "FALSE"),
        ({"all": [], "unless": [True]}, "FALSE"),
        ({"any": [True], "unless": [False]}, "TRUE"),
    ],
)
def test_constant_rules_have_empty_cone_and_empty_certificate(expr, expected):
    engine = AskCert({"g": expr})
    res = engine.certify("g")
    assert res.status == expected
    assert res.certificate == {}
    assert res.relevant_unknowns == ()
    assert res.witnesses is None
    assert engine.rules.cone("g") == ()


def test_constant_rule_with_unrelated_atom_evidence_still_has_empty_certificate():
    rules = {"g": True, "h": {"all": ["a"]}}
    res = AskCert(rules).certify("g", {"a": True})
    assert res.status == "TRUE" and res.certificate == {}


def test_constants_inside_operators_simplify():
    rules = {"g": {"all": ["a", True]}, "h": {"any": ["a", False]}, "k": {"all": ["a", False]}}
    engine = AskCert(rules)
    assert engine.certify("g", {"a": T}).certificate == {"a": T}
    assert engine.find_relevant_unknowns("g") == ("a",)
    assert engine.evaluate("h", {"a": F}) == "FALSE"
    assert engine.evaluate("k") == "FALSE"  # a and false is FALSE with a unknown
    assert engine.certify("k", {"a": T}).certificate == {}


# ---------------------------------------------------------------- xor parity


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_xor_is_odd_parity_over_every_complete_assignment(n):
    """``xor`` is 1 iff an odd number of operands are 1 (all 2^n worlds)."""
    atoms = [f"x{i}" for i in range(n)]
    engine = AskCert({"g": {"xor": atoms}})
    for bits in itertools.product([F, T], repeat=n):
        expected = "TRUE" if sum(bits) % 2 else "FALSE"
        assert engine.evaluate("g", dict(zip(atoms, bits, strict=True))) == expected


@pytest.mark.parametrize("known", [0, 1, 2])
def test_xor_with_any_unknown_atom_is_unknown_and_every_unknown_is_relevant(known):
    """Flipping any single unknown input flips the parity, so all unknowns are relevant."""
    atoms = ["a", "b", "c"]
    engine = AskCert({"g": {"xor": atoms}})
    evidence = {a: T for a in atoms[:known]}
    res = engine.certify("g", evidence)
    assert res.status == "UNKNOWN"
    assert res.relevant_unknowns == tuple(atoms[known:])
    assert res.certificate is None


def test_xor_witnesses_have_opposite_parity():
    res = AskCert({"g": {"xor": ["a", "b", "c"]}}).certify("g", {"a": T, "b": F})
    assert res.relevant_unknowns == ("c",)
    assert dict(res.witnesses.true_world) == {"a": T, "b": F, "c": F}
    assert dict(res.witnesses.false_world) == {"a": T, "b": F, "c": T}


def test_xor_of_repeated_atom_cancels():
    engine = AskCert({"even": {"xor": ["a", "a"]}, "odd": {"xor": ["a", "a", "a"]}})
    assert engine.certify("even").status == "FALSE"
    assert engine.certify("even").certificate == {}
    assert engine.certify("odd").status == "UNKNOWN"
    assert engine.find_relevant_unknowns("odd") == ("a",)


def test_xor_certificate_needs_every_operand():
    res = AskCert({"g": {"xor": ["a", "b", "c"]}}).certify("g", {"a": T, "b": T, "c": T})
    assert res.status == "TRUE" and res.certificate == {"a": T, "b": T, "c": T}


# ---------------------------------------------------------------- implies


@pytest.mark.parametrize(
    ("evidence", "expected", "cert"),
    [
        ({"a": T, "b": T}, "TRUE", {"b": T}),  # lexicographic deletion drops a
        ({"a": T, "b": F}, "FALSE", {"a": T, "b": F}),
        ({"a": F, "b": T}, "TRUE", {"b": T}),  # lexicographic deletion drops a first
        ({"a": F, "b": F}, "TRUE", {"a": F}),
        ({"a": F}, "TRUE", {"a": F}),
        ({"b": T}, "TRUE", {"b": T}),
        ({"a": T}, "UNKNOWN", None),
        ({"b": F}, "UNKNOWN", None),
        ({}, "UNKNOWN", None),
    ],
)
def test_implies_is_not_a_or_b(evidence, expected, cert):
    res = AskCert({"g": {"implies": ["a", "b"]}}).certify("g", evidence)
    assert res.status == expected
    assert res.certificate == cert


def test_implies_relevant_unknowns_and_witnesses():
    engine = AskCert({"g": {"implies": ["a", "b"]}})
    assert engine.find_relevant_unknowns("g", {"a": T}) == ("b",)
    assert engine.find_relevant_unknowns("g", {"b": F}) == ("a",)
    res = engine.certify("g", {})
    assert res.relevant_unknowns == ("a", "b")
    assert dict(res.witnesses.true_world) == {"a": F, "b": F}
    assert dict(res.witnesses.false_world) == {"a": T, "b": F}


# ---------------------------------------------------------------- unless (classical negation of exceptions)


@pytest.mark.parametrize("core", ["all", "any"])
def test_unless_is_core_and_not_any_exception(core):
    """``{core: [a], unless: [e1, e2]}`` = core AND NOT(e1 OR e2)."""
    engine = AskCert({"g": {core: ["a"], "unless": ["e1", "e2"]}})
    assert engine.evaluate("g", {"a": T, "e1": F, "e2": F}) == "TRUE"
    assert engine.evaluate("g", {"a": T, "e1": T}) == "FALSE"
    assert engine.evaluate("g", {"a": T, "e2": T}) == "FALSE"
    assert engine.evaluate("g", {"a": F}) == "FALSE"
    assert engine.evaluate("g", {"a": T}) == "UNKNOWN"


def test_unknown_exception_is_not_treated_as_false():
    """Classical negation: an unknown exception blocks TRUE (not negation-as-failure)."""
    res = AskCert({"g": {"all": ["a"], "unless": ["e"]}}).certify("g", {"a": T})
    assert res.status == "UNKNOWN"
    assert res.relevant_unknowns == ("e",)
    assert dict(res.witnesses.true_world) == {"a": T, "e": F}
    assert dict(res.witnesses.false_world) == {"a": T, "e": T}


def test_exception_certificate():
    engine = AskCert({"g": {"all": ["a"], "unless": ["e"]}})
    assert engine.certify("g", {"a": T, "e": F}).certificate == {"a": T, "e": F}
    # exception fires: FALSE, and a is dropped by lexicographic deletion
    assert engine.certify("g", {"a": T, "e": T}).certificate == {"e": T}


def test_empty_unless_means_no_exception():
    with_empty = AskCert({"g": {"any": ["a", "b"], "unless": []}})
    without = AskCert({"g": {"any": ["a", "b"]}})
    for ev in ({}, {"a": T}, {"a": F}, {"a": F, "b": F}):
        assert with_empty.certify("g", ev) == without.certify("g", ev)


def test_any_with_unless_empty_core_is_false():
    assert status({"g": {"any": [], "unless": ["e"]}}, "g") == "FALSE"
    assert status({"g": {"all": [], "unless": ["e"]}}, "g") == "UNKNOWN"


def test_unless_references_rules_and_negations():
    rules = {"blocked": {"all": ["x", "!y"]}, "g": {"any": ["a", "b"], "unless": ["blocked", "!z"]}}
    engine = AskCert(rules)
    assert engine.evaluate("g", {"a": T, "x": F, "z": T}) == "TRUE"
    assert engine.evaluate("g", {"a": T, "x": T, "y": F, "z": T}) == "FALSE"
    assert engine.evaluate("g", {"a": T, "z": F}) == "FALSE"  # "!z" is an exception
    assert engine.find_relevant_unknowns("g", {"a": T, "z": T}) == ("x", "y")


# ---------------------------------------------------------------- nested rules / goals / repeated atoms


def test_rule_can_reference_later_declared_rule():
    rules = {"top": {"all": ["mid", "c"]}, "mid": {"any": ["a", "b"]}}
    engine = AskCert(rules)
    assert engine.certify("top", {"a": T, "c": T}).certificate == {"a": T, "c": T}
    assert engine.rules.cone("top") == ("a", "b", "c")
    assert engine.rules.cone("mid") == ("a", "b")


def test_rule_and_atom_goals():
    engine = AskCert({"g": {"all": ["a", "b"]}})
    assert engine.evaluate("g", {"a": T, "b": T}) == "TRUE"
    assert engine.evaluate("a", {"a": T}) == "TRUE"  # atom as goal
    assert engine.evaluate("a", {"b": T}) == "UNKNOWN"  # evidence outside the cone is ignored
    res = engine.certify("a")
    assert res.relevant_unknowns == ("a",)
    assert dict(res.witnesses.true_world) == {"a": T}
    assert dict(res.witnesses.false_world) == {"a": F}
    assert engine.certify("b", {"a": F, "b": F}).certificate == {"b": F}


def test_declared_but_unused_atom_is_a_valid_goal_and_evidence_key():
    engine = AskCert({"atoms": ["a", "unused"], "rules": {"g": "a"}})
    assert engine.evaluate("unused", {"unused": F}) == "FALSE"
    assert engine.evaluate("g", {"unused": T}) == "UNKNOWN"
    assert engine.rules.atoms == ("a", "unused")
    assert engine.rules.declared_atoms == ("a", "unused")


def test_evidence_outside_cone_is_ignored_for_decision_and_certificate():
    engine = AskCert({"g": {"all": ["a", "b"]}, "h": {"any": ["c", "d"]}})
    res = engine.certify("g", {"a": F, "c": T, "d": T})
    assert res.status == "FALSE"
    assert res.certificate == {"a": F}  # only cone atoms appear in the certificate
    assert res.evidence == {"a": F, "c": T, "d": T}  # known facts supplied (None dropped)


def test_repeated_atoms_within_one_rule():
    """``a and (a or b)`` == a ; ``a or (not a and b)`` == a or b."""
    engine = AskCert(
        {"absorb": {"all": ["a", {"any": ["a", "b"]}]}, "g": {"any": ["a", {"all": ["!a", "b"]}]}}
    )
    assert engine.find_relevant_unknowns("absorb") == ("a",)
    assert engine.certify("absorb", {"a": T, "b": T}).certificate == {"a": T}
    assert engine.evaluate("absorb", {"b": T}) == "UNKNOWN"
    assert engine.find_relevant_unknowns("g") == ("a", "b")
    assert engine.evaluate("g", {"a": F, "b": T}) == "TRUE"
    assert engine.evaluate("g", {"a": F, "b": F}) == "FALSE"


def test_repeated_atoms_across_nested_rules_share_one_variable():
    rules = {
        "inner": {"any": ["a", "b"]},
        "outer": {"all": ["inner", "a"]},  # == a
        "taut": {"any": ["!a", "inner"]},  # == TRUE
        "contra": {"all": ["a", {"not": "inner"}]},  # == FALSE
    }
    engine = AskCert(rules)
    assert engine.certify("outer", {"a": T, "b": T}).certificate == {"a": T}
    assert engine.certify("outer", {"a": F, "b": T}).certificate == {"a": F}
    assert engine.certify("taut").status == "TRUE" and engine.certify("taut").certificate == {}
    assert engine.certify("contra", {"a": T}).status == "FALSE"
    assert engine.certify("contra", {"a": T}).certificate == {}


def test_deeply_nested_rule_chain_small():
    rules = {"r0": "x", **{f"r{i}": {"not": f"r{i - 1}"} for i in range(1, 11)}}
    engine = AskCert(rules)
    assert engine.evaluate("r10", {"x": T}) == "TRUE"  # even number of negations
    assert engine.evaluate("r9", {"x": T}) == "FALSE"
    assert engine.rules.cone("r10") == ("x",)


# ---------------------------------------------------------------- names / bang / document shapes


def test_bang_prefix_is_classical_negation():
    engine = AskCert({"g": {"all": ["!a", "b"]}})
    assert engine.evaluate("g", {"a": F, "b": T}) == "TRUE"
    assert engine.evaluate("g", {"a": T}) == "FALSE"
    assert engine.evaluate("g", {"b": T}) == "UNKNOWN"
    assert engine.find_relevant_unknowns("g", {"b": T}) == ("a",)


def test_bang_on_a_rule_reference():
    engine = AskCert({"p": {"all": ["a", "b"]}, "g": "!p"})
    assert engine.evaluate("g", {"a": F}) == "TRUE"
    assert engine.evaluate("g", {"a": T, "b": T}) == "FALSE"


def test_identifier_names_with_underscores_and_digits():
    engine = AskCert({"Rule_1": {"all": ["_a", "B2", "c_3"]}})
    assert engine.evaluate("Rule_1", {"_a": T, "B2": T, "c_3": T}) == "TRUE"
    assert engine.rules.atoms == ("B2", "_a", "c_3")  # sorted by code point


def test_document_shorthand_and_flat_forms_agree():
    doc = {"schema_version": "1", "rules": {"g": {"any": ["a", "b"], "unless": ["c"]}}}
    short = {"g": {"any": ["a", "b"], "unless": ["c"]}}
    flat = {"rules": [{"name": "g", "op": "ANY", "conditions": ["a", "b"], "exceptions": ["c"]}]}
    flat_p = [{"p": "g", "conditions": ["a", "b"], "exceptions": ["c"]}]  # alias p, default op ANY
    engines = [AskCert(s) for s in (doc, short, flat, {"rules": flat_p})]
    for ev in ({}, {"a": T}, {"c": T}, {"a": F, "b": F}, {"a": T, "c": F}):
        results = [e.certify("g", ev) for e in engines]
        assert all(r == results[0] for r in results[1:])
    assert RuleSet.from_dict(flat) == RuleSet.from_dict(doc)  # flat converts to any/unless


def test_flat_form_all_op_and_defaults():
    rs = RuleSet.from_dict({"rules": [{"name": "g", "op": "ALL", "conditions": ["a", "b"]}, {"name": "h"}]})
    engine = AskCert(rs)
    assert engine.evaluate("g", {"a": T, "b": T}) == "TRUE"
    assert engine.evaluate("g", {"a": F}) == "FALSE"
    assert engine.evaluate("h") == "FALSE"  # default op ANY over no conditions
    assert rs.cone("h") == ()


def test_flat_form_rule_can_reference_other_rules():
    flat = {
        "rules": [
            {"name": "top", "op": "ALL", "conditions": ["low", "c"]},
            {"name": "low", "op": "ANY", "conditions": ["a", "b"]},
        ]
    }
    engine = AskCert(flat)
    assert engine.certify("top", {"b": T, "c": T}).certificate == {"b": T, "c": T}


def test_declared_atoms_strict_mode_accepts_exactly_the_declared_names():
    engine = AskCert({"atoms": ["a", "b"], "rules": {"g": {"all": ["a", "b"]}}})
    assert engine.evaluate("g", {"a": T, "b": T}) == "TRUE"


def test_rule_set_atoms_are_sorted_union_of_declared_and_referenced_non_rules():
    rs = RuleSet.from_dict({"r": {"all": ["z", "m", "r2"]}, "r2": {"any": ["a", "!z"]}})
    assert rs.atoms == ("a", "m", "z")
    assert rs.declared_atoms is None
    assert list(rs.rules) == ["r", "r2"]  # insertion order preserved
