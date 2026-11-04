# Contributing to AskCert

Thank you for your interest in AskCert. This document describes how to set up a
development environment, run the checks, and submit changes.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
```

AskCert requires Python 3.11 or newer.

## Running tests

```bash
pytest                           # default test suite
HYPOTHESIS_PROFILE=ci pytest     # property-based tests with the CI profile
pytest -m slow                   # slow tests
pytest -m z3                     # tests that require the z3 backend
```

## Lint and type checks

```bash
ruff check .
ruff format --check .
mypy
```

## Regression cases

- Every bug fix must add a regression case to `tests/regression/cases.json`.
- Every Hypothesis counterexample must also be added to `tests/regression/cases.json`.

## Scope policy

- The core package stays stdlib-only and domain-independent.
- Integrations with LLMs or with specific domains (for example, legal reasoning)
  belong in `examples/` or in separate packages, not in the core.
- Changes to correctness behavior require tests backed by an oracle.

## Pull request checklist

Before requesting review, confirm that:

- [ ] `pytest` passes locally.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `mypy` passes.
- [ ] Bug fixes include a regression case in `tests/regression/cases.json`.
- [ ] Correctness changes include oracle-backed tests.
- [ ] The core package remains stdlib-only and domain-independent.
- [ ] Public API or result-schema changes are described in `CHANGELOG.md`.
