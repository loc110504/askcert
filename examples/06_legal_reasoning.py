"""Legal-style reasoning: a conditional rule with exceptions, decided under missing facts.

The "Tenancy Notice Act" below is a FICTIONAL toy statute invented for this example. It is
illustrative only and NOT LEGAL ADVICE; AskCert does not interpret law, it only checks what
follows from the rules and facts it is given.

  s1  A landlord may end a tenancy if valid notice was given and the notice period was met.
  s2  Notice is valid if it was in writing and it was served on the tenant.
  s3  The notice period is met if the tenant has lived there under a year and 30 days passed,
      or has lived there a year or more and 90 days passed.
  s4  Exceptions: the landlord may not end the tenancy during a protected period, or in
      retaliation for a complaint.

Run:  python examples/06_legal_reasoning.py
"""

from askcert import AskCert

engine = AskCert(
    {
        "valid_notice": {"all": ["notice_in_writing", "notice_served"]},
        "notice_period_met": {
            "any": [
                {"all": ["tenancy_under_one_year", "thirty_days_passed"]},
                {"all": [{"not": "tenancy_under_one_year"}, "ninety_days_passed"]},
            ]
        },
        "may_end_tenancy": {
            "all": ["valid_notice", "notice_period_met"],
            "unless": ["protected_period", "retaliation"],
        },
    }
)


def analyse(title: str, facts: dict[str, bool]) -> None:
    result = engine.certify("may_end_tenancy", facts)
    print(f"{title}\n  facts : {facts}\n  result: {result.status}")
    if result.decided:
        print("  holds regardless of everything not listed here:", dict(result.certificate or {}))
    else:
        print("  open questions that could still change it:", list(result.relevant_unknowns))
    print()


analyse(
    "Case A: all conditions shown, no exception known",
    {
        "notice_in_writing": True,
        "notice_served": True,
        "tenancy_under_one_year": True,
        "thirty_days_passed": True,
    },
)  # exceptions not established -> UNKNOWN

analyse(
    "Case B: same facts, exceptions ruled out",
    {
        "notice_in_writing": True,
        "notice_served": True,
        "tenancy_under_one_year": True,
        "thirty_days_passed": True,
        "protected_period": False,
        "retaliation": False,
    },
)

analyse("Case C: notice was not in writing", {"notice_in_writing": False})  # decided FALSE from a single fact

analyse(
    "Case D: retaliation established, nothing else known", {"retaliation": True}
)  # the exception alone defeats the rule

# A decision about a part of the statute works the same way.
part = engine.certify("notice_period_met", {"tenancy_under_one_year": False, "ninety_days_passed": True})
print("s3 alone (long tenancy, 90 days passed):", part.status, dict(part.certificate or {}))
