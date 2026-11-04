"""Certificates and witnesses: why a decision holds, and what could still change it.

Run:  python examples/02_decision_certificates.py
"""

from askcert import AskCert

engine = AskCert(
    {
        # Editing is allowed for administrators, or for verified owners.
        "can_edit": {"any": ["is_admin", {"all": ["is_owner", "is_verified"]}]},
    }
)

# 1. A decided goal comes with a subset-minimal certificate: a part of the evidence that
#    alone fixes the answer, from which no single fact can be removed. Evidence that is
#    not needed (here: nothing else is known) is left out.
evidence = {"is_admin": True, "is_owner": True, "is_verified": True}
result = engine.certify("can_edit", evidence)
print("status      :", result.status)
print("evidence    :", dict(result.evidence))
print("certificate :", dict(result.certificate or {}))

# 2. Subset-minimal is not minimum-size, and it is not unique. {is_admin} alone would also
#    decide the goal, but AskCert tries to drop atoms in alphabetical order, so it keeps the
#    larger {is_owner, is_verified}. The choice is deterministic: same input, same certificate.
for candidate in ({"is_admin": True}, {"is_owner": True, "is_verified": True}, {"is_owner": True}):
    print("check       :", candidate, "->", engine.evaluate("can_edit", candidate))

# 3. A FALSE decision is certified in the same way.
result = engine.certify("can_edit", {"is_admin": False, "is_owner": False})
print("\nstatus      :", result.status)
print("certificate :", dict(result.certificate or {}))

# 4. UNKNOWN has no certificate. Instead AskCert lists the relevant unknowns (the missing
#    atoms whose value can still change the outcome) and two witnesses: complete worlds that
#    agree with the evidence, one where the goal is true and one where it is false.
result = engine.certify("can_edit", {"is_admin": False, "is_owner": True})
print("\nstatus      :", result.status)
print("certificate :", result.certificate)
print("relevant    :", result.relevant_unknowns)
assert result.witnesses is not None
print("true world  :", dict(result.witnesses.true_world))
print("false world :", dict(result.witnesses.false_world))

# 5. The whole result serializes to stable JSON (schema version 1).
print("\n" + result.to_json(indent=2))
