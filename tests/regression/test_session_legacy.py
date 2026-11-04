"""Legacy session-API regression suite, ported to ``askcert.Reasoner`` / ``askcert.Rule``.

Ported from the research prototype's ``test_core.py``, ``test_formal_properties_extended.py`` and
``test_mutability_regressions.py``. Assertions are unchanged except for the two documented
intentional differences: invalid fact values raise ``EvidenceError`` (was ``TypeError``) and the
node limit raises ``ResourceLimitExceeded`` (was ``MemoryError``).
"""

import json
from itertools import product
from random import Random

import pytest

from askcert import (
    EvidenceError,
    ObservationConflictError,
    Reasoner,
    ResourceLimitExceeded,
    Rule,
    RuleError,
    Status,
)


def eligible(**kwargs):
    return Reasoner([Rule("eligible", ANY=["resident", "valid_visa"], UNLESS=["restricted"])], kwargs)


def test_missing_exception_unknown_then_known():
    e = eligible(resident=True, valid_visa=False)
    assert e.evaluate("eligible") is Status.UNKNOWN
    assert e.ask("eligible").fact == "restricted"
    d = e.certify("eligible")
    assert d.counterexamples[0]["restricted"] is False
    assert d.counterexamples[1]["restricted"] is True
    assert e.verify_small("eligible", d)
    e.observe("restricted", False)
    assert e.evaluate("eligible") is Status.TRUE
    assert e.certify("eligible").evidence == ("resident", "restricted")
    assert e.verify_small("eligible")


def test_falsity_without_over_questioning():
    e = eligible(resident=False, valid_visa=False)
    assert e.evaluate("eligible") is Status.FALSE
    assert e.ask("eligible") is None
    assert e.certify("eligible").evidence == ("resident", "valid_visa")


def test_short_circuit_unknown():
    e = Reasoner([Rule("p", ALL=["a", "b", "c"], UNLESS=["block"])], {"a": False})
    assert e.evaluate("p") is Status.FALSE
    assert e.ask("p") is None
    assert e.verify_small("p")


def test_tautology_is_true_even_if_atom_unknown():
    e = Reasoner([Rule("p", ANY=["x", "!x"])])
    assert e.evaluate("p") is Status.TRUE
    assert e.ask("p") is None
    assert e.certify("p").evidence == ()
    assert e.verify_small("p")


def test_contradiction_is_false_even_if_atom_unknown():
    e = Reasoner([Rule("p", ALL=["x", "!x"])])
    assert e.evaluate("p") is Status.FALSE
    assert e.ask("p") is None
    assert e.verify_small("p")


def test_mutually_shared_fact_simplification():
    e = Reasoner(
        [Rule("a", ALL=["x", "y"]), Rule("b", ALL=["x", "!y"]), Rule("p", ANY=["a", "b"])], {"x": True}
    )
    assert e.evaluate("p") is Status.TRUE
    assert e.certify("p").evidence == ("x",)
    assert e.verify_small("p")


def test_nested_exception_with_negated_ref():
    e = Reasoner(
        [Rule("sanction", ALL=["breach"], UNLESS=["waiver"]), Rule("action", ALL=["sanction", "!appeal"])],
        {"breach": True, "waiver": False, "appeal": False},
    )
    assert e.evaluate("action") is Status.TRUE
    assert e.verify_small("action")
    e.observe("appeal", True, replace=True)
    assert e.evaluate("action") is Status.FALSE


def test_empty_rules_have_mathematical_identities():
    e = Reasoner([Rule("yes", ALL=[]), Rule("no", ANY=[])])
    assert e.evaluate("yes") is Status.TRUE
    assert e.evaluate("no") is Status.FALSE
    assert e.verify_small("yes")
    assert e.verify_small("no")


def test_why_returns_explanations():
    e = eligible(resident=True, valid_visa=False)
    d = e.why("eligible")
    assert d["status"] == "UNKNOWN"
    assert d["relevant_unknown"] == ["restricted"]
    assert d["counterexamples"]["true_world"]["restricted"] is False
    e.observe("restricted", False)
    d = e.why("eligible")
    assert d["status"] == "TRUE"
    assert d["sufficient_evidence"] == {"resident": True, "restricted": False}


