"""Public API shape (contract Sec. 4): return types, None/() iff rules, Status, AST, exceptions."""

from __future__ import annotations

import copy
import dataclasses

import pytest

import askcert
from askcert import (
    AskCert,
    AskCertError,
    CertificationResult,
    EvidenceError,
    ObservationConflictError,
    ResourceLimitExceeded,
    RuleError,
    RuleSet,
    Status,
    Witnesses,
    compile_rules,
)
from askcert.rules import All, Any, Const, Implies, Not, Ref, Xor

T, F = True, False
RULES = {
    "g": {"all": ["a", "b"]},
    "h": {"any": ["a", {"not": "b"}], "unless": ["c"]},
    "t": {"any": ["a", "!a"]},
}
EVIDENCES = [{}, {"a": T}, {"a": F}, {"a": T, "b": T}, {"b": F}, {"a": F, "b": T, "c": T}, {"c": T}]


@pytest.fixture
def engine():
    return AskCert(RULES)


# ---------------------------------------------------------------- iff relations


@pytest.mark.parametrize("goal", ["g", "h", "t", "a"])
@pytest.mark.parametrize("evidence", EVIDENCES)
def test_none_empty_iff_relations(engine, goal, evidence):
    res = engine.certify(goal, evidence)
    cert = engine.find_certificate(goal, evidence)
    rel = engine.find_relevant_unknowns(goal, evidence)
    wit = engine.find_witnesses(goal, evidence)
    unknown = engine.evaluate(goal, evidence) == Status.UNKNOWN
    assert (cert is None) == unknown == (res.certificate is None)
    assert (rel == ()) == (not unknown) == (res.relevant_unknowns == ())
    assert (wit is None) == (not unknown) == (res.witnesses is None)
    assert isinstance(rel, tuple)
    assert res.decided == (not unknown)
    if not unknown:
        assert cert is not None
    else:
        assert isinstance(wit, Witnesses)
        assert wit == res.witnesses
    assert cert == res.certificate and rel == res.relevant_unknowns


def test_certificate_may_be_empty_for_tautology(engine):
    res = engine.certify("t", {"a": T})
    assert res.status == "TRUE" and res.certificate == {} and res.decided


def test_certify_witnesses_false_drops_only_witnesses(engine):
    with_w = engine.certify("g", {"a": T})
    without = engine.certify("g", {"a": T}, witnesses=False)
    assert with_w.status == without.status == "UNKNOWN"
    assert with_w.witnesses is not None and without.witnesses is None
    assert without.relevant_unknowns == with_w.relevant_unknowns == ("b",)
    assert without.certificate is None
    assert dataclasses.replace(with_w, witnesses=None) == without


def test_certify_evidence_defaults_to_empty(engine):
    assert engine.certify("g") == engine.certify("g", None) == engine.certify("g", {})
    assert engine.certify("g").evidence == {}


def test_evidence_in_result_drops_none_and_sorts_keys(engine):
    res = engine.certify("g", {"b": T, "c": None, "a": F})
    assert list(res.evidence) == ["a", "b"]
    assert res.evidence == {"a": F, "b": T}


def test_witnesses_cover_the_whole_cone_and_are_sorted(engine):
    res = engine.certify("h", {"b": T})
    assert res.status == "UNKNOWN"
    wit = res.witnesses
    assert list(wit.true_world) == list(wit.false_world) == ["a", "b", "c"] == list(engine.rules.cone("h"))
    assert wit.to_dict() == {"true": dict(wit.true_world), "false": dict(wit.false_world)}
    assert list(wit.to_dict()) == ["true", "false"]


# ---------------------------------------------------------------- certify_many / compile


def test_certify_many_matches_individual_certify(engine):
    many = engine.certify_many("g", EVIDENCES)
    assert isinstance(many, list)
    assert many == [AskCert(RULES).certify("g", e) for e in EVIDENCES]
    assert [r.evidence for r in many] == [{k: v for k, v in e.items() if v is not None} for e in EVIDENCES]


