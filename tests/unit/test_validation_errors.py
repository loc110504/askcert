"""Every validation error in the contract (rules, goals, engine arguments, evidence)."""

from __future__ import annotations

import re
from collections.abc import Mapping

import pytest

from askcert import AskCert, AskCertError, EvidenceError, RuleError, RuleSet
from askcert.serialization import load_json


def rule_error(spec, match=None):
    """``RuleSet.from_dict`` and ``AskCert`` must both reject ``spec`` with a RuleError."""
    with pytest.raises(RuleError, match=match):
        RuleSet.from_dict(spec)
    with pytest.raises(RuleError, match=match):
        AskCert(spec)


# ---------------------------------------------------------------- cycles


def test_two_rule_cycle_reports_path():
    with pytest.raises(RuleError) as exc:
        RuleSet.from_dict({"a": "b", "b": "a"})
    msg = str(exc.value)
    m = re.search(r"cycle: (\w+(?: -> \w+)+)", msg)
    assert m, msg
    path = m.group(1).split(" -> ")
    assert path[0] == path[-1] and set(path) == {"a", "b"}


def test_self_cycle_reports_path():
    with pytest.raises(RuleError, match=r"cycle: a -> a"):
        RuleSet.from_dict({"a": {"all": ["x", "a"]}})


def test_long_cycle_inside_operators_and_unless():
    spec = {
        "a": {"any": ["x", "b"]},
        "b": {"all": ["x"], "unless": ["c"]},
        "c": {"implies": ["y", {"not": "a"}]},
        "ok": "x",
    }
    with pytest.raises(RuleError) as exc:
        RuleSet.from_dict(spec)
    m = re.search(r"cycle: (\w+(?: -> \w+)+)", str(exc.value))
    assert m, str(exc.value)
    path = m.group(1).split(" -> ")
    assert path[0] == path[-1] and set(path) == {"a", "b", "c"}


def test_cycle_via_bang_reference():
    rule_error({"a": "!b", "b": "a"}, match="cycle")


def test_cycle_detected_by_engine_constructor_and_load():
    with pytest.raises(RuleError, match="cycle"):
        AskCert({"p": {"all": ["q"]}, "q": {"not": "p"}})
    with pytest.raises(RuleError, match="cycle"):
        RuleSet.from_json('{"p": "q", "q": "p"}')


# ---------------------------------------------------------------- undefined references / names


def test_undefined_reference_with_declared_atoms():
    spec = {"atoms": ["x"], "rules": {"g": {"all": ["x", "y"]}}}
    rule_error(spec, match="undefined reference")
    with pytest.raises(RuleError) as exc:
        RuleSet.from_dict(spec)
    assert "y" in str(exc.value)


def test_undefined_reference_inside_unless_and_bang():
    rule_error(
        {"atoms": ["x"], "rules": {"g": {"all": ["x"], "unless": ["!nope"]}}}, match="undefined reference"
    )


def test_declared_atoms_may_be_unused():
    rs = RuleSet.from_dict({"atoms": ["x", "unused"], "rules": {"g": "x"}})
    assert rs.atoms == ("unused", "x")


def test_name_both_declared_atom_and_rule():
    rule_error({"atoms": ["g"], "rules": {"g": True}})
    rule_error({"atoms": ["x", "g"], "rules": {"g": "x"}})


@pytest.mark.parametrize("reserved", ["rules", "atoms", "schema_version"])
def test_reserved_names_cannot_be_rule_names(reserved):
    rule_error({"rules": {reserved: "x"}})
    rule_error({"rules": [{"name": reserved, "conditions": ["x"]}]})
    with pytest.raises(RuleError):
        RuleSet({reserved: "x"})


@pytest.mark.parametrize("reserved", ["rules", "atoms", "schema_version"])
def test_reserved_names_cannot_be_atom_names(reserved):
    rule_error({"rules": {"g": reserved}})  # as a reference
    rule_error({"rules": {"g": {"not": reserved}}})
    rule_error({"atoms": ["x", reserved], "rules": {"g": "x"}})  # as a declared atom
    with pytest.raises(RuleError):
        RuleSet({"g": "x"}, atoms=[reserved])


