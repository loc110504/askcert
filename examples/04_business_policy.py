"""Business policy with exceptions: a refund and a loan pre-screen.

The policies below are FICTIONAL and only illustrate how rules with exceptions are written;
they are not taken from any real company.

Run:  python examples/04_business_policy.py
"""

from askcert import AskCert, RuleSet

# "unless" lists exceptions: core AND NOT(any exception). An exception is not "negation as
# failure": it only blocks the rule when it is known (or forced) to be true.
policy = RuleSet.from_dict(
    {
        "atoms": [
            "within_30_days",
            "item_unused",
            "has_receipt",
            "final_sale",
            "fraud_flag",
            "income_verified",
            "debt_ratio_ok",
            "credit_score_ok",
            "has_guarantor",
            "bankruptcy_on_file",
        ],
        "rules": {
            "refund_approved": {
                "all": ["within_30_days", "item_unused", "has_receipt"],
                "unless": ["final_sale", "fraud_flag"],
            },
            # Credit needs verified income and a healthy debt ratio, plus either a good
            # credit score or a guarantor; a bankruptcy on file blocks it.
            "loan_prescreen": {
                "all": ["income_verified", "debt_ratio_ok", {"any": ["credit_score_ok", "has_guarantor"]}],
                "unless": ["bankruptcy_on_file"],
            },
        },
    }
)
engine = AskCert(policy)


def report(title: str, goal: str, evidence: dict[str, bool]) -> None:
    result = engine.certify(goal, evidence)
    print(f"{title}\n  {goal} = {result.status}")
    if result.decided:
        print("  because", dict(result.certificate or {}))
    else:
        print("  still needed:", ", ".join(result.relevant_unknowns))


report(
    "Refund, everything in order",
    "refund_approved",
    {
        "within_30_days": True,
        "item_unused": True,
        "has_receipt": True,
        "final_sale": False,
        "fraud_flag": False,
    },
)
report(
    "Refund, receipt present but the item is a final-sale item",
    "refund_approved",
    {"has_receipt": True, "final_sale": True},
)  # exception alone decides it
report(
    "Refund, nothing about exceptions yet",
    "refund_approved",
    {"within_30_days": True, "item_unused": True, "has_receipt": True},
)
report(
    "Loan, strong application but no bankruptcy information",
    "loan_prescreen",
    {"income_verified": True, "debt_ratio_ok": True, "credit_score_ok": True},
)
report(
    "Loan, a guarantor makes the credit score irrelevant",
    "loan_prescreen",
    {"income_verified": True, "debt_ratio_ok": True, "has_guarantor": True, "bankruptcy_on_file": False},
)
