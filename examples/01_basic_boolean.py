"""Basic Boolean reasoning: all / any / not, and the three outcomes TRUE, FALSE and UNKNOWN.

Run:  python examples/01_basic_boolean.py
"""

from askcert import AskCert

# Rules are plain dicts. A bare string is a reference to another rule or to a base atom;
# {"not": e}, {"all": [...]} and {"any": [...]} are classical negation, AND and OR.
engine = AskCert(
    {
        "can_enter": {"all": ["has_ticket", {"not": "is_banned"}]},
        "can_pay": {"any": ["has_cash", "has_card"]},
        "always": {"any": ["x", {"not": "x"}]},  # x OR NOT x
        "never": {"all": ["x", {"not": "x"}]},  # x AND NOT x
    }
)


def show(goal: str, evidence: dict[str, bool | None]) -> None:
    print(f"{goal:9} given {evidence!s:46} -> {engine.evaluate(goal, evidence)}")


print("-- everything known")
show("can_enter", {"has_ticket": True, "is_banned": False})
show("can_enter", {"has_ticket": True, "is_banned": True})

print("-- missing evidence: unknown is never treated as False")
show("can_enter", {"has_ticket": True})  # depends on is_banned -> UNKNOWN
show("can_pay", {})  # nothing known -> UNKNOWN

print("-- a decision can be reached without knowing everything")
show("can_enter", {"has_ticket": False})  # no ticket: FALSE whatever is_banned is
show("can_pay", {"has_card": True})  # one way to pay is enough: TRUE

print("-- completion semantics: the answer must hold in every completion of the unknowns")
show("always", {})  # x OR NOT x is TRUE even though x is unknown
show("never", {})  # x AND NOT x is FALSE even though x is unknown

print("-- None means unknown, exactly like leaving the atom out")
show("can_pay", {"has_cash": None, "has_card": None})