@pytest.mark.parametrize(
    "name", ["", "1abc", "a-b", "a b", "a.b", "é", "a!", "!!x", "!", "x y", "a/b", "9", "-x", " x", "x "]
)
def test_bad_names_rejected_as_references(name):
    rule_error({"g": {"all": [name]}})


@pytest.mark.parametrize("name", ["", "1abc", "a-b", "a b", "é", "!x", "x!", "a.b"])
def test_bad_names_rejected_as_rule_names(name):
    rule_error({name: "x"})
    rule_error({"rules": {name: "x"}})


def test_bad_declared_atom_name():
    rule_error({"atoms": ["ok", "not ok"], "rules": {"g": "ok"}})
    rule_error({"atoms": ["ok", "!x"], "rules": {"g": "ok"}})


def test_single_bang_allowed_double_bang_not():
    assert RuleSet.from_dict({"g": "!x"}).atoms == ("x",)
    rule_error({"g": "!!x"})


# ---------------------------------------------------------------- expression grammar


def test_unknown_operator():
    rule_error({"g": {"nand": ["a", "b"]}})
    rule_error({"g": {"ALL": ["a"]}})  # operators are lower-case


def test_multiple_operators_in_one_node():
    rule_error({"g": {"all": ["a"], "any": ["b"]}})
    rule_error({"g": {"not": "a", "xor": ["b"]}})


def test_empty_node_has_no_operator():
    rule_error({"g": {}})


def test_unknown_key_next_to_operator():
    rule_error({"g": {"all": ["a"], "else": ["b"]}})


@pytest.mark.parametrize(
    "expr",
    [
        {"implies": ["a"]},
        {"implies": ["a", "b", "c"]},
        {"implies": []},
        {"implies": "a"},
        {"implies": {"a": "b"}},
    ],
)
def test_implies_needs_exactly_two_operands(expr):
    rule_error({"g": expr})


@pytest.mark.parametrize("op", ["all", "any", "xor"])
def test_nary_operators_need_a_list(op):
    rule_error({"g": {op: "a"}})
    rule_error({"g": {op: True}})
    rule_error({"g": {op: {"not": "a"}}})
    rule_error({"g": {op: None}})


def test_not_takes_exactly_one_expression_not_a_list():
    rule_error({"g": {"not": ["a", "b"]}})
    rule_error({"g": {"not": []}})


@pytest.mark.parametrize(
    "expr",
    [
        {"xor": ["a"], "unless": ["b"]},
        {"not": "a", "unless": ["b"]},
        {"implies": ["a", "b"], "unless": ["c"]},
    ],
)
def test_unless_only_with_all_or_any(expr):
    rule_error({"g": expr})


def test_unless_must_be_a_list():
    rule_error({"g": {"all": ["a"], "unless": "b"}})
    rule_error({"g": {"any": ["a"], "unless": {"not": "b"}}})


def test_unless_without_core_operator():
    rule_error({"g": {"unless": ["b"]}})


@pytest.mark.parametrize("bad", [1, 0, 2, 1.0, 0.5, None, [], ["a"]])
def test_non_bool_scalars_and_containers_are_not_expressions(bad):
    rule_error({"g": bad})
    rule_error({"g": {"all": [bad]}})


def test_int_instead_of_bool_rejected_everywhere():
    rule_error({"g": 1})
    rule_error({"g": {"all": [1, "a"]}})
    rule_error({"g": {"not": 0}})
    rule_error({"g": {"implies": [1, "a"]}})
    rule_error({"g": {"all": ["a"], "unless": [1]}})


