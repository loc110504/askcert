"""Hand-derived expected answers (paper Sec. 3 completion semantics).

Shared by the unit tests (checked against askcert) and by the oracle self-checks
(checked against the brute-force and z3 oracles), so the oracles are themselves
validated against values worked out by hand.

Each row: ``(id, rules, goal, evidence, status, certificate, relevant, witnesses)``
where ``witnesses`` is ``(true_world, false_world)`` or ``None``.  Witness worlds are
the lexicographically smallest ones (False < True over sorted atoms), i.e. what the
contract's False-branch-first DFS yields under the default variable order; in every
row below the unknown atoms are forced, so the values are unambiguous.
"""

from __future__ import annotations

T, F = True, False

AND = {"g": {"all": ["a", "b"]}}
OR = {"g": {"any": ["a", "b"]}}
NOT = {"g": {"not": "a"}}
EXCLUDED_MIDDLE = {"g": {"any": ["a", "!a"]}}
CONTRADICTION = {"g": {"all": ["a", "!a"]}}
ABSORPTION = {"g": {"any": ["a", {"all": ["a", "b"]}]}}  # a or (a and b)
AND_NOT = {"g": {"all": ["a", "!b"]}}  # a and not b

OPERATOR_TABLE = [
    # --- the ten rows of the paper-style operator table
    ("and_1_1", AND, "g", {"a": T, "b": T}, "TRUE", {"a": T, "b": T}, (), None),
    ("and_1_?", AND, "g", {"a": T}, "UNKNOWN", None, ("b",), ({"a": T, "b": T}, {"a": T, "b": F})),
    ("and_0_?", AND, "g", {"a": F}, "FALSE", {"a": F}, (), None),
    ("or_1_?", OR, "g", {"a": T}, "TRUE", {"a": T}, (), None),
    ("or_0_?", OR, "g", {"a": F}, "UNKNOWN", None, ("b",), ({"a": F, "b": T}, {"a": F, "b": F})),
    ("not_?", NOT, "g", {}, "UNKNOWN", None, ("a",), ({"a": F}, {"a": T})),
    ("excluded_middle_?", EXCLUDED_MIDDLE, "g", {}, "TRUE", {}, (), None),
    ("contradiction_?", CONTRADICTION, "g", {}, "FALSE", {}, (), None),
    ("absorption_1_?", ABSORPTION, "g", {"a": T}, "TRUE", {"a": T}, (), None),
    ("and_not_1_?", AND_NOT, "g", {"a": T}, "UNKNOWN", None, ("b",), ({"a": T, "b": F}, {"a": T, "b": T})),
    # --- neighbouring rows
    ("and_?_?", AND, "g", {}, "UNKNOWN", None, ("a", "b"), ({"a": T, "b": T}, {"a": F, "b": F})),
    ("or_?_?", OR, "g", {}, "UNKNOWN", None, ("a", "b"), ({"a": F, "b": T}, {"a": F, "b": F})),
    ("or_?_0", OR, "g", {"b": F}, "UNKNOWN", None, ("a",), ({"a": T, "b": F}, {"a": F, "b": F})),
    ("or_1_1", OR, "g", {"a": T, "b": T}, "TRUE", {"b": T}, (), None),  # lexicographic deletion drops a
    ("and_0_0", AND, "g", {"a": F, "b": F}, "FALSE", {"b": F}, (), None),
    ("not_1", NOT, "g", {"a": T}, "FALSE", {"a": T}, (), None),
    ("not_0", NOT, "g", {"a": F}, "TRUE", {"a": F}, (), None),
    ("excluded_middle_1", EXCLUDED_MIDDLE, "g", {"a": T}, "TRUE", {}, (), None),
    ("contradiction_1", CONTRADICTION, "g", {"a": T}, "FALSE", {}, (), None),
    ("absorption_0_?", ABSORPTION, "g", {"a": F}, "FALSE", {"a": F}, (), None),
    ("absorption_?_?", ABSORPTION, "g", {}, "UNKNOWN", None, ("a",), ({"a": T, "b": F}, {"a": F, "b": F})),
]
