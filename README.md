# AskCert

**AskCert: a Python library for certifiable Boolean reasoning under incomplete evidence.**

You have rules and only some of the facts. AskCert tells you whether the conclusion is already
settled whatever the missing facts turn out to be, which of the known facts are enough to settle
it, and which unknown facts can still change it. It never treats a missing fact as false.

[Documentation](https://github.com/loc110504/askcert/tree/main/docs) ·
[Examples](https://github.com/loc110504/askcert/blob/main/examples/README.md) ·
[Changelog](https://github.com/loc110504/askcert/blob/main/CHANGELOG.md)

## Install

```bash
pip install askcert
```

AskCert has no runtime dependencies (standard library only) and needs Python 3.11 or newer.

## Quickstart

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})

r = engine.certify("eligible", {"is_adult": True})  # is_banned is not known
print(r.status, r.relevant_unknowns)
print(dict(r.witnesses.true_world), dict(r.witnesses.false_world))

r = engine.certify("eligible", {"is_adult": True, "is_banned": False})
print(r.status, dict(r.certificate))

r = engine.certify("eligible", {"is_adult": False})  # settled although is_banned is unknown
print(r.status, dict(r.certificate))
```

```text
UNKNOWN ('is_banned',)
{'is_adult': True, 'is_banned': False} {'is_adult': True, 'is_banned': True}
TRUE {'is_adult': True, 'is_banned': False}
FALSE {'is_adult': False}
```

With only `is_adult` known the answer is `UNKNOWN`: `is_banned` can still flip it, and the two
witness worlds show both outcomes. With `is_banned = False` the goal is `TRUE`, and the
certificate lists the facts that justify it. If the applicant is not an adult the goal is `FALSE`
whatever `is_banned` is, and `is_adult = False` alone is the certificate.

## What you get

For a goal and some evidence, `certify` returns a `CertificationResult` with:

- **A status: `TRUE`, `FALSE` or `UNKNOWN`**, defined over *all completions* of the unknown facts.
  A goal is `TRUE` if it holds however the unknowns are filled in, `FALSE` if it fails however they
  are filled in, and `UNKNOWN` if both outcomes remain possible.
- **A supporting certificate** when the goal is decided: a subset of the known facts that alone
  fixes the status, from which no fact can be removed.
- **The relevant unknowns** when the goal is `UNKNOWN`: exactly the unknown atoms that can still
  change the outcome. Supplying all of them always settles the goal.
- **Witnesses** when the goal is `UNKNOWN`: two complete worlds that agree with the evidence, one
  where the goal holds and one where it fails.

### Completion semantics, not Kleene logic

Because the status is defined over completions, AskCert recognises tautologies and contradictions
even when the facts involved are unknown. Kleene three-valued logic evaluates bottom-up and would
answer `UNKNOWN` for both rules below.

```python
from askcert import AskCert

engine = AskCert(
    {
        "tautology": {"any": ["x", {"not": "x"}]},
        "contradiction": {"all": ["x", {"not": "x"}]},
    }
)
print(engine.evaluate("tautology"), engine.evaluate("contradiction"))  # x is unknown
```

```text
TRUE FALSE
```

A closed-world evaluator would instead read a missing fact as false. AskCert does neither: a
missing fact is unknown, and the answer says so.

### The certificate is subset-minimal

No fact in the certificate can be dropped without losing the status. That does not make it the
*smallest* possible certificate, and it need not be unique. AskCert starts from all known facts
that the goal depends on and tries to delete them one at a time in lexicographic order of atom
name, so the result is deterministic. Here `{a}` alone would also settle the goal, but the
procedure returns `{b, c}`:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["a", {"all": ["b", "c"]}]}})
print(dict(engine.certify("g", {"a": True, "b": True, "c": True}).certificate))
```

```text
{'b': True, 'c': True}
```

Minimum-cardinality certificates are not computed. See
[semantics](https://github.com/loc110504/askcert/blob/main/docs/semantics.md#supporting-certificates).

### Relevant unknowns are exact

Relevance is a property of the logic, not of the rule text. In the rule below `b` appears but
cannot matter, because `a or (a and b)` is just `a`:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["a", {"all": ["a", "b"]}]}})
print(engine.certify("g").relevant_unknowns)
```

```text
('a',)
```

### UNKNOWN never means that the computation failed

If a computation hits a resource limit (`max_nodes`, `timeout`, or the recursion limit), AskCert
raises `ResourceLimitExceeded`. It does not return `UNKNOWN`.

```python
from askcert import AskCert, ResourceLimitExceeded

engine = AskCert({"g": {"all": ["a", "b"]}}, max_nodes=3)
try:
    engine.evaluate("g")
except ResourceLimitExceeded as exc:
    print("no answer:", exc.limit)
```

```text
no answer: max_nodes
```

### Machine-readable results

`result.to_dict()` and `result.to_json()` give a stable JSON document (schema version 1),
documented in [results.md](https://github.com/loc110504/askcert/blob/main/docs/results.md):

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(engine.certify("eligible", {"is_adult": False}).to_json(indent=2))
```

