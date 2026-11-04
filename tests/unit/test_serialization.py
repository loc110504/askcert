"""Serialization (contract Sec. 4): canonical RuleSet dicts/JSON and the stable result schema."""

from __future__ import annotations

import json

import pytest

from askcert import AskCert, CertificationResult, RuleSet, Status, Witnesses

T, F = True, False

CONTRACT_RULES = {
    "schema_version": "1",
    "atoms": ["is_adult", "is_banned"],
    "rules": {"eligible": {"all": ["is_adult", {"not": "is_banned"}]}},
}

CONTRACT_EXAMPLE = {
    "schema_version": "1",
    "goal": "eligible",
    "status": "UNKNOWN",
    "evidence": {"is_adult": True},
    "certificate": None,
    "relevant_unknowns": ["is_banned"],
    "witnesses": {
        "true": {"is_adult": True, "is_banned": False},
        "false": {"is_adult": True, "is_banned": True},
    },
}

RESULT_KEYS = [
    "schema_version",
    "goal",
    "status",
    "evidence",
    "certificate",
    "relevant_unknowns",
    "witnesses",
]

MESSY = {
    "r1": {"all": ["a", "!b"]},
    "r2": {"any": ["a", "b"], "unless": []},
    "r3": {"xor": []},
    "r4": True,
    "r5": "!r1",
    "r6": {"implies": ["a", {"not": "b"}]},
    "r7": {"any": ["a"], "unless": ["c", "!d"]},
    "r8": "a",
    "r9": {"not": {"not": "r8"}},
}

CANONICAL_MESSY = {
    "r1": {"all": ["a", {"not": "b"}]},
    "r2": {"any": ["a", "b"]},  # empty unless is dropped
    "r3": {"xor": []},
    "r4": True,
    "r5": {"not": "r1"},  # "!x" is never emitted
    "r6": {"implies": ["a", {"not": "b"}]},
    "r7": {"any": ["a"], "unless": ["c", {"not": "d"}]},
    "r8": "a",
    "r9": {"not": {"not": "r8"}},
}


# ---------------------------------------------------------------- RuleSet


def test_rule_set_to_dict_is_canonical():
    d = RuleSet.from_dict(MESSY).to_dict()
    assert d == {"schema_version": "1", "rules": CANONICAL_MESSY}
    assert list(d) == ["schema_version", "rules"]
    assert list(d["rules"]) == list(MESSY)  # rule insertion order preserved


def test_rule_set_to_dict_with_declared_atoms_key_order():
    d = RuleSet.from_dict(CONTRACT_RULES).to_dict()
    assert list(d) == ["schema_version", "atoms", "rules"]
    assert sorted(d["atoms"]) == ["is_adult", "is_banned"]
    assert d["rules"] == CONTRACT_RULES["rules"]
    assert "atoms" not in RuleSet.from_dict({"g": "x"}).to_dict()


def test_rule_set_to_dict_uses_plain_json_types():
    d = RuleSet.from_dict({**MESSY, "r10": {"all": ["a", True, False]}}).to_dict()
    assert json.loads(json.dumps(d)) == d

    def walk(x):
        assert type(x) in (dict, list, str, bool), type(x)
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(d["rules"])


@pytest.mark.parametrize(
    "spec",
    [
        MESSY,
        {"rules": MESSY},
        {"schema_version": "1", "rules": MESSY},
        CONTRACT_RULES,
        {"atoms": ["a", "b", "extra"], "rules": {"g": {"any": ["a", "b"]}}},
        {"atoms": [], "rules": {"g": True}},
        {"rules": [{"name": "g", "op": "ALL", "conditions": ["a", "b"], "exceptions": ["c"]}, {"p": "h"}]},
        {"only": False},
    ],
    ids=["shorthand", "doc", "doc-version", "contract", "declared-extra", "declared-empty", "flat", "const"],
)
def test_rule_set_round_trips(spec):
    rs = RuleSet.from_dict(spec)
    assert RuleSet.from_dict(rs.to_dict()) == rs
    assert RuleSet.from_json(rs.to_json()) == rs
    assert RuleSet.from_json(rs.to_json(indent=2, sort_keys=True)) == rs
    assert rs.to_dict() == RuleSet.from_dict(rs.to_dict()).to_dict()  # idempotent
    assert rs.to_json() == RuleSet.from_json(rs.to_json()).to_json()


def test_rule_set_to_json_passes_kwargs_and_parses_back():
    rs = RuleSet.from_dict(MESSY)
    assert json.loads(rs.to_json()) == rs.to_dict()
    pretty = rs.to_json(indent=2)
    assert "\n" in pretty and json.loads(pretty) == rs.to_dict()
    assert list(json.loads(rs.to_json(sort_keys=True))["rules"]) == sorted(MESSY)


def test_rule_set_flat_form_serialises_to_mapping_form():
    flat = {
        "rules": [
            {"name": "e", "op": "ANY", "conditions": ["r", "v"], "exceptions": ["x"]},
            {"p": "f", "op": "ALL", "conditions": ["r"]},
        ]
    }
    assert RuleSet.from_dict(flat).to_dict() == {
        "schema_version": "1",
        "rules": {"e": {"any": ["r", "v"], "unless": ["x"]}, "f": {"all": ["r"]}},
    }