def test_certify_many_accepts_generators_and_empty_input(engine):
    assert engine.certify_many("g", (e for e in EVIDENCES)) == engine.certify_many("g", list(EVIDENCES))
    assert engine.certify_many("g", []) == []
    assert engine.certify_many("g", iter([])) == []


def test_certify_many_witnesses_flag(engine):
    many = engine.certify_many("g", [{"a": T}, {"a": T, "b": T}], witnesses=False)
    assert [r.status for r in many] == ["UNKNOWN", "TRUE"]
    assert all(r.witnesses is None for r in many)
    assert many[0].relevant_unknowns == ("b",)
    assert engine.certify_many("g", [{"a": T}])[0].witnesses is not None


def test_certify_many_bounded_memory_node_count_is_stable(engine):
    engine.compile()
    before = engine.node_count
    engine.certify_many("g", EVIDENCES * 5)
    assert engine.node_count == before


def test_compile_returns_engine_and_is_idempotent():
    engine = AskCert(RULES)
    assert engine.compile() is engine
    n = engine.node_count
    assert engine.compile("g", "h") is engine
    assert engine.compile() is engine
    assert engine.node_count == n
    assert engine.evaluate("g", {"a": F}) == "FALSE"


def test_compile_subset_of_goals_then_other_goals_still_work():
    engine = AskCert(RULES).compile("g")
    assert engine.evaluate("h", {"a": T, "c": F}) == "TRUE"
    assert engine.evaluate("g", {"a": T, "b": T}) == "TRUE"


def test_compile_rules_helper_returns_engine():
    engine = compile_rules(RULES)
    assert isinstance(engine, AskCert)
    assert engine.evaluate("g", {"a": T, "b": T}) == "TRUE"
    engine2 = compile_rules(RuleSet.from_dict(RULES), goals=["g"], max_nodes=10_000, timeout=30)
    assert isinstance(engine2, AskCert) and engine2.rules == RuleSet.from_dict(RULES)
    assert compile_rules(RULES, goals=[]).evaluate("g", {"a": F}) == "FALSE"
    with pytest.raises(RuleError):
        compile_rules(RULES, goals=["nope"])


def test_compile_rules_passes_engine_kwargs():
    from askcert import ResourceLimitExceeded

    with pytest.raises(ResourceLimitExceeded):
        compile_rules(RULES, max_nodes=2).evaluate("g")
    order = ["c", "b", "a"]
    assert compile_rules(RULES, variable_order=order).evaluate("g", {"a": F}) == "FALSE"


def test_engine_accepts_rule_set_or_mapping_and_exposes_rules():
    rs = RuleSet.from_dict(RULES)
    a, b = AskCert(rs), AskCert(RULES)
    assert a.rules == b.rules == rs
    assert isinstance(a.rules, RuleSet)
    assert a.certify("h", {"a": T}) == b.certify("h", {"a": T})


def test_node_count_is_an_int_and_grows_with_compilation():
    engine = AskCert(RULES)
    n0 = engine.node_count
    engine.compile()
    assert isinstance(n0, int) and engine.node_count > n0


# ---------------------------------------------------------------- Status


def test_status_is_a_str_enum():
    assert issubclass(Status, str)
    assert Status.TRUE == "TRUE" and Status.FALSE == "FALSE" and Status.UNKNOWN == "UNKNOWN"
    assert Status("TRUE") is Status.TRUE
    assert {s.value for s in Status} == {"TRUE", "FALSE", "UNKNOWN"}
    assert Status.TRUE != "FALSE" and Status.TRUE != Status.FALSE
    assert Status.TRUE in {"TRUE"} and hash(Status.TRUE) == hash("TRUE")


def test_status_json_serialises_as_plain_string():
    import json

    assert json.dumps({"s": Status.UNKNOWN}) == '{"s": "UNKNOWN"}'


def test_engine_returns_status_members(engine):
    assert isinstance(engine.evaluate("g"), Status)
    assert isinstance(engine.certify("g").status, Status)


