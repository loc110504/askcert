# Command-line interface

The `askcert` command certifies goals from JSON files. It is installed with the package and can
also be started as `python -m askcert`. It needs no configuration and reads files as UTF-8.

The examples on this page use the files in
[`examples/data/`](../examples/data/) and are run from the repository root. The command blocks show real
output. (Line wrapping in the `--help` output depends on the terminal width; the blocks below
use 80 columns.)

## Contents

- [Synopsis](#synopsis)
- [`certify`](#certify)
- [`evaluate`](#evaluate)
- [`batch`](#batch)
- [`validate`](#validate)
- [Reading from standard input](#reading-from-standard-input)
- [Exit codes and errors](#exit-codes-and-errors)
- [Using the CLI from scripts](#using-the-cli-from-scripts)

## Synopsis

```console
$ askcert --help
usage: askcert [-h] [--version] COMMAND ...

Certifiable Boolean reasoning under incomplete evidence.

Decide a goal as TRUE, FALSE or UNKNOWN over every completion of the missing
facts, with a subset-minimal certificate, the relevant unknowns and witnesses.

positional arguments:
  COMMAND
    certify   Decide one goal and print the full certification result as JSON.
    evaluate  Decide one goal and print only its status.
    batch     Certify one goal for many evidence objects (JSON Lines in, JSON
              Lines out).
    validate  Check a rule set and list its rules and atoms.

options:
  -h, --help  show this help message and exit
  --version   show program's version number and exit

exit codes:
  0  success (the status may be TRUE, FALSE or UNKNOWN)
  2  invalid input or usage (bad rules, evidence, JSON, file, or command line)
  3  resource limit exceeded (--max-nodes / --timeout / recursion); no answer was computed

Errors are printed to stderr as {"error": {"type": ..., "message": ...}}.
$ askcert --version
askcert 0.1.0
```

| Command | Purpose |
|---|---|
| `askcert certify` | Decide one goal and print the full [result document](results.md). |
| `askcert evaluate` | Decide one goal and print only its status. |
| `askcert batch` | Certify one goal for many evidence objects: JSON Lines in, JSON Lines out. |
| `askcert validate` | Check a rule file and list its rules and atoms. |

All commands except `validate` share these options:

| Option | Meaning |
|---|---|
| `--rules RULES.json` | Required. Rule set in any [rule format](rule-format.md); duplicate JSON keys are rejected. |
| `--goal GOAL` | Required. A rule name or base atom. |
| `--max-nodes N` | Decision-diagram node limit, an integer of at least 2. Default 1,000,000. |
| `--timeout SECONDS` | Time limit per run, a positive number. Default: none. |

The files used below are the fictional scholarship rules from `examples/data/`:

```json
{
  "schema_version": "1",
  "atoms": ["enrolled", "gpa_ok", "income_ok", "on_waiver", "resident", "has_sanction"],
  "rules": {
    "academic_ok": {"all": ["enrolled", "gpa_ok"]},
    "financial_ok": {"any": ["income_ok", "on_waiver"]},
    "eligible": {"all": ["academic_ok", "financial_ok", "resident"], "unless": ["has_sanction"]}
  }
}
```

## `certify`

```text
askcert certify --rules RULES.json --goal GOAL [--evidence EVIDENCE.json]
                [--no-witnesses] [--max-nodes N] [--timeout SECONDS] [--indent N]
```

Prints the [result document](results.md) for one goal and one evidence object. Without
`--evidence` the evidence is empty (everything unknown).

```console
$ askcert certify --rules examples/data/eligibility_rules.json --goal eligible --evidence examples/data/eligibility_evidence.json
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

| Option | Meaning |
|---|---|
| `--evidence EVIDENCE.json` | A JSON object mapping atom names to `true`, `false` or `null`. `-` reads standard input. |
| `--no-witnesses` | Leave `witnesses` as `null` for UNKNOWN goals (faster, smaller). |
| `--indent N` | JSON indentation, default 2. `0` prints one line. |

`UNKNOWN` is a normal answer and exits with code 0.

```console
$ echo '{"enrolled": false}' | askcert certify --rules examples/data/eligibility_rules.json --goal eligible --evidence - --indent 0
{"schema_version": "1", "goal": "eligible", "status": "FALSE", "evidence": {"enrolled": false}, "certificate": {"enrolled": false}, "relevant_unknowns": [], "witnesses": null}
```

## `evaluate`

```text
askcert evaluate --rules RULES.json --goal GOAL [--evidence EVIDENCE.json]
                 [--max-nodes N] [--timeout SECONDS]
```

Prints only the status, as `{"schema_version", "goal", "status"}`.

```console
$ askcert evaluate --rules examples/data/eligibility_rules.json --goal eligible --evidence examples/data/eligibility_evidence.json
{"schema_version": "1", "goal": "eligible", "status": "UNKNOWN"}
```

## `batch`

```text
askcert batch --rules RULES.json --goal GOAL --cases CASES.jsonl
              [--no-witnesses] [--max-nodes N] [--timeout SECONDS]
```

Certifies one goal for many evidence objects with a single compiled engine. The cases file is
JSON Lines: one evidence object per line, blank lines skipped, `-` for standard input. Output is
one compact result document per line, in input order.

```console
$ askcert batch --rules examples/data/eligibility_rules.json --goal eligible --cases examples/data/cases.jsonl --no-witnesses
{"schema_version":"1","goal":"eligible","status":"TRUE","evidence":{"enrolled":true,"gpa_ok":true,"has_sanction":false,"income_ok":true,"resident":true},"certificate":{"enrolled":true,"gpa_ok":true,"has_sanction":false,"income_ok":true,"resident":true},"relevant_unknowns":[],"witnesses":null}
{"schema_version":"1","goal":"eligible","status":"UNKNOWN","evidence":{"enrolled":true,"gpa_ok":true,"has_sanction":false,"resident":true},"certificate":null,"relevant_unknowns":["income_ok","on_waiver"],"witnesses":null}
{"schema_version":"1","goal":"eligible","status":"UNKNOWN","evidence":{"enrolled":true,"gpa_ok":true,"on_waiver":true,"resident":true},"certificate":null,"relevant_unknowns":["has_sanction"],"witnesses":null}
{"schema_version":"1","goal":"eligible","status":"FALSE","evidence":{"enrolled":false},"certificate":{"enrolled":false},"relevant_unknowns":[],"witnesses":null}
{"schema_version":"1","goal":"eligible","status":"FALSE","evidence":{"enrolled":true,"gpa_ok":true,"has_sanction":true,"income_ok":true,"resident":true},"certificate":{"has_sanction":true},"relevant_unknowns":[],"witnesses":null}
{"schema_version":"1","goal":"eligible","status":"UNKNOWN","evidence":{},"certificate":null,"relevant_unknowns":["enrolled","gpa_ok","has_sanction","income_ok","on_waiver","resident"],"witnesses":null}
```

The cases are read and certified first, and the output is printed only if every line is valid.
A bad line (invalid JSON, not an object, an unknown atom, a non-boolean value) prints nothing to
standard output, exits with code 2 and names the line number in the error message:

```console
$ printf '{"enrolled": true}\n{"enrolled": 1}\n' | askcert batch --rules examples/data/eligibility_rules.json --goal eligible --cases - 2>&1; echo "exit code: $?"
{"error": {"type": "EvidenceError", "message": "<stdin>, line 2: evidence value for 'enrolled' must be True, False or None, got 1"}}
exit code: 2
```

## `validate`

```text
askcert validate --rules RULES.json
```

Checks that the file is a valid rule set. It prints the rule names in definition order and the
sorted base atoms.

```console
$ askcert validate --rules examples/data/eligibility_rules.json
{"valid": true, "schema_version": "1", "rules": ["academic_ok", "financial_ok", "eligible"], "atoms": ["enrolled", "gpa_ok", "has_sanction", "income_ok", "on_waiver", "resident"]}
```

An invalid file exits with code 2 and reports the problem (see below). Use `validate` as a check
in continuous integration for rule files kept in version control.

## Reading from standard input

`--evidence -` and `--cases -` read standard input, which allows pipelines. Standard input can be
read once, so only one input of a run can come from it.

```console
$ echo '{"enrolled": true, "gpa_ok": true, "income_ok": true, "resident": true}' | askcert evaluate --rules examples/data/eligibility_rules.json --goal eligible --evidence -
{"schema_version": "1", "goal": "eligible", "status": "UNKNOWN"}
```

(`has_sanction` is still unknown, so the scholarship is not decided yet.)

## Exit codes and errors

| Code | Meaning |
|---|---|
| 0 | Success. The status can be `TRUE`, `FALSE` or `UNKNOWN`. |
| 2 | Invalid input or usage: bad rules, bad evidence, unreadable file, malformed JSON, a bad line in a batch, or a bad command line. |
| 3 | A resource limit was exceeded (`--max-nodes`, `--timeout`, or the recursion limit). **No answer was computed.** This is not the same as UNKNOWN. |

On failure, standard output stays empty and a single JSON object is written to standard error. No
traceback is printed for expected errors. For exit code 3 the object also carries `limit` and
`value`.

```console
$ askcert evaluate --rules examples/data/eligibility_rules.json --goal nope 2>&1; echo "exit code: $?"
{"error": {"type": "RuleError", "message": "unknown goal 'nope'"}}
exit code: 2
$ echo '{"typo": true}' | askcert evaluate --rules examples/data/eligibility_rules.json --goal eligible --evidence - 2>&1; echo "exit code: $?"
{"error": {"type": "EvidenceError", "message": "unknown atom 'typo'"}}
exit code: 2
$ askcert certify --rules missing.json --goal eligible 2>&1; echo "exit code: $?"
{"error": {"type": "RuleError", "message": "cannot read 'missing.json': [Errno 2] No such file or directory: 'missing.json'"}}
exit code: 2
$ askcert certify --rules examples/data/eligibility_rules.json 2>&1; echo "exit code: $?"
{"error": {"type": "UsageError", "message": "the following arguments are required: --goal (see 'askcert certify --help')"}}
exit code: 2
$ askcert certify --rules examples/data/eligibility_rules.json --goal eligible --max-nodes 3 2>&1; echo "exit code: $?"
{"error": {"type": "ResourceLimitExceeded", "message": "resource limit exceeded: max_nodes (limit value 3)", "limit": "max_nodes", "value": 3}}
exit code: 3
```

The `type` field is the name of the exception class in [api.md](api.md#exceptions) (`RuleError`,
`EvidenceError`, `ResourceLimitExceeded`), or `UsageError` for a bad command line.

## Using the CLI from scripts

- Branch on the exit code, then parse standard output as JSON. A script that sees exit code 0 can
  rely on `status` being one of the three values.
- Treat exit code 3 as "could not decide", not as UNKNOWN. Retry with a larger `--max-nodes` or
  `--timeout`, or report the failure.
- In shell, `status` can be read without extra tools by using `evaluate` and a JSON-aware tool of
  your choice (`jq`, `python -c`). The output layout is fixed: see [results.md](results.md).
- For many cases, prefer one `batch` run to many `certify` runs: the rules are parsed and compiled
  once.
- From Python, the same functionality is available without a subprocess:
  [`AskCert.certify_many`](api.md#certify_many).
