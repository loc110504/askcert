# Result format (JSON schema v1)

`CertificationResult.to_dict()` and `CertificationResult.to_json()` produce a stable JSON document.
The command line prints the same document for `askcert certify` and one document per line for
`askcert batch` (see [cli.md](cli.md)). This page describes it field by field.

Code blocks on this page are complete and runnable, and the output shown is what they print.

## Contents

- [An UNKNOWN result](#an-unknown-result)
- [A decided result](#a-decided-result)
- [Fields](#fields)
- [Invariants](#invariants)
- [Reading and writing results](#reading-and-writing-results)
- [Other JSON documents](#other-json-documents)

## An UNKNOWN result

The rules are a small scholarship check: the applicant must pass an academic check and a financial
check, be a resident, and have no sanction.

```python
from askcert import AskCert

engine = AskCert(
    {
        "academic_ok": {"all": ["enrolled", "gpa_ok"]},
        "financial_ok": {"any": ["income_ok", "on_waiver"]},
        "eligible": {"all": ["academic_ok", "financial_ok", "resident"], "unless": ["has_sanction"]},
    }
)
evidence = {"enrolled": True, "gpa_ok": True, "resident": True, "has_sanction": False}
result = engine.certify("eligible", evidence)
print(result.to_json(indent=2))
```

```json
{
  "schema_version": "1",
  "goal": "eligible",
  "status": "UNKNOWN",
  "evidence": {
    "enrolled": true,
    "gpa_ok": true,
    "has_sanction": false,
    "resident": true
  },
  "certificate": null,
  "relevant_unknowns": [
    "income_ok",
    "on_waiver"
  ],
  "witnesses": {
    "true": {
      "enrolled": true,
      "gpa_ok": true,
      "has_sanction": false,
      "income_ok": false,
      "on_waiver": true,
      "resident": true
    },
    "false": {
      "enrolled": true,
      "gpa_ok": true,
      "has_sanction": false,
      "income_ok": false,
      "on_waiver": false,
      "resident": true
    }
  }
}
```

The goal is not decided. Either `income_ok` or `on_waiver` would have to be true, and both are
unknown, so both are relevant. The two witness worlds agree with the evidence and differ only in
`on_waiver`.

## A decided result

Add the missing financial fact:

```python
result = engine.certify("eligible", {**evidence, "income_ok": True})
print(result.to_json(indent=2))
```

```json
{
  "schema_version": "1",
  "goal": "eligible",
  "status": "TRUE",
  "evidence": {
    "enrolled": true,
    "gpa_ok": true,
    "has_sanction": false,
    "income_ok": true,
    "resident": true
  },
  "certificate": {
    "enrolled": true,
    "gpa_ok": true,
    "has_sanction": false,
    "income_ok": true,
    "resident": true
  },
  "relevant_unknowns": [],
  "witnesses": null
}
```

A decision can also be settled by a single fact. A sanction alone makes the goal FALSE, whatever
else is known or unknown:

```python
result = engine.certify("eligible", {"has_sanction": True, "enrolled": True})
print(result.to_json())
```

```json
{"schema_version": "1", "goal": "eligible", "status": "FALSE", "evidence": {"enrolled": true, "has_sanction": true}, "certificate": {"has_sanction": true}, "relevant_unknowns": [], "witnesses": null}
```

## Fields

The document is a JSON object with exactly these keys, in this order.

| Key | JSON type | Description |
|---|---|---|
| `schema_version` | string | Always `"1"` in this version. Check it before reading the other fields. |
| `goal` | string | The goal that was certified, as passed by the caller. |
| `status` | string | `"TRUE"`, `"FALSE"` or `"UNKNOWN"`, under [completion semantics](semantics.md). |
| `evidence` | object | The known facts that were supplied: atom name to `true` or `false`. Entries given as `null` are dropped (they are unknown). Includes facts outside the goal's cone. Keys sorted. |
| `certificate` | object or `null` | If decided: a subset-minimal set of facts, a subset of `evidence` restricted to the goal's cone, that alone fixes the status. May be `{}` when the goal is a tautology or contradiction. `null` if the status is `"UNKNOWN"`. Keys sorted. |
| `relevant_unknowns` | array of strings | If `"UNKNOWN"`: the unknown cone atoms that can still change the outcome, sorted by name. `[]` if decided. |
| `witnesses` | object or `null` | If `"UNKNOWN"` and witnesses were requested: `{"true": world, "false": world}`. Otherwise `null`. |

A *world* is an object that maps **every atom of the goal's cone** (not only the unknown ones) to
`true` or `false`, with keys sorted. In `witnesses.true` the goal evaluates to true, in
`witnesses.false` it evaluates to false, and both agree with `evidence` on every cone atom.

`witnesses` is `null` in two cases: the goal is decided, or witnesses were switched off
(`certify(..., witnesses=False)`, `--no-witnesses`). Use `status`, not `witnesses`, to tell whether
a goal is decided.

Definitions of certificate, relevant unknowns and witnesses: [semantics.md](semantics.md).

## Invariants

For any result produced by AskCert:

| Condition | Consequence |
|---|---|
| `status` is `"UNKNOWN"` | `certificate` is `null`; `relevant_unknowns` is not empty. |
| `status` is `"TRUE"` or `"FALSE"` | `certificate` is an object; `relevant_unknowns` is `[]`; `witnesses` is `null`. |
| `certificate` is an object | Every entry of `certificate` is also in `evidence`. |
| `witnesses` is an object | `status` is `"UNKNOWN"`. |

Keys appear in the order of the table above. Inside `evidence`, `certificate` and the witness
worlds, keys are sorted alphabetically. `relevant_unknowns` is sorted. For the same rules, goal and
evidence the document is identical from run to run. (Witness worlds can change if you pass a
different `variable_order` to the engine; everything else cannot.)

The text produced by `to_json()` uses the standard `json.dumps` layout (`", "` and `": "`
separators, ASCII-escaped). Pass `indent=2` for a readable form, or other `json.dumps` keyword
arguments as needed.

## Reading and writing results

`CertificationResult.from_dict(d)` rebuilds a result from the dictionary form, and
`CertificationResult.from_dict(r.to_dict()) == r` always holds. A missing `schema_version` is
treated as `"1"`; any other value, a missing required key, an invalid `status` or a
non-boolean fact raises `EvidenceError`.

```python
import json
from askcert import CertificationResult, EvidenceError

text = engine.certify("eligible", evidence).to_json()
restored = CertificationResult.from_dict(json.loads(text))
print(restored.status, restored.relevant_unknowns, restored.witnesses.true_world["on_waiver"])

try:
    CertificationResult.from_dict({"schema_version": "2", "goal": "g", "status": "TRUE"})
except EvidenceError as exc:
    print(exc)
```

```text
UNKNOWN ('income_ok', 'on_waiver') True
unsupported schema_version '2'
```

Consumers in other languages should check `schema_version`, then read the fields in the table. If
the layout ever changes incompatibly, `schema_version` changes and the change is listed in the
[changelog](https://github.com/loc110504/askcert/blob/main/CHANGELOG.md).

## Other JSON documents

The command line prints three other small documents, described in [cli.md](cli.md):

- `askcert evaluate`: `{"schema_version": "1", "goal": ..., "status": ...}`
- `askcert validate`: `{"valid": true, "schema_version": "1", "rules": [...], "atoms": [...]}`
- errors on stderr: `{"error": {"type": ..., "message": ...}}`