def test_asks_only_relevant_facts():
    e = Reasoner([Rule("p", ANY=["a", "b", "c"])], {"a": True})
    assert e.ask_all("p") == ()
    e.observe("a", None)
    assert [q.fact for q in e.ask_all("p")] == ["a", "b", "c"]


def test_queries_respect_positive_cost_and_prompt():
    e = Reasoner(
        [Rule("p", ANY=["a", "b"])],
        costs={"a": 100.0, "b": 1.0},
        questions={"b": "Is condition B satisfied?"},
    )
    assert e.ask("p").fact == "b"
    assert e.ask("p").text == "Is condition B satisfied?"
    assert e.ask("p").resolving_answers == (True,)


def test_validation():
    with pytest.raises(RuleError, match="Cycle"):
        Reasoner([Rule("p", ALL=["q"]), Rule("q", ANY=["p"])])
    with pytest.raises(RuleError, match="Duplicate"):
        Reasoner([Rule("p"), Rule("p")])
    with pytest.raises(RuleError, match="derived"):
        Reasoner([Rule("p", ALL=["x"])], {"p": True})
    with pytest.raises(RuleError, match="metadata"):
        Reasoner([Rule("p", ALL=["x"])], costs={"oops": 1})
    with pytest.raises(RuleError, match="finite"):
        Reasoner([Rule("p", ALL=["x"])], costs={"x": float("nan")})
    with pytest.raises(EvidenceError):
        Reasoner([Rule("p", ALL=["x"])], {"x": 1})
    with pytest.raises(RuleError):
        Rule("p", ALL=["x"], ANY=["y"])
    with pytest.raises(RuleError):
        Rule("p", ALL="x")
    with pytest.raises(RuleError):
        Reasoner([Rule("p", ALL=["x"])], {"unknown": True})


def test_legacy_rule_json_support():
    e = Reasoner.from_dict(
        {
            "rules": [{"p": "approved", "op": "ALL", "conditions": ["paid"], "exceptions": ["fraud"]}],
            "facts": {"paid": True},
        }
    )
    assert e.evaluate("approved") is Status.UNKNOWN
    saved = json.loads(json.dumps(e.to_dict()))
    assert Reasoner.from_dict(saved).evaluate("approved") is Status.UNKNOWN


def test_truth_table_exhaustive_simple_rules():
    rules = [Rule("q", ALL=["a", "!b"], UNLESS=["c"]), Rule("p", ANY=["q", "d"], UNLESS=["a", "!c"])]
    for states in product((True, False, None), repeat=4):
        e = Reasoner(rules, dict(zip(("a", "b", "c", "d"), states, strict=True)))
        assert e.verify_small("p")
        if e.evaluate("p") is Status.UNKNOWN:
            assert e.ask("p") is not None
        else:
            assert e.ask("p") is None


def test_random_acyclic_programs_against_independent_enumeration():
    rng = Random(20261027)
    for _ in range(300):
        atoms = ["a", "b", "c", "d", "e"]
        rules = []
        for i in range(rng.randrange(1, 5)):
            available = atoms + [r.name for r in rules]
            cond = [rng.choice(available) for _ in range(rng.randrange(0, 5))]
            exceptions = [rng.choice(available) for _ in range(rng.randrange(0, 3))]
            cond = [("!" if rng.random() < 0.35 else "") + c for c in cond]
            exceptions = [("!" if rng.random() < 0.35 else "") + c for c in exceptions]
            rules.append(
                Rule("r" + str(i), op=rng.choice(["ANY", "ALL"]), conditions=cond, exceptions=exceptions)
            )
        used = {s.removeprefix("!") for r in rules for s in r.conditions + r.exceptions}
        facts = {k: rng.choice([True, False, None]) for k in atoms if k in used}
        engine = Reasoner(rules, facts)
        goal = rules[-1].name
        assert engine.verify_small(goal), (rules, facts)
        for q in engine.ask_all(goal):
            assert facts.get(q.fact) is None
            assert q.fact in engine.atoms