# ---------------------------------------------------------------- exceptions & exports


def test_exception_hierarchy():
    assert issubclass(AskCertError, Exception)
    assert issubclass(RuleError, AskCertError) and issubclass(RuleError, ValueError)
    assert issubclass(EvidenceError, AskCertError) and issubclass(EvidenceError, ValueError)
    assert issubclass(ObservationConflictError, EvidenceError)
    assert issubclass(ResourceLimitExceeded, AskCertError)
    assert not issubclass(RuleError, EvidenceError) and not issubclass(EvidenceError, RuleError)


def test_public_exports_and_version():
    for name in (
        "AskCert",
        "RuleSet",
        "Status",
        "CertificationResult",
        "Witnesses",
        "compile_rules",
        "AskCertError",
        "RuleError",
        "EvidenceError",
        "ObservationConflictError",
        "ResourceLimitExceeded",
        "Reasoner",
        "Rule",
        "Decision",
        "Question",
        "__version__",
    ):
        assert hasattr(askcert, name), name
    assert askcert.__version__ == "0.1.0"


# ---------------------------------------------------------------- immutability / no aliasing


def test_results_are_frozen(engine):
    res = engine.certify("g", {"a": T})
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.status = Status.TRUE  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.witnesses.true_world = {}  # type: ignore[misc]


def test_result_mappings_are_read_only(engine):
    res = engine.certify("g", {"a": T, "b": T})
    with pytest.raises(TypeError):
        res.evidence["a"] = F  # type: ignore[index]
    unk = engine.certify("g", {"a": T})
    with pytest.raises(TypeError):
        unk.witnesses.true_world["b"] = F  # type: ignore[index]


def test_ruleset_rules_mapping_is_read_only_and_ordered():
    rs = RuleSet.from_dict({"z": "a", "y": "b", "x": {"all": ["z", "y"]}})
    with pytest.raises(TypeError):
        rs.rules["new"] = Ref("a")  # type: ignore[index]
    assert list(rs.rules) == ["z", "y", "x"]


def test_engine_does_not_mutate_or_alias_the_evidence(engine):
    ev = {"a": T, "b": None, "c": F}
    snapshot = copy.deepcopy(ev)
    res = engine.certify("g", ev)
    assert ev == snapshot
    ev["a"] = F
    ev["zzz"] = T
    assert res.evidence == {"a": T, "c": F}


def test_rule_set_does_not_alias_the_input_spec():
    spec = {"g": {"all": ["a", "b"]}}
    rs = RuleSet.from_dict(spec)
    spec["g"]["all"].append("c")
    spec["extra"] = "a"
    assert rs.atoms == ("a", "b") and list(rs.rules) == ["g"]


# ---------------------------------------------------------------- AST (askcert.rules)


def test_ast_nodes_are_frozen_hashable_and_structurally_equal():
    e1 = All((Ref("a"), Not(Ref("b"))), (Ref("c"),))
    e2 = All((Ref("a"), Not(Ref("b"))), (Ref("c"),))
    assert e1 == e2 and hash(e1) == hash(e2) and e1 != All((Ref("a"),))
    assert All((Ref("a"),)) == All((Ref("a"),), ())  # unless defaults to ()
    assert Any((Ref("a"),)).unless == ()
    assert Const(True) == Const(True) != Const(False)
    assert len({Ref("a"), Ref("a"), Ref("b")}) == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        e1.args = ()  # type: ignore[misc]


def test_parsed_rules_are_ast_nodes():
    rs = RuleSet.from_dict(
        {
            "g": {"all": ["a", "!b"], "unless": ["c"]},
            "h": {"xor": ["a", True]},
            "i": {"implies": ["a", "b"]},
            "j": {"any": []},
            "k": False,
            "l": "!a",
            "m": "a",
        }
    )
    assert rs.rules["g"] == All((Ref("a"), Not(Ref("b"))), (Ref("c"),))
    assert rs.rules["h"] == Xor((Ref("a"), Const(True)))
    assert rs.rules["i"] == Implies(Ref("a"), Ref("b"))
    assert rs.rules["j"] == Any(())
    assert rs.rules["k"] == Const(False)
    assert rs.rules["l"] == Not(Ref("a"))
    assert rs.rules["m"] == Ref("a")


