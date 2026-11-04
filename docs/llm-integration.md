# Using AskCert with LLMs and agents

A language model can read free text and propose facts. It is a poor judge of whether a set of rules
is satisfied when some facts are missing. AskCert covers that second part. This page shows four
patterns that combine the two. AskCert has no LLM dependency and no model-specific code; the
snippets use a placeholder `call_llm(prompt: str) -> str`. Plug in any LLM client there: send the
prompt, return the reply text. An offline example with a stub in place of the model is
[`examples/05_llm_reasoning.py`](../examples/05_llm_reasoning.py).

## Division of labour

- **The LLM reads text and proposes facts.** Each fact is `true`, `false` or `null` (the text does
  not say).
- **AskCert decides** whether the goal follows from the rules and the facts you accept, whatever
  the missing facts turn out to be, and says which facts matter: the certificate for a decision,
  the relevant unknowns for an open question.
- **AskCert does not check that the LLM read the text correctly.** A certificate over wrong facts
  is a correct proof about the wrong facts. Patterns B and C and the provenance tip below reduce
  that risk. They do not remove it.

## Shared setup

```python
from askcert import AskCert, AskCertError, EvidenceError
from askcert.serialization import load_json

RULES = {
    "schema_version": "1",
    "atoms": ["is_resident", "income_ok", "prior_award"],
    "rules": {"eligible": {"all": ["is_resident", "income_ok", {"not": "prior_award"}]}},
}
DESCRIPTIONS = {  # one plain-language line per atom; AskCert only sees the names
    "is_resident": "The applicant lives in the city.",
    "income_ok": "Household income is under the limit.",
    "prior_award": "The applicant has received this grant before.",
}
engine = AskCert(RULES)


def call_llm(prompt: str) -> str:
    """Plug in any LLM client: send the prompt, return the reply text."""
    raise NotImplementedError
```

## Pattern A: fact extraction

Build the prompt from `engine.rules.atoms` so that the model sees exactly the atoms AskCert knows.
Ask for JSON with `true`, `false` or `null`, parse the reply defensively, and certify.

```python
def extraction_prompt(text: str, atoms) -> str:
    lines = "\n".join(f"- {a}: {DESCRIPTIONS.get(a, a)}" for a in atoms)
    return (
        "For each statement below, say whether the text states that it is true, states that it "
        "is false, or does not say. Reply with one JSON object with exactly these keys and the "
        "values true, false or null. Use null when the text does not say. Do not guess.\n"
        f"{lines}\n\nText:\n{text}"
    )


def load_object(reply: str) -> dict:
    """Parse a JSON object. An unusable reply means nothing learned, nothing assumed."""
    try:
        data = load_json(reply, "evidence")  # json.loads that also rejects duplicate keys and NaN
    except EvidenceError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_facts(reply: str, atoms) -> dict:
    """Keep only bool or None values for known atoms. Anything else is dropped, not coerced."""
    return {a: v for a, v in load_object(reply).items() if a in atoms and (v is None or isinstance(v, bool))}


text = "I live in the city and we are over the income limit."
atoms = engine.rules.atoms
facts = parse_facts(call_llm(extraction_prompt(text, atoms)), atoms)
result = engine.certify("eligible", facts)
print(result.status, dict(result.certificate or {}), result.relevant_unknowns)
```

Never turn a missing, `null` or invalid value into `False`. `null` means unknown, and AskCert
treats a missing key the same way. If the model wraps its JSON in a code fence, strip the fence
before parsing; if it cannot be parsed, treat every fact as unknown.

## Pattern B: targeted follow-up