def test_witness_cannot_contradict_known():
    e = Reasoner([Rule("p", ANY=["a", "b"], UNLESS=["c"])], {"a": False, "c": False})
    d = e.certify("p")
    assert d.status == Status.UNKNOWN
    assert all(world["a"] is False and world["c"] is False for world in d.counterexamples)
    assert e.verify_small("p")


def test_max_nodes_enforced():
    engine = Reasoner([Rule("p", ANY=["a", "b", "c"])], max_nodes=3)
    with pytest.raises(ResourceLimitExceeded):
        engine.evaluate("p")


@pytest.mark.parametrize("seed", range(150))
def test_random_small_rule_programs_independent_certificate(seed):
    rnd = Random(seed)
    atoms = [f"x{i}" for i in range(rnd.randint(2, 7))]
    rules = []
    for i in range(rnd.randint(1, 5)):
        choices = atoms + [rule.name for rule in rules]

        def literal(choices=choices):
            x = rnd.choice(choices)
            return ("!" if rnd.random() < 0.25 else "") + x

        rules.append(
            Rule(
                f"p{i}",
                op=rnd.choice(("ALL", "ANY")),
                conditions=[literal() for _ in range(rnd.randint(0, 4))],
                exceptions=[literal() for _ in range(rnd.randint(0, 2))],
            )
        )
    engine = Reasoner(rules)
    target = rules[-1].name
    for _ in range(15):
        for fact in engine.atoms:
            engine.set_fact(fact, rnd.choice((True, False, None)))
        decision = engine.certify(target)
        assert engine.verify_small(target, decision)
        questions = engine.ask_all(target)
        if decision.status is Status.UNKNOWN:
            assert questions
            assert {q.fact for q in questions} == set(decision.relevant_unknown)
        else:
            assert not questions
            assert engine.ask(target) is None


@pytest.mark.parametrize(
    "spec,facts,expected,evidence",
    [
        (Rule("g", ANY=["x", "!x"]), {}, Status.TRUE, ()),
        (Rule("g", ALL=["x", "!x"]), {}, Status.FALSE, ()),
        (Rule("g", ALL=["x", "y"]), {"x": False}, Status.FALSE, ("x",)),
        (Rule("g", ANY=["x", "y"]), {"x": True}, Status.TRUE, ("x",)),
        (Rule("g", ALL=[]), {}, Status.TRUE, ()),
        (Rule("g", ANY=[]), {}, Status.FALSE, ()),
        (Rule("g", ALL=["x"], UNLESS=["z"]), {"x": True, "z": False}, Status.TRUE, ("x", "z")),
        (Rule("g", ALL=["x"], UNLESS=["!z"]), {"x": True, "z": True}, Status.TRUE, ("x", "z")),
    ],
)
def test_golden_boolean_certificate(spec, facts, expected, evidence):
    r = Reasoner([spec], facts=facts)
    assert r.evaluate("g") is expected
    assert r.certify("g").evidence == evidence
    assert r.verify_small("g")


@pytest.mark.parametrize(
    "facts,expected_questions",
    [
        ({"x": None, "y": None}, {"x", "y"}),
        ({"x": True, "y": None}, set()),
        ({"x": False, "y": None}, {"y"}),
        ({"x": None, "y": True}, set()),
        ({"x": None, "y": False}, {"x"}),
    ],
)
def test_query_support_example(facts, expected_questions):
    r = Reasoner([Rule("goal", ANY=["x", "y"])], facts)
    assert {q.fact for q in r.ask_all("goal")} == expected_questions
    assert r.verify_small("goal")


def test_rule_map_cannot_be_mutated_after_compilation():
    engine = Reasoner([Rule("eligible", ALL=["x"])], {"x": True})
    assert engine.evaluate("eligible") == "TRUE"
    with pytest.raises((TypeError, AttributeError)):
        engine.rules["eligible"] = Rule("eligible", ALL=["!x"])
    assert engine.evaluate("eligible") == "TRUE"


def test_public_fact_map_rejects_invalid_write():
    engine = Reasoner([Rule("eligible", ALL=["x"])], {"x": True})
    with pytest.raises((TypeError, AttributeError)):
        engine.facts["x"] = "invalid string"
    assert engine.evaluate("eligible") == "TRUE"