def test_flat_list_errors():
    rule_error({"rules": [{"name": "g", "op": "XOR", "conditions": ["a"]}]})  # op not ALL/ANY
    rule_error({"rules": [{"name": "g", "conditions": "a"}]})  # conditions must be a list
    rule_error({"rules": [{"name": "g", "exceptions": "a"}]})
    rule_error({"rules": [{"name": "g", "conditions": [1]}]})  # list of strings
    rule_error({"rules": [{"name": "g"}, {"name": "g"}]}, match="g")  # duplicate names
    rule_error({"rules": [{"name": "g"}, {"p": "g"}]})  # duplicate via alias


def test_depth_beyond_256_is_a_rule_error():
    expr: object = "x"
    for _ in range(300):
        expr = {"not": expr}
    rule_error({"g": expr})


def test_shallow_nesting_is_fine():
    expr: object = "x"
    for _ in range(100):
        expr = {"not": expr}
    assert AskCert({"g": expr}).evaluate("g", {"x": True}) == "TRUE"  # even number of negations


def test_depth_limit_counts_all_operators():
    expr: object = "x"
    for i in range(300):
        expr = {"all": [expr]} if i % 2 else {"any": [expr, "y"], "unless": []}
    rule_error({"g": expr})


# ---------------------------------------------------------------- document level


@pytest.mark.parametrize("version", ["2", "0", "1.0", "v1", "", 1, 2, 1.0, True, None, ["1"]])
def test_schema_version_must_be_the_string_1(version):
    rule_error({"schema_version": version, "rules": {"g": "x"}})


def test_schema_version_1_accepted():
    assert RuleSet.from_dict({"schema_version": "1", "rules": {"g": "x"}}).atoms == ("x",)


def test_unknown_top_level_key_in_document_form():
    rule_error({"rules": {"g": "x"}, "extra": 1})
    rule_error({"rules": {"g": "x"}, "Atoms": ["x"]})
    rule_error({"schema_version": "1", "rules": {"g": "x"}, "description": "nope"})


def test_rules_must_be_mapping_or_list():
    rule_error({"rules": "g"})
    rule_error({"rules": 3})
    rule_error({"rules": None})


def test_atoms_must_be_a_list_of_strings():
    rule_error({"atoms": "x", "rules": {"g": "x"}})
    rule_error({"atoms": [1], "rules": {"g": "x"}})
    rule_error({"atoms": ["x", None], "rules": {"g": "x"}})


def test_non_mapping_spec_is_rejected():
    for bad in (None, 3, "g", True):
        with pytest.raises((RuleError, TypeError)):
            RuleSet.from_dict(bad)


def test_error_hierarchy_for_rule_errors():
    with pytest.raises(AskCertError):
        RuleSet.from_dict({"g": 1})
    with pytest.raises(ValueError):
        RuleSet.from_dict({"g": 1})


# ---------------------------------------------------------------- JSON duplicate keys


def test_duplicate_keys_in_rules_json():
    with pytest.raises(RuleError):
        RuleSet.from_json('{"g": "a", "g": "b"}')


def test_duplicate_keys_nested_in_document_and_expression():
    with pytest.raises(RuleError):
        RuleSet.from_json('{"rules": {"g": "a", "g": "b"}}')
    with pytest.raises(RuleError):
        RuleSet.from_json('{"rules": {"g": {"all": ["a"], "all": ["b"]}}}')
    with pytest.raises(RuleError):
        RuleSet.from_json('{"rules": {"g": "a"}, "rules": {"h": "b"}}')


def test_malformed_rules_json_is_a_value_error():
    with pytest.raises(ValueError):
        RuleSet.from_json("{not json")


def test_load_json_helper_duplicate_keys_by_kind():
    with pytest.raises(RuleError):
        load_json('{"a": 1, "a": 2}', "rules")
    with pytest.raises(EvidenceError):
        load_json('{"a": true, "a": false}', "evidence")
    assert load_json('{"a": true}', "evidence") == {"a": True}
    assert load_json('{"g": "a"}', "rules") == {"g": "a"}