When `result.status` is `UNKNOWN`, ask only about `result.relevant_unknowns`. Other facts cannot
settle the goal on their own. Merge the answers and certify again. By
[Proposition 1](semantics.md#proposition-1-decision-locality), part 2, once every relevant unknown
has a `true` or `false` value the goal is decided.

```python
def follow_up(goal: str, text: str, facts: dict):
    result = engine.certify(goal, facts, witnesses=False)
    if not result.decided:
        todo = result.relevant_unknowns
        answers = parse_facts(call_llm(extraction_prompt(text, todo)), todo)
        facts.update({a: v for a, v in answers.items() if v is not None})
        result = engine.certify(goal, facts, witnesses=False)
    return result
```

The questions can go to the user instead of the model: show `DESCRIPTIONS[atom]` for each relevant
unknown and store the answer. If an answer is still missing, the goal stays `UNKNOWN`, and that is
the correct output. The relevant set is sufficient but not always minimal (for `any(a, b)` both
atoms are relevant, yet `a = true` alone decides), so to save questions ask one atom, certify
again, and stop as soon as the goal is decided.

## Pattern C: verify what the decision rests on

When the goal is decided, `result.certificate` lists the known facts that alone fix the status. By
[Proposition 1](semantics.md#proposition-1-decision-locality), part 1, while those facts stand,
learning or revising any other fact cannot change the outcome. So a reviewer, a second extraction pass or the
user needs to re-check only the certificate, not every extracted fact.

```python
facts = {"is_resident": True, "income_ok": False, "prior_award": True}
result = engine.certify("eligible", facts)
print(result.status, dict(result.certificate))  # FALSE, and only prior_award needs a check
for atom, value in result.certificate.items():
    print(f"please confirm: {DESCRIPTIONS[atom]} -> {value}")

facts["prior_award"] = False  # the reviewer corrected it
result = engine.certify("eligible", facts)  # certify again: the basis of the decision changed
print(result.status, dict(result.certificate))
```

A certificate is subset-minimal but not unique, and a correction can change which facts the
decision rests on. Certify again after any revision and use the new result. If a reviewer cannot
confirm a fact, set it to `None`, not `False`.

## Pattern D: AskCert as an agent tool

Expose `certify` as a tool. The schema below is plain JSON Schema; wrap it in whatever tool format
your client expects (some call the schema key `parameters`, others `input_schema`).

```python
CERTIFY_TOOL = {
    "name": "certify_decision",
    "description": (
        "Decide whether the goal follows from the rules and the known facts. Returns status TRUE, "
        "FALSE or UNKNOWN. If UNKNOWN, relevant_unknowns lists the only facts worth asking about; "
        "ask for them, then call again. If decided, certificate lists the facts the decision "
        "rests on. Leave a fact out when it is not known; never guess a value."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "enum": list(engine.rules.rules)},
            "evidence": {
                "type": "object",
                "properties": {a: {"type": ["boolean", "null"]} for a in engine.rules.atoms},
                "additionalProperties": False,
            },
        },
        "required": ["goal"],
    },
}


def certify_decision(goal: str, evidence: dict | None = None) -> dict:
    try:
        return engine.certify(goal, evidence or {}, witnesses=False).to_dict()
    except AskCertError as exc:  # EvidenceError, ResourceLimitExceeded, unknown goal, ...
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}
```

Return `ResourceLimitExceeded` and `EvidenceError` to the agent as tool errors (set the error flag
your client provides, if it has one). Do not convert them to `UNKNOWN`: `UNKNOWN` is an answer, an
error means nothing was decided. The error message says what to fix, such as an unknown atom name
or a non-boolean value. See [results.md](results.md) for the result schema.

Agents that do not run Python can call the command line instead. Evidence goes in on standard
input, and the exit code is 0 for any status, 2 for invalid input and 3 for a resource limit:

```console
$ echo '{"is_resident": true}' | askcert certify --rules rules.json --goal eligible --evidence - --no-witnesses --indent 0
```

See [cli.md](cli.md).

## Provenance tip

Keep the source quote for every fact in your application, and report the certificate facts with
their quotes. AskCert takes only the booleans, so it stays independent of the domain and the model.

```python
def parse_with_quotes(reply: str, atoms):
    """Reply shape: {"atom": {"value": true | false | null, "quote": "exact words from the text"}}"""
    facts, quotes = {}, {}
    for atom, item in load_object(reply).items():
        if atom in atoms and isinstance(item, dict) and isinstance(item.get("value"), bool):
            facts[atom], quotes[atom] = item["value"], str(item.get("quote", ""))
    return facts, quotes
```

After certifying, print `f"{atom} = {value}: {quotes[atom]!r}"` for each certificate fact. A cheap
check on the application side is to confirm that each quote occurs verbatim in the source text;
a quote that does not is a sign the model invented the fact.

## Pitfalls

- **Coercing unknown to `False`.** `bool(None)`, `facts.get(atom, False)`, `value or False` and a
  schema default of `false` all turn "the text does not say" into "the text says no". That can
  turn an `UNKNOWN` into a wrong `TRUE` or `FALSE`.
- **Letting the model invent atom names.** AskCert rejects an unknown atom, and a derived rule
  name, with `EvidenceError`. Build prompts from `engine.rules.atoms`, filter replies, and catch
  `EvidenceError` where evidence comes from other sources, such as tool calls or user input.
- **Non-boolean values.** `"yes"`, `"no"`, `"true"`, `1` and `0` raise `EvidenceError`. Do not
  fix them with `bool(...)`: the string `"false"` is truthy. Map them on purpose, or drop them and
  ask again.
- **Trusting the decision more than the evidence.** `TRUE` means "follows from these facts and
  these rules". It says nothing about whether the facts are true. Show the certificate with its
  quotes, and use pattern C where a wrong fact would be costly.
- **Treating `ResourceLimitExceeded` as `UNKNOWN`.** It means no answer was computed. Raise
  `max_nodes` or `timeout`, or report an error.
