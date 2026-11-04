# Rule format

Rules are plain data: a JSON document, or the equivalent Python `dict`. They are parsed and
validated, never executed. This page describes the format (schema version `"1"`), the three ways
to write a rule set, and the errors you get for invalid input.

Code blocks on this page are complete and runnable, and the output shown is what they print.

## Contents

- [Document form](#document-form)
- [Expressions](#expressions)
- [Names, atoms and rules](#names-atoms-and-rules)
- [Strict mode: declared atoms](#strict-mode-declared-atoms)
- [Shorthand form](#shorthand-form)
- [Flat list form](#flat-list-form)
- [Loading and saving](#loading-and-saving)
- [Validation errors](#validation-errors)

## Document form

```json
{
  "schema_version": "1",
  "atoms": ["is_adult", "is_banned"],
  "rules": {
    "eligible": {"all": ["is_adult", {"not": "is_banned"}]}
  }
}
```

| Key | Required | Meaning |
|---|---|---|
| `rules` | yes | Either a mapping `name -> expression` or the [flat list](#flat-list-form). |
| `schema_version` | no | If present it must be the string `"1"`. |
| `atoms` | no | List of declared base atoms. If present the rule set is [strict](#strict-mode-declared-atoms). |

Any other top-level key is an error. A document that has no `rules` key is read as the
[shorthand form](#shorthand-form).

## Expressions

An expression is one of the following.

| JSON | Meaning |
|---|---|
| `true`, `false` | Constant. Only JSON booleans; the numbers `0` and `1` are rejected. |
| `"name"` | Reference to a rule or a base atom. |
| `"!name"` | Classical negation of a reference. Same as `{"not": "name"}`. |
| `{"not": e}` | Negation of one expression. |
| `{"all": [e, ...]}` | Conjunction. The empty list is TRUE. |
| `{"any": [e, ...]}` | Disjunction. The empty list is FALSE. |
| `{"xor": [e, ...]}` | True when an odd number of operands are true. The empty list is FALSE. |
| `{"implies": [e1, e2]}` | `not e1 or e2`. Exactly two operands. |
| `{"all": [...], "unless": [e, ...]}` | `all(...) and not any(unless)`. |
| `{"any": [...], "unless": [e, ...]}` | `any(...) and not any(unless)`. |

Each object has exactly one operator key (`not`, `all`, `any`, `xor`, `implies`), plus an optional
`unless` next to `all` or `any`. An empty `unless` list means no exception. Expressions nest up to
256 levels deep.

Semantics of the operators under missing information follows
[completion semantics](semantics.md): an operator does not "propagate unknown". The rule
`{"any": ["x", {"not": "x"}]}` is TRUE even when `x` is unknown.

The table below is the behaviour for two atoms. Each row is computed by the code that follows.

```python
from askcert import AskCert

engine = AskCert(
    {
        "and_": {"all": ["a", "b"]},
        "or_": {"any": ["a", "b"]},
        "not_": {"not": "a"},
        "xor_": {"xor": ["a", "b"]},
        "implies_": {"implies": ["a", "b"]},
        "unless_": {"any": ["a"], "unless": ["b"]},
    }
)
rows = [{}, {"a": True}, {"a": False}, {"a": True, "b": True}, {"a": False, "b": False}]
goals = list(engine.rules.rules)
print("evidence", *goals, sep=" | ")
for evidence in rows:
    cells = [str(engine.evaluate(goal, evidence)) for goal in goals]
    print(evidence, *cells, sep=" | ")
```

```text
evidence | and_ | or_ | not_ | xor_ | implies_ | unless_
{} | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN
{'a': True} | UNKNOWN | TRUE | FALSE | UNKNOWN | UNKNOWN | UNKNOWN
{'a': False} | FALSE | UNKNOWN | TRUE | UNKNOWN | TRUE | FALSE
{'a': True, 'b': True} | TRUE | TRUE | FALSE | FALSE | TRUE | FALSE
{'a': False, 'b': False} | FALSE | FALSE | TRUE | FALSE | TRUE | FALSE
```

(`not_` does not mention `b`, so evidence for `b` is ignored for it.)

### `unless`

`unless` is the exception mechanism. A rule fires when its core holds and none of its exceptions
hold. An exception that is unknown is not assumed false:

```python
from askcert import AskCert

engine = AskCert(
    {
        "refund": {"all": ["within_30_days", "item_returned"], "unless": ["final_sale"]},
    }
)
r = engine.certify("refund", {"within_30_days": True, "item_returned": True})
print(r.status, r.relevant_unknowns)
r = engine.certify("refund", {"within_30_days": True, "item_returned": True, "final_sale": False})
print(r.status, dict(r.certificate))
r = engine.certify("refund", {"final_sale": True})
print(r.status, dict(r.certificate))
```

```text
UNKNOWN ('final_sale',)
TRUE {'final_sale': False, 'item_returned': True, 'within_30_days': True}
FALSE {'final_sale': True}
```

## Names, atoms and rules

- A name matches `[A-Za-z_][A-Za-z0-9_]*`: ASCII letters, digits and underscores, not starting
  with a digit. For references, one leading `!` is allowed and means negation.
- `rules`, `atoms` and `schema_version` are reserved and cannot be rule or atom names.
- A name that is a key of `rules` is a *rule*. Any other referenced name is a *base atom*.
- Rules may refer to other rules. Rule references must not form a cycle.
- Evidence can only assign base atoms. Assigning a rule is an error (`EvidenceError`).
- A goal is a rule name or a base atom.

```python
from askcert import AskCert

engine = AskCert(
    {
        "academic_ok": {"all": ["enrolled", "gpa_ok"]},
        "eligible": {"all": ["academic_ok", "resident"]},
    }
)
print(engine.rules.atoms)
print(engine.rules.cone("eligible"))
print(engine.evaluate("eligible", {"enrolled": True, "gpa_ok": False}))
print(engine.evaluate("enrolled", {"enrolled": True}))  # an atom can be a goal
```

```text
('enrolled', 'gpa_ok', 'resident')
('enrolled', 'gpa_ok', 'resident')
FALSE
TRUE
```

## Strict mode: declared atoms

If the document lists `atoms`, every referenced name must be either a rule or a declared atom.
This catches typos, which are otherwise silently read as new atoms (and therefore as unknown
facts). Declared atoms that no rule uses are allowed and can be given evidence.

```python
from askcert import RuleError, RuleSet

try:
    RuleSet.from_dict(
        {
            "atoms": ["is_adult", "is_banned"],
            "rules": {"eligible": {"all": ["is_adult", {"not": "is_bannd"}]}},  # typo
        }
    )
except RuleError as exc:
    print(exc)
```

```text
undefined reference 'is_bannd' in rule 'eligible'
```

For rule sets you maintain by hand, declare the atoms.

## Shorthand form

A top-level mapping without a `rules` key is itself the rules mapping. It is the quickest way to
write a rule set in code. It cannot carry `atoms` or `schema_version`.

```python
from askcert import RuleSet

doc = RuleSet.from_dict({"schema_version": "1", "rules": {"eligible": {"all": ["is_adult", "!is_banned"]}}})
short = RuleSet.from_dict({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(doc == short)
```

```text
True
```

## Flat list form

`rules` may be a list of entries with the fields `name`, `op`, `conditions` and `exceptions`:

```json
{
  "rules": [
    {"name": "eligible", "op": "ANY",
     "conditions": ["resident", "valid_visa"], "exceptions": ["restricted"]}
  ]
}
```

| Field | Meaning |
|---|---|
| `name` | Rule name. `p` is accepted as an alias (giving both is an error). |
| `op` | `"ALL"` or `"ANY"`. Default `"ANY"`. |
| `conditions` | List of strings (names, or `"!name"`). Default `[]`. |
| `exceptions` | List of strings. Default `[]`. |

An entry means `op(conditions) and not any(exceptions)`, exactly as `{"all"|"any": conditions,
"unless": exceptions}`. Rule names must be unique. Entries may only use the five keys above.

This is the layout used by the rule-programs of [PYTHEN](https://github.com/nguyenthanhasia/pythen),
so a flat rule list written for that library loads unchanged:

```python
from askcert import AskCert, RuleSet

flat = RuleSet.from_dict(
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
print(flat.to_dict())
print(AskCert(flat).evaluate("eligible", {"resident": True, "restricted": False}))
```

```text
{'schema_version': '1', 'rules': {'eligible': {'any': ['resident', 'valid_visa'], 'unless': ['restricted']}}}
TRUE
```

The loaded rules have AskCert semantics, which differ from closed-world evaluation when evidence
is missing. A fact that is not supplied is unknown, not false:

```python
from askcert import AskCert, RuleSet

engine = AskCert(
    RuleSet.from_dict(
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
)
r = engine.certify("eligible", {"resident": True})
print(r.status, r.relevant_unknowns)
```

```text
UNKNOWN ('restricted',)
```

A closed-world evaluator reads the missing `restricted` as false and answers TRUE here. AskCert
reports that the answer depends on `restricted`.

## Loading and saving

| Method | Use |
|---|---|
| `RuleSet.from_dict(spec)` | Document, shorthand or flat list as a Python mapping. |
| `RuleSet.from_json(text)` | Same, from JSON text. Duplicate object keys are an error. |
| `RuleSet.load(path)` | Read a UTF-8 JSON file (a byte-order mark is tolerated). |
| `rs.to_dict()`, `rs.to_json(**kw)` | Canonical form. `RuleSet.from_dict(rs.to_dict()) == rs`. |

The canonical form always uses `{"not": e}` (never `"!name"`), lists for operands, an `unless` key
only when it is non-empty, and bare strings for references. The `atoms` key is written only if
atoms were declared.

```python
from askcert import RuleSet

rs = RuleSet.from_json('{"eligible": {"all": ["is_adult", "!is_banned"], "unless": []}}')
print(rs.to_json())
print(RuleSet.from_json(rs.to_json()) == rs)
```

```text
{"schema_version": "1", "rules": {"eligible": {"all": ["is_adult", {"not": "is_banned"}]}}}
True
```

## Validation errors

Every problem with a rule document raises `askcert.RuleError` (a subclass of `ValueError`). The
messages name the rule and the cause:

```python
from askcert import RuleError, RuleSet

bad = {
    "cycle": {"a": {"all": ["b"]}, "b": {"any": ["a"]}},
    "undefined (strict)": {"atoms": ["x"], "rules": {"a": "y"}},
    "unknown key": {"a": {"all": ["x"], "foo": 1}},
    "wrong arity": {"a": {"implies": ["x"]}},
    "unless on xor": {"a": {"xor": ["x"], "unless": ["y"]}},
    "integer constant": {"a": 1},
    "bad name": {"a": "x y"},
    "reserved name": {"rules": {"atoms": "x"}},
    "bad schema_version": {"schema_version": 2, "rules": {"a": "x"}},
    "unknown top key": {"rules": {"a": "x"}, "extra": 1},
    "duplicate flat": {"rules": [{"name": "a"}, {"p": "a"}]},
}
for label, spec in bad.items():
    try:
        RuleSet.from_dict(spec)
    except RuleError as exc:
        print(f"{label}: {exc}")
try:
    RuleSet.from_json('{"a": "x", "a": "y"}')
except RuleError as exc:
    print(f"duplicate key: {exc}")
```

```text
cycle: Cycle detected among rules (cycle: a -> b -> a)
undefined (strict): undefined reference 'y' in rule 'a'
unknown key: rule 'a': unknown key 'foo'
wrong arity: rule 'a': 'implies' takes exactly 2 operands, got 1
unless on xor: rule 'a': 'unless' is only allowed with 'all' or 'any'
integer constant: rule 'a': invalid expression 1 (expected bool, string or operator object)
bad name: rule 'a': invalid reference 'x y': must match [A-Za-z_][A-Za-z0-9_]*
reserved name: invalid rule name 'atoms': reserved word
bad schema_version: unsupported schema_version 2; expected '1'
unknown top key: unknown top-level key 'extra'
duplicate flat: Duplicate rule name 'a'
duplicate key: duplicate key 'a' in JSON rules
```

Asking for a goal that does not exist is also a `RuleError`; providing evidence for a name that is
not a base atom is an `EvidenceError`. See [api.md](api.md#exceptions).