def test_rule_set_load_from_file_rejects_duplicates(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text('{"g": "a", "g": "b"}', encoding="utf-8")
    with pytest.raises(RuleError):
        RuleSet.load(path)


# ---------------------------------------------------------------- goals


def test_unknown_goal_everywhere():
    engine = AskCert({"g": {"all": ["a", "b"]}})
    with pytest.raises(RuleError, match="unknown goal"):
        engine.rules.cone("nope")
    for call in (
        lambda: engine.evaluate("nope"),
        lambda: engine.certify("nope"),
        lambda: engine.find_certificate("nope"),
        lambda: engine.find_relevant_unknowns("nope"),
        lambda: engine.find_witnesses("nope"),
        lambda: engine.certify_many("nope", [{}]),
        lambda: engine.compile("nope"),
    ):
        with pytest.raises(RuleError, match="unknown goal"):
            call()


def test_goal_must_be_exact_name():
    engine = AskCert({"g": "a"})
    with pytest.raises(RuleError):
        engine.evaluate("G")
    with pytest.raises(RuleError):
        engine.evaluate("!a")
    with pytest.raises(RuleError):
        engine.evaluate("")


# ---------------------------------------------------------------- engine arguments


@pytest.mark.parametrize(
    "order",
    [["a"], ["a", "b", "b"], ["a", "b", "c", "d"], ["a", "c"], [], ["b", "c"], ["a", "b", "x"]],
)
def test_bad_variable_order_is_value_error(order):
    with pytest.raises(ValueError):
        AskCert({"g": {"all": ["a", "b", "c"]}}, variable_order=order)


def test_variable_order_must_be_exact_permutation_of_rule_set_atoms():
    spec = {"atoms": ["a", "b", "unused"], "rules": {"g": {"all": ["a", "b"]}}}
    with pytest.raises(ValueError):  # declared-but-unused atoms belong to rules.atoms
        AskCert(spec, variable_order=["a", "b"])
    assert AskCert(spec, variable_order=["unused", "b", "a"]).evaluate("g", {"a": True, "b": True}) == "TRUE"


@pytest.mark.parametrize("max_nodes", [1, 0, -1, -100, "100", 2.5, [2]])
def test_bad_max_nodes(max_nodes):
    with pytest.raises((ValueError, TypeError)):
        AskCert({"g": "a"}, max_nodes=max_nodes)


@pytest.mark.parametrize("timeout", [0, 0.0, -1, -0.5, "1", [1]])
def test_bad_timeout(timeout):
    with pytest.raises((ValueError, TypeError)):
        AskCert({"g": "a"}, timeout=timeout)


def test_good_limits_accepted():
    engine = AskCert({"g": "a"}, max_nodes=2_000, timeout=30)
    assert engine.evaluate("g", {"a": False}) == "FALSE"
    assert AskCert({"g": "a"}, timeout=None).evaluate("g", {"a": True}) == "TRUE"


def test_limits_are_keyword_only():
    with pytest.raises(TypeError):
        AskCert({"g": "a"}, 1000)  # type: ignore[misc]


# ---------------------------------------------------------------- evidence errors

ENGINE_CALLS = {
    "evaluate": lambda e, ev: e.evaluate("g", ev),
    "certify": lambda e, ev: e.certify("g", ev),
    "find_certificate": lambda e, ev: e.find_certificate("g", ev),
    "find_relevant_unknowns": lambda e, ev: e.find_relevant_unknowns("g", ev),
    "find_witnesses": lambda e, ev: e.find_witnesses("g", ev),
    "certify_many": lambda e, ev: e.certify_many("g", [ev]),
}


@pytest.fixture
def engine():
    return AskCert({"g": {"all": ["a", "b"]}, "h": {"any": ["g", "c"]}})


@pytest.mark.parametrize("call", ENGINE_CALLS)
def test_unknown_atom_in_evidence(engine, call):
    with pytest.raises(EvidenceError, match="unknown atom"):
        ENGINE_CALLS[call](engine, {"a": True, "zzz": True})


@pytest.mark.parametrize("call", ENGINE_CALLS)
def test_derived_rule_in_evidence(engine, call):
    with pytest.raises(EvidenceError, match="cannot assign derived rule"):
        ENGINE_CALLS[call](engine, {"h": True})


def test_unknown_atom_even_if_value_is_none(engine):
    with pytest.raises(EvidenceError, match="unknown atom"):
        engine.evaluate("g", {"zzz": None})


def test_derived_rule_even_if_value_is_none(engine):
    with pytest.raises(EvidenceError, match="cannot assign derived rule"):
        engine.evaluate("g", {"h": None})


def test_unknown_atom_outside_cone_but_in_rule_set_is_fine(engine):
    assert engine.evaluate("g", {"c": True, "a": False}) == "FALSE"


@pytest.mark.parametrize("bad", [1, 0, "true", "True", "", 1.0, 0.0, [], {}, (True,), b"1"])
@pytest.mark.parametrize("call", ENGINE_CALLS)
def test_non_bool_evidence_values(engine, call, bad):
    """Values must be exactly ``bool`` or ``None``; ``1``/``0`` are rejected."""
    with pytest.raises(EvidenceError):
        ENGINE_CALLS[call](engine, {"a": bad})


@pytest.mark.parametrize("bad", [[("a", True)], "a", 5, ["a"], True])
def test_evidence_must_be_a_mapping(engine, bad):
    with pytest.raises(EvidenceError):
        engine.evaluate("g", bad)


def test_evidence_none_and_empty_are_equivalent(engine):
    assert engine.certify("g", None) == engine.certify("g", {}) == engine.certify("g")


def test_any_mapping_is_accepted_as_evidence(engine):
    class Ev(Mapping):
        def __getitem__(self, k):
            return {"a": True, "b": False}[k]

        def __iter__(self):
            return iter(["a", "b"])

        def __len__(self):
            return 2

    assert engine.evaluate("g", Ev()) == "FALSE"


def test_bad_evidence_in_certify_many_is_rejected_for_any_element(engine):
    with pytest.raises(EvidenceError):
        engine.certify_many("g", [{"a": True}, {"a": 1}])
    with pytest.raises(EvidenceError):
        engine.certify_many("g", [{}, {"nope": True}])


def test_evidence_error_hierarchy():
    assert issubclass(EvidenceError, AskCertError) and issubclass(EvidenceError, ValueError)


def test_depth_limit_applies_to_ast_input_too():
    from askcert.rules import Not, Ref

    expr = Ref("x")
    for _ in range(300):
        expr = Not(expr)
    with pytest.raises(RuleError):
        RuleSet({"g": expr})
    shallow = Ref("x")
    for _ in range(50):
        shallow = Not(shallow)
    assert RuleSet({"g": shallow}).atoms == ("x",)


def _nest(op, n):
    expr: object = "x"
    for _ in range(n):
        if op == "not":
            expr = {"not": expr}
        elif op == "unless":
            expr = {"all": ["y"], "unless": [expr]}
        else:
            expr = {op: [expr]}
    return expr


@pytest.mark.parametrize("op", ["not", "all", "any", "xor", "unless"])
def test_nesting_depth_boundary_is_256_operator_levels(op):
    """Depth 256 (operator nodes around a leaf) is accepted, 257 is a RuleError."""
    assert RuleSet.from_dict({"g": _nest(op, 256)}).cone("g")
    rule_error({"g": _nest(op, 257)})


def test_nesting_depth_boundary_for_ast_input():
    from askcert.rules import Not, Ref

    def deep(n):
        expr = Ref("x")
        for _ in range(n):
            expr = Not(expr)
        return expr

    assert RuleSet({"g": deep(256)}).cone("g") == ("x",)
    with pytest.raises(RuleError):
        RuleSet({"g": deep(257)})


def test_nesting_depth_is_per_rule_not_cumulative():
    """Chains of rule references are not limited by the 256 expression-depth cap."""
    rules = {f"r{i}": {"not": f"r{i - 1}"} for i in range(1, 400)}
    rules["r0"] = "x"
    assert RuleSet.from_dict(rules).cone("r399") == ("x",)