def test_rule_set_load_from_utf8_file(tmp_path):
    rs = RuleSet.from_dict(CONTRACT_RULES)
    path = tmp_path / "rules.json"
    path.write_text(rs.to_json(indent=2), encoding="utf-8")
    assert RuleSet.load(path) == rs
    assert RuleSet.load(str(path)) == rs
    bom_free = tmp_path / "unicode.json"
    bom_free.write_text('{"g": {"all": ["a"]}, "_": "a"}', encoding="utf-8")
    assert RuleSet.load(bom_free).atoms == ("a",)


def test_rule_set_semantics_survive_round_trip():
    rs = RuleSet.from_dict(MESSY)
    rs2 = RuleSet.from_json(rs.to_json())
    ev = {"a": T, "b": F, "c": F, "d": F}
    for goal in MESSY:
        assert AskCert(rs).certify(goal, ev) == AskCert(rs2).certify(goal, ev)


# ---------------------------------------------------------------- CertificationResult


def test_contract_example_result_is_reproduced_exactly():
    res = AskCert(CONTRACT_RULES).certify("eligible", {"is_adult": True})
    d = res.to_dict()
    assert d == CONTRACT_EXAMPLE
    assert list(d) == RESULT_KEYS
    assert list(d["witnesses"]) == ["true", "false"]
    assert json.dumps(d) == json.dumps(CONTRACT_EXAMPLE)  # byte-identical incl. key order
    assert json.loads(res.to_json()) == CONTRACT_EXAMPLE
    assert list(json.loads(res.to_json())) == RESULT_KEYS


def test_to_dict_key_order_decided():
    res = AskCert({"g": {"all": ["a", "b"]}}).certify("g", {"b": T, "a": T})
    d = res.to_dict()
    assert list(d) == RESULT_KEYS
    assert d == {
        "schema_version": "1",
        "goal": "g",
        "status": "TRUE",
        "evidence": {"a": True, "b": True},
        "certificate": {"a": True, "b": True},
        "relevant_unknowns": [],
        "witnesses": None,
    }
    assert list(d["evidence"]) == ["a", "b"]  # sorted keys inside mappings


def test_to_dict_sorts_mapping_keys_regardless_of_input_order():
    engine = AskCert({"g": {"all": ["z", "m", "a"]}})
    d = engine.certify("g", {"z": T, "a": T, "m": None}).to_dict()
    assert list(d["evidence"]) == ["a", "z"]
    assert d["relevant_unknowns"] == ["m"]
    assert list(d["witnesses"]["true"]) == list(d["witnesses"]["false"]) == ["a", "m", "z"]


def test_to_dict_uses_plain_json_types():
    res = AskCert(CONTRACT_RULES).certify("eligible", {"is_adult": True})
    d = res.to_dict()
    assert type(d) is dict and type(d["evidence"]) is dict and type(d["relevant_unknowns"]) is list
    assert type(d["witnesses"]) is dict and type(d["witnesses"]["true"]) is dict
    assert json.loads(json.dumps(d)) == d
    decided = AskCert(CONTRACT_RULES).certify("eligible", {"is_adult": True, "is_banned": False}).to_dict()
    assert type(decided["certificate"]) is dict and decided["witnesses"] is None


@pytest.mark.parametrize(
    "evidence", [{}, {"is_adult": True}, {"is_banned": True}, {"is_adult": True, "is_banned": False}]
)
@pytest.mark.parametrize("witnesses", [True, False])
def test_result_round_trip(evidence, witnesses):
    res = AskCert(CONTRACT_RULES).certify("eligible", evidence, witnesses=witnesses)
    assert CertificationResult.from_dict(res.to_dict()) == res
    assert CertificationResult.from_dict(json.loads(res.to_json())) == res
    assert CertificationResult.from_dict(json.loads(res.to_json(indent=2, sort_keys=False))) == res
    back = CertificationResult.from_dict(res.to_dict())
    assert isinstance(back.status, Status)
    assert back.to_dict() == res.to_dict()


def test_result_round_trip_restores_witness_object():
    res = AskCert(CONTRACT_RULES).certify("eligible", {"is_adult": True})
    back = CertificationResult.from_dict(res.to_dict())
    assert isinstance(back.witnesses, Witnesses)
    assert dict(back.witnesses.true_world) == {"is_adult": True, "is_banned": False}
    assert back.decided is False and back.certificate is None and back.relevant_unknowns == ("is_banned",)


def test_result_from_dict_accepts_a_plain_literal():
    res = CertificationResult.from_dict(CONTRACT_EXAMPLE)
    assert res.goal == "eligible" and res.status == Status.UNKNOWN
    assert res.evidence == {"is_adult": True} and res.relevant_unknowns == ("is_banned",)
    assert res.to_dict() == CONTRACT_EXAMPLE


def test_witnesses_to_dict_shape():
    w = AskCert(CONTRACT_RULES).find_witnesses("eligible", {"is_adult": True})
    assert w.to_dict() == CONTRACT_EXAMPLE["witnesses"]
    assert list(w.to_dict()) == ["true", "false"]
