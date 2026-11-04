"""Computational failure is never UNKNOWN: node limit / timeout / recursion raise
``ResourceLimitExceeded`` (contract Sec. 1, 2, 4, 5)."""

from __future__ import annotations

import pytest

from askcert import AskCert, AskCertError, ResourceLimitExceeded, RuleSet, Status

PAIRS = 18  # OR of x_i AND y_i with all x before all y: exponential ROBDD (2^PAIRS nodes)


def hard_rules(pairs=PAIRS):
    terms = [{"all": [f"x{i:02d}", f"y{i:02d}"]} for i in range(pairs)]
    return {"hard": {"any": terms}}


def bad_order(pairs=PAIRS):
    return [f"x{i:02d}" for i in range(pairs)] + [f"y{i:02d}" for i in range(pairs)]


def test_tiny_max_nodes_raises_never_unknown():
    with pytest.raises(ResourceLimitExceeded) as exc:
        engine = AskCert({"g": {"all": ["a", "b", "c"]}}, max_nodes=2)
        result = engine.certify("g", {"a": True})
        pytest.fail(f"expected ResourceLimitExceeded, got {result.status}")
    assert exc.value.limit == "max_nodes"
    assert exc.value.value == 2  # the configured limit


@pytest.mark.parametrize(
    "call", ["evaluate", "certify", "find_certificate", "find_relevant_unknowns", "find_witnesses"]
)
def test_node_limit_raises_in_every_entry_point(call):
    engine = AskCert(hard_rules(12), max_nodes=100, variable_order=bad_order(12))
    with pytest.raises(ResourceLimitExceeded) as exc:
        getattr(engine, call)("hard", {})
    assert exc.value.limit == "max_nodes"


def test_node_limit_raises_for_compile_and_certify_many_and_compile_rules():
    from askcert import compile_rules

    with pytest.raises(ResourceLimitExceeded):
        AskCert(hard_rules(12), max_nodes=100, variable_order=bad_order(12)).compile()
    with pytest.raises(ResourceLimitExceeded):
        AskCert(hard_rules(12), max_nodes=100, variable_order=bad_order(12)).certify_many("hard", [{}])
    with pytest.raises(ResourceLimitExceeded):
        compile_rules(hard_rules(12), max_nodes=100, variable_order=bad_order(12))


def test_resource_limit_is_an_askcert_error_not_a_decision():
    with pytest.raises(AskCertError):
        AskCert(hard_rules(12), max_nodes=100, variable_order=bad_order(12)).evaluate("hard")
    assert not isinstance(Status.UNKNOWN, ResourceLimitExceeded)


def test_engine_never_answers_wrongly_after_node_limit_error():
    """After a failed query the engine gives the right answer or raises again, never a wrong one."""
    rules = {**hard_rules(12), "small": {"all": ["p", "q"]}}
    order = sorted(RuleSet.from_dict(rules).atoms, key=lambda a: (a[0] == "y", a))
    engine = AskCert(rules, max_nodes=400, variable_order=order)
    assert engine.evaluate("small", {"p": True, "q": True}) == "TRUE"
    with pytest.raises(ResourceLimitExceeded):
        engine.evaluate("hard")
    for _ in range(2):
        try:
            assert engine.evaluate("small", {"p": False}) == "FALSE"
            assert engine.certify("small", {"p": True}).relevant_unknowns == ("q",)
        except ResourceLimitExceeded as exc:
            assert exc.limit == "max_nodes"


def test_generous_max_nodes_decides_the_same_formula():
    engine = AskCert(hard_rules(8), max_nodes=1_000_000, variable_order=bad_order(8))
    assert engine.evaluate("hard", {"x00": True, "y00": True}) == "TRUE"
    assert engine.evaluate("hard", {}) == "UNKNOWN"


def test_tiny_timeout_on_hard_formula_raises_timeout():
    engine = AskCert(hard_rules(), max_nodes=50_000_000, timeout=0.005, variable_order=bad_order())
    with pytest.raises(ResourceLimitExceeded) as exc:
        engine.certify("hard", {})
    assert exc.value.limit == "timeout"
    assert exc.value.value == 0.005  # the configured limit


@pytest.mark.parametrize("call", ["evaluate", "find_relevant_unknowns", "find_certificate"])
def test_timeout_is_raised_by_each_entry_point(call):
    engine = AskCert(hard_rules(), max_nodes=50_000_000, timeout=0.005, variable_order=bad_order())
    with pytest.raises(ResourceLimitExceeded) as exc:
        getattr(engine, call)("hard", {})
    assert exc.value.limit == "timeout"


def test_generous_timeout_does_not_trigger():
    engine = AskCert(hard_rules(6), timeout=60, variable_order=bad_order(6))
    assert engine.evaluate("hard") == "UNKNOWN"


def chain(n, reverse=False):
    names = [f"r{i}" for i in range(n)]
    rules = {names[0]: "x", **{names[i]: {"not": names[i - 1]} for i in range(1, n)}}
    if reverse:
        rules = dict(reversed(list(rules.items())))
    return rules, names[-1]


@pytest.mark.parametrize("reverse", [False, True])
def test_very_deep_rule_chain_is_correct_or_resource_limit_never_wrong(reverse):
    """5000 chained rule references: either the right answer or ResourceLimitExceeded(recursion).

    Never a raw RecursionError, never UNKNOWN, never a RuleError for a valid acyclic chain.
    """
    rules, goal = chain(5000, reverse)
    try:
        engine = AskCert(rules)
        status = engine.evaluate(goal, {"x": True})
    except ResourceLimitExceeded as exc:
        assert exc.limit == "recursion"
    else:
        assert status == Status.FALSE  # 4999 negations of x=True
        assert engine.evaluate(goal, {"x": False}) == Status.TRUE
        assert engine.find_relevant_unknowns(goal) == ("x",)


def test_deep_chain_cycle_is_still_a_rule_error_not_recursion_error():
    from askcert import RuleError

    rules, _ = chain(3000)
    rules["r0"] = "r2999"  # close the loop
    with pytest.raises((RuleError, ResourceLimitExceeded)):
        RuleSet.from_dict(rules)
        AskCert(rules).compile()


def test_recursion_limit_error_carries_limit_attribute():
    """If the implementation gives up on a deep chain it must say so via ``.limit``."""
    rules, goal = chain(20000)
    try:
        AskCert(rules).evaluate(goal, {"x": True})
    except ResourceLimitExceeded as exc:
        assert exc.limit == "recursion"
