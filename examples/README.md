# Examples

Runnable, deterministic, offline examples. They use only `askcert` and the standard library.
Install the package first (`pip install .` or `pip install -e .` from the repository root), or
run from a checkout with `PYTHONPATH=src`.

The business and legal examples use **fictional** rules for illustration; they are not real
policies or legal advice.

| File | What it shows | How to run |
|---|---|---|
| [`01_basic_boolean.py`](01_basic_boolean.py) | `all` / `any` / `not`; TRUE, FALSE and UNKNOWN; `x or not x` is TRUE and `x and not x` is FALSE even when `x` is unknown | `python examples/01_basic_boolean.py` |
| [`02_decision_certificates.py`](02_decision_certificates.py) | Subset-minimal certificates (and why they are not unique), witnesses for UNKNOWN, JSON output | `python examples/02_decision_certificates.py` |
| [`03_missing_information.py`](03_missing_information.py) | Relevant unknowns: ask only for facts that can still change the answer, until the goal is decided | `python examples/03_missing_information.py` |
| [`04_business_policy.py`](04_business_policy.py) | Fictional refund and loan pre-screen policies with exceptions (`unless`) | `python examples/04_business_policy.py` |
| [`05_llm_reasoning.py`](05_llm_reasoning.py) | Text to facts (a deterministic stub standing in for a language model) to UNKNOWN, follow-up questions and a certified decision; AskCert does not check the extraction | `python examples/05_llm_reasoning.py` |
| [`06_legal_reasoning.py`](06_legal_reasoning.py) | A fictional toy statute with nested rules and exceptions, decided under missing facts | `python examples/06_legal_reasoning.py` |
| [`07_batch_certification.py`](07_batch_certification.py) | Compile once and certify many cases with `certify_many`; reads the files in `data/`; prints timing | `python examples/07_batch_certification.py` |

## Data files (`data/`)

Fictional scholarship-eligibility rules, used by example 07 and by the command-line interface.

| File | Content |
|---|---|
| [`data/eligibility_rules.json`](data/eligibility_rules.json) | Rule set; goal `eligible` |
| [`data/eligibility_evidence.json`](data/eligibility_evidence.json) | One evidence object (leaves `income_ok` and `on_waiver` unknown) |
| [`data/cases.jsonl`](data/cases.jsonl) | One evidence object per line, for `askcert batch` |

```bash
askcert validate --rules examples/data/eligibility_rules.json
askcert certify  --rules examples/data/eligibility_rules.json --goal eligible \
                 --evidence examples/data/eligibility_evidence.json
askcert batch    --rules examples/data/eligibility_rules.json --goal eligible \
                 --cases examples/data/cases.jsonl --no-witnesses
```