def test_metadata_maps_are_read_only():
    engine = Reasoner([Rule("p", ALL=["x"])], costs={"x": 2.0}, questions={"x": "X?"})
    with pytest.raises(TypeError):
        engine.costs["x"] = -1
    with pytest.raises(TypeError):
        engine.questions["x"] = ""
    assert engine.ask("p").cost == 2.0


def test_conflicting_observe_requires_explicit_revision():
    engine = Reasoner([Rule("eligible", ALL=["x"])], {"x": True})
    with pytest.raises(ValueError):
        engine.observe("x", False)
    with pytest.raises(ObservationConflictError):
        engine.observe("x", False)
    assert engine.evaluate("eligible") == "TRUE"
    engine.observe("x", True)  # same value is not a conflict
    engine.observe("x", False, replace=True)
    assert engine.evaluate("eligible") == "FALSE"
    engine.observe("x", None)  # withdrawal means unknown, not False
    assert engine.evaluate("eligible") == "UNKNOWN"


def test_observe_validates_types_and_heads():
    engine = Reasoner([Rule("p", ALL=["x"])])
    with pytest.raises(EvidenceError):
        engine.observe("x", 1)
    with pytest.raises(ValueError):
        engine.observe("p", True)
    with pytest.raises(ValueError):
        engine.observe("nope", True)


# ---- independent reference: evaluates rule *dicts* by plain recursion, no askcert code ----
def _ref_eval(rules: dict, name: str, world: dict) -> bool:
    if name not in rules:
        return world[name]
    r = rules[name]

    def lit(s):
        v = _ref_eval(rules, s.lstrip("!"), world)
        return (not v) if s.startswith("!") else v

    core = all(map(lit, r["conditions"])) if r["op"] == "ALL" else any(map(lit, r["conditions"]))
    return core and not any(map(lit, r["exceptions"]))


def _ref_status(rules, target, atoms, facts):
    free = [a for a in atoms if facts.get(a) is None]
    outs = set()
    for row in product((False, True), repeat=len(free)):
        world = {a: v for a, v in facts.items() if v is not None}
        world.update(zip(free, row, strict=True))
        outs.add(_ref_eval(rules, target, world))
    return "TRUE" if outs == {True} else "FALSE" if outs == {False} else "UNKNOWN"


@pytest.mark.parametrize("seed", range(150))
def test_status_certificate_and_witnesses_match_independent_reference(seed):
    rnd = Random(10_000 + seed)
    atoms = [f"x{i}" for i in range(rnd.randint(2, 7))]
    specs = []
    for i in range(rnd.randint(1, 5)):
        pool = atoms + [s["name"] for s in specs]

        def lit(pool=pool):
            return ("!" if rnd.random() < 0.3 else "") + rnd.choice(pool)

        specs.append(
            {
                "name": f"p{i}",
                "op": rnd.choice(("ALL", "ANY")),
                "conditions": [lit() for _ in range(rnd.randint(0, 4))],
                "exceptions": [lit() for _ in range(rnd.randint(0, 2))],
            }
        )
    table = {s["name"]: s for s in specs}
    target = specs[-1]["name"]
    for _ in range(15):
        engine = Reasoner(specs)
        facts = {a: rnd.choice((True, False, None)) for a in engine.atoms}
        for k, v in facts.items():
            engine.observe(k, v)
        expected = _ref_status(table, target, engine.atoms, facts)
        d = engine.certify(target)
        assert d.status.value == expected
        if d.is_certified:
            ev = {k: facts[k] for k in d.evidence}
            # sufficiency under the reference, and every member necessary (subset-minimal)
            assert _ref_status(table, target, engine.atoms, ev) == expected
            for k in ev:
                assert (
                    _ref_status(table, target, engine.atoms, {j: w for j, w in ev.items() if j != k})
                    != expected
                )
        else:
            pos, neg = d.counterexamples
            assert _ref_eval(table, target, pos) is True
            assert _ref_eval(table, target, neg) is False
            for k, v in facts.items():
                if v is not None:
                    assert pos[k] == v and neg[k] == v
            # every relevant unknown flips the outcome in some completion
            assert set(d.relevant_unknown) <= {k for k, v in facts.items() if v is None}
