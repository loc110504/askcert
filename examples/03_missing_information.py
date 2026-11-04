"""Missing information: ask only for the facts that can still change the answer.

Run:  python examples/03_missing_information.py
"""

from askcert import AskCert

engine = AskCert(
    {
        # A visitor is admitted with a ticket and an ID, or with a staff pass.
        "admitted": {"any": [{"all": ["has_ticket", "has_id"]}, "has_staff_pass"]},
    }
)

evidence: dict[str, bool | None] = {}
print("known:", evidence)
result = engine.certify("admitted", evidence)
print("status:", result.status, "| relevant unknowns:", result.relevant_unknowns)

# Pretend these are the true answers; in a real application they come from a person,
# a database or a sensor. The loop asks about one relevant unknown at a time.
truth = {"has_staff_pass": False, "has_ticket": True, "has_id": True}

while not result.decided:
    atom = result.relevant_unknowns[0]
    evidence[atom] = truth[atom]
    print(f"\nask {atom!r} -> {truth[atom]}")
    result = engine.certify("admitted", evidence)
    print("known:", evidence)
    print("status:", result.status, "| relevant unknowns:", result.relevant_unknowns)

print("\ndecided:", result.status, "because", dict(result.certificate or {}))

# Facts that cannot matter are never requested: once the staff pass is True, has_ticket
# and has_id are irrelevant and the goal is already decided.
print("\nstaff pass only:", engine.certify("admitted", {"has_staff_pass": True}).relevant_unknowns)
