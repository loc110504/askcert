"""From free text to a certified decision: how AskCert sits behind a language model.

The pipeline is:   text -> extracted facts -> AskCert -> UNKNOWN + relevant unknowns
                   -> targeted follow-up questions -> answers -> decision + certificate.

The "LLM" below is a DETERMINISTIC STUB (keyword matching) so that the example runs offline
and prints the same output every time. The scheme and rules are FICTIONAL.

Trust boundary: AskCert certifies the decision relative to the facts it is given. It does
NOT check that the extraction was right: if the model misreads the text, the certificate is
a correct proof about the wrong facts. Verify extractions (or ask the user to confirm them)
where that matters.

Run:  python examples/05_llm_reasoning.py
"""

from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_resident", "income_ok", {"not": "prior_award"}]}})

QUESTIONS = {
    "is_resident": "Do you live in the city?",
    "income_ok": "Is your household income under the limit?",
    "prior_award": "Have you received this grant before?",
}

# (phrase, atom, value); the first matching phrase for an atom wins, so keep the negated
# phrases first.
KEYWORDS = [
    ("do not live in the city", "is_resident", False),
    ("live in the city", "is_resident", True),
    ("over the income limit", "income_ok", False),
    ("under the income limit", "income_ok", True),
    ("never received", "prior_award", False),
    ("received this grant before", "prior_award", True),
]


def extract_facts(text: str) -> dict[str, bool]:
    """STUB standing in for a language model: keyword matching, not understanding.

    A real implementation would call a model and parse its structured answer, e.g.
        reply = client.chat(prompt=EXTRACTION_PROMPT.format(text=text))
        return json.loads(reply)  # {"is_resident": true, ...}; omit what the text does not say
    Whatever it returns must map atom names to True/False; leave out what is not stated.
    """
    facts: dict[str, bool] = {}
    for phrase, atom, value in KEYWORDS:
        if phrase in text.lower() and atom not in facts:
            facts[atom] = value
    return facts


def decide(applicant: str, text: str, answers: dict[str, bool]) -> None:
    print(f"== {applicant}: {text!r}")
    facts = extract_facts(text)  # 1. the model reads the text
    print("extracted:", facts)
    result = engine.certify("eligible", facts, witnesses=False)  # 2. AskCert decides
    while not result.decided:
        atom = result.relevant_unknowns[0]  # 3. ask only what can still change the answer
        print(f"  UNKNOWN, still relevant: {list(result.relevant_unknowns)}")
        print(f"  ask: {QUESTIONS[atom]} -> {'yes' if answers[atom] else 'no'}")
        facts[atom] = answers[atom]  # 4. the answer becomes new evidence
        result = engine.certify("eligible", facts, witnesses=False)
    print(f"  {result.status} because {dict(result.certificate or {})}\n")


decide("Applicant 1", "I live in the city and I have never received this grant.", answers={"income_ok": True})
decide(
    "Applicant 2", "I do not live in the city, but my family does.", answers={}
)  # already FALSE: no question is needed
decide(
    "Applicant 3", "I live in the city and we are over the income limit.", answers={"prior_award": False}
)  # already FALSE: prior_award is never asked