```json
{
  "schema_version": "1",
  "goal": "eligible",
  "status": "FALSE",
  "evidence": {
    "is_adult": false
  },
  "certificate": {
    "is_adult": false
  },
  "relevant_unknowns": [],
  "witnesses": null
}
```

## Rule format at a glance

Rules are data: a JSON document or a Python `dict`, never executed. A rule is an expression over
atoms and other rules.

| JSON | Meaning |
|---|---|
| `true`, `false` | Constant |
| `"name"` | A rule or a base atom |
| `"!name"` or `{"not": e}` | Negation |
| `{"all": [e, ...]}` | Conjunction (empty is true) |
| `{"any": [e, ...]}` | Disjunction (empty is false) |
| `{"xor": [e, ...]}` | Odd parity |
| `{"implies": [e1, e2]}` | `not e1 or e2` |
| `{"all": [...], "unless": [e, ...]}` or the same with `"any"` | The core holds and none of the exceptions does |

Rules may refer to other rules but must not form cycles. Declare `"atoms": [...]` in a document to
catch typos. The flat list form `{"name", "op", "conditions", "exceptions"}` is accepted too. See
[rule-format.md](https://github.com/loc110504/askcert/blob/main/docs/rule-format.md).

```python
from askcert import AskCert

engine = AskCert(
    {
        "schema_version": "1",
        "atoms": ["enrolled", "gpa_ok", "income_ok", "on_waiver", "resident", "has_sanction"],
        "rules": {
            "academic_ok": {"all": ["enrolled", "gpa_ok"]},
            "financial_ok": {"any": ["income_ok", "on_waiver"]},
            "eligible": {"all": ["academic_ok", "financial_ok", "resident"], "unless": ["has_sanction"]},
        },
    }
)
r = engine.certify("eligible", {"enrolled": True, "gpa_ok": True, "resident": True, "has_sanction": False})
print(r.status, r.relevant_unknowns)
```

```text
UNKNOWN ('income_ok', 'on_waiver')
```

## Command line

```console
$ askcert validate --rules examples/data/eligibility_rules.json
{"valid": true, "schema_version": "1", "rules": ["academic_ok", "financial_ok", "eligible"], "atoms": ["enrolled", "gpa_ok", "has_sanction", "income_ok", "on_waiver", "resident"]}
$ askcert evaluate --rules examples/data/eligibility_rules.json --goal eligible --evidence examples/data/eligibility_evidence.json
{"schema_version": "1", "goal": "eligible", "status": "UNKNOWN"}
$ askcert certify --rules examples/data/eligibility_rules.json --goal eligible --evidence examples/data/eligibility_evidence.json --no-witnesses --indent 0
{"schema_version": "1", "goal": "eligible", "status": "UNKNOWN", "evidence": {"enrolled": true, "gpa_ok": true, "has_sanction": false, "resident": true}, "certificate": null, "relevant_unknowns": ["income_ok", "on_waiver"], "witnesses": null}
```

(Run from a clone of the repository; the files are in
[`examples/data/`](https://github.com/loc110504/askcert/tree/main/examples/data).)
`askcert batch` certifies many evidence objects from a JSON Lines file with one compiled engine.
Exit code 0 means success whatever the status (`UNKNOWN` is not an error), 2 means invalid input,
and 3 means a resource limit was hit. The full reference is
[cli.md](https://github.com/loc110504/askcert/blob/main/docs/cli.md). The same functionality is
available as `python -m askcert`.

## Use cases

**LLM and agent pipelines.** A language model or a parser extracts facts from text; AskCert says
whether those facts settle the decision and, if not, which facts to ask for next. The model reads
the text again only for the facts that matter: the relevant unknowns when the goal is undecided,
the certificate when you want to double-check a decision.

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})


def extract_facts(text):
    """Stand-in for an LLM or form parser: return only what the text states."""
    facts = {}
    if "I am 34" in text:
        facts["is_adult"] = True
    return facts


result = engine.certify("eligible", extract_facts("Hello, I am 34 and would like to apply."))
if result.decided:
    print("decision:", result.status, "based on", dict(result.certificate))
else:
    for atom in result.relevant_unknowns:
        print("ask:", atom)
```

```text
ask: is_banned
```

AskCert does not check that the extraction is right; see the trust boundary below. A complete
example is
[`examples/05_llm_reasoning.py`](https://github.com/loc110504/askcert/blob/main/examples/05_llm_reasoning.py).
For prompts, follow-up questions and agent tool use, see the
[LLM integration guide](https://github.com/loc110504/askcert/blob/main/docs/llm-integration.md).

**Rule-based business policies.** Refund, approval and pre-screening rules with exceptions
(`unless`), evaluated on whatever a customer has told you so far, without guessing the rest. See
[`examples/04_business_policy.py`](https://github.com/loc110504/askcert/blob/main/examples/04_business_policy.py).

**Legal and clinical decision support.** Conditional rules with exceptions, and a record of which
facts a conclusion rests on. See
[`examples/06_legal_reasoning.py`](https://github.com/loc110504/askcert/blob/main/examples/06_legal_reasoning.py).

> **Trust boundary.** AskCert certifies a conclusion *relative to the rules and evidence you
> supply*. It does not verify that the evidence is true or that the rules are correct. Its output
> is not legal, medical or other professional advice.

## Relation to PYTHEN

[PYTHEN](https://github.com/nguyenthanhasia/pythen) is a Python framework for executing readable
rules with conditions and exceptions, aimed at legal reasoning. AskCert has a different scope:
certification of a conclusion when evidence is partial. The two are complementary.

| | PYTHEN | AskCert |
|---|---|---|
| Question answered | Does the predicate hold for this list of facts? | Is the conclusion settled, by which facts, and what can still change it? |
| Evidence | A list of facts that hold | A partial assignment: true, false or unknown |
| A fact that is not supplied | Does not hold (closed-world evaluation) | Unknown; never treated as false |
| Result | `bool` | `TRUE`, `FALSE` or `UNKNOWN`, with certificate, relevant unknowns and witnesses |
| Rule layout | `{"p", "op", "conditions", "exceptions"}` | The same flat layout, plus a nested format with `not`, `xor`, `implies` and constants |

The flat PYTHEN rule format is accepted by `RuleSet.from_dict`. The evaluation semantics differ
when evidence is missing: with the same rules and the same facts, a closed-world run can answer
where AskCert reports `UNKNOWN` and names the missing fact that decides it.

```python
from askcert import AskCert, RuleSet

rules = RuleSet.from_dict(
    {
        "rules": [
            {
                "p": "eligible",
                "op": "ANY",
                "conditions": ["resident", "valid_visa"],
                "exceptions": ["restricted"],
            },
        ]
    }
)
r = AskCert(rules).certify("eligible", {"resident": True})
print(r.status, r.relevant_unknowns)
```

```text
UNKNOWN ('restricted',)
```

## Correctness and testing

The test suite compares AskCert with two independent oracles that do not import AskCert: a
brute-force enumerator of the completions and a Z3-based checker. The checks cover the status,
the certificate (sufficient, subset-minimal, and equal to the documented deletion result), the
relevant unknowns (exact set equality) and the witnesses.

- Unit tests, a golden regression corpus with exact expected outputs, and integration tests of the
  command line and the examples.
- Hypothesis property tests on random rule documents and evidence, including Proposition 1 of the
  semantics page (decision locality).
- A seeded corpus of 10,000 random formula/evidence pairs checked against the brute-force oracle
  (`pytest -m slow`), and a Z3 differential suite.

This is strong evidence on small generated formulas (2 to 8 atoms), not a formal proof.

## Limitations

- Evidence and atoms are Boolean. There is no first-order logic, no probabilities, no cyclic rules
  and no rule priorities.
- Certificates are subset-minimal, not minimum-cardinality, and not unique.
- Worst-case cost is exponential; `max_nodes` and `timeout` raise `ResourceLimitExceeded` instead
  of returning a wrong or `UNKNOWN` answer. Computing a certificate for a decided goal costs one
  diagram restriction per known fact, so it grows with (known facts × diagram size).
- `AskCert` and `Reasoner` instances are not thread-safe.
- Names are ASCII identifiers.
- Correctness is relative to the supplied rules and evidence.

## Documentation

| | |
|---|---|
| [semantics](https://github.com/loc110504/askcert/blob/main/docs/semantics.md) | Formal definitions, Proposition 1, what is not supported |
| [rule-format](https://github.com/loc110504/askcert/blob/main/docs/rule-format.md) | JSON rule format |
| [api](https://github.com/loc110504/askcert/blob/main/docs/api.md) | Python API reference |
| [cli](https://github.com/loc110504/askcert/blob/main/docs/cli.md) | Command-line reference |
| [results](https://github.com/loc110504/askcert/blob/main/docs/results.md) | JSON result schema |
| [llm-integration](https://github.com/loc110504/askcert/blob/main/docs/llm-integration.md) | Using AskCert with LLMs and agents |

Contributions are welcome: see
[CONTRIBUTING.md](https://github.com/loc110504/askcert/blob/main/CONTRIBUTING.md). Report security
issues as described in
[SECURITY.md](https://github.com/loc110504/askcert/blob/main/SECURITY.md).

## Citing

If you use AskCert in research, please cite it using
[`CITATION.cff`](https://github.com/loc110504/askcert/blob/main/CITATION.cff) (GitHub shows a "Cite
this repository" button once the repository is public).

## License

MIT. See [LICENSE](https://github.com/loc110504/askcert/blob/main/LICENSE). Copyright (c)
Hoang-Loc Cao.