def test_flat_list_form_parses_to_any_all_with_unless():
    rs = RuleSet.from_dict(
        {
            "rules": [
                {"name": "e", "op": "ANY", "conditions": ["r", "v"], "exceptions": ["x"]},
                {"p": "f", "op": "ALL", "conditions": ["r"]},
                {"name": "d"},
            ]
        }
    )
    assert rs.rules["e"] == Any((Ref("r"), Ref("v")), (Ref("x"),))
    assert rs.rules["f"] == All((Ref("r"),), ())
    assert rs.rules["d"] == Any((), ())


def test_ruleset_constructor_accepts_ast_dict_str_bool():
    rs = RuleSet(
        {
            "a1": Ref("x"),
            "b1": {"all": ["x", "y"]},
            "c1": "!x",
            "d1": True,
            "e1": All((Ref("x"), Not(Ref("y")))),
        },
        atoms=["x", "y", "z"],
    )
    assert rs.rules["a1"] == Ref("x") and rs.rules["c1"] == Not(Ref("x")) and rs.rules["d1"] == Const(True)
    assert rs.declared_atoms == ("x", "y", "z") and rs.atoms == ("x", "y", "z")
    assert rs.rules["e1"] == All((Ref("x"), Not(Ref("y"))))


def test_ruleset_equality_is_on_rules_and_declared_atoms():
    spec = {"g": {"all": ["a", "b"]}}
    assert RuleSet.from_dict(spec) == RuleSet.from_dict({"schema_version": "1", "rules": spec})
    assert RuleSet.from_dict(spec) != RuleSet.from_dict({"atoms": ["a", "b"], "rules": spec})
    assert RuleSet.from_dict(spec) != RuleSet.from_dict({"g": {"all": ["b", "a"]}})
    assert RuleSet.from_dict(spec) != RuleSet.from_dict({"h": {"all": ["a", "b"]}})
    assert "g" in repr(RuleSet.from_dict(spec))


def test_ruleset_cone_is_sorted_and_transitive():
    rs = RuleSet.from_dict({"top": {"all": ["mid", "z"]}, "mid": {"any": ["m", "!a", "leaf"]}, "leaf": "q"})
    assert rs.cone("top") == ("a", "m", "q", "z")
    assert rs.cone("mid") == ("a", "m", "q")
    assert rs.cone("leaf") == ("q",)
    assert rs.cone("z") == ("z",)  # atom goal


def test_certification_result_type_exports():
    res = AskCert(RULES).certify("g", {"a": T})
    assert isinstance(res, CertificationResult) and isinstance(res.witnesses, Witnesses)
    assert dataclasses.is_dataclass(res) and dataclasses.is_dataclass(res.witnesses)


def test_ruleset_is_not_equal_to_other_types():
    rs = RuleSet.from_dict({"g": "a"})
    assert rs != 5 and rs != None and rs != {"g": "a"}  # noqa: E711
    assert rs != "g" and rs != [rs]


@pytest.mark.parametrize(
    "node",
    [
        Const(True),
        Ref("a"),
        Not(Ref("a")),
        All((Ref("a"), Ref("b")), (Ref("c"),)),
        Any((Ref("a"),), (Ref("c"),)),
        Xor((Ref("a"), Ref("b"))),
        Implies(Ref("a"), Const(False)),
    ],
    ids=lambda n: type(n).__name__,
)
def test_every_ast_node_type_is_frozen_hashable_and_comparable(node):
    first_field = dataclasses.fields(node)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(node, first_field, None)
    clone = copy.deepcopy(node)
    assert clone == node and hash(clone) == hash(node)
    assert {node, clone} == {node}
    assert node != Const(False)
