# API reference

Everything in `askcert.__all__` is public API. This page lists each symbol with its signature,
semantics, the exceptions it raises and a small example. Code blocks are complete and runnable, and
the output shown is what they print.

```python
import askcert

print(askcert.__version__)
print(sorted(askcert.__all__))
```

```text
0.1.0
['AskCert', 'AskCertError', 'CertificationResult', 'Decision', 'EvidenceError', 'ObservationConflictError', 'Question', 'Reasoner', 'ResourceLimitExceeded', 'Rule', 'RuleError', 'RuleSet', 'Status', 'Witnesses', '__version__', 'compile_rules']
```

## Contents

- Engine: [`AskCert`](#askcert) · [`compile_rules`](#compile_rules)
- Rules: [`RuleSet`](#ruleset) · [expression nodes](#expression-nodes-askcertrules)
- Results: [`Status`](#status) · [`CertificationResult`](#certificationresult) · [`Witnesses`](#witnesses)
- [Exceptions](#exceptions)
- [Session API](#session-api): `Reasoner`, `Rule`, `Decision`, `Question`
- [Evidence rules](#evidence-rules) · [`__version__`](#__version__)

## `AskCert`

<!-- no-run -->
```python
class AskCert:
    def __init__(
        self,
        rules: RuleSet | Mapping,
        *,
        max_nodes: int = 1_000_000,
        timeout: float | None = None,
        variable_order: Sequence[str] | None = None,
    ): ...
```

The engine. It validates a rule set, compiles goals into a decision diagram on first use and
answers certified queries. Create one engine per rule set and reuse it.

| Parameter | Meaning |
|---|---|
| `rules` | A [`RuleSet`](#ruleset), or anything `RuleSet.from_dict` accepts (document, shorthand or flat list). |
| `max_nodes` | Upper bound on the number of diagram nodes, an integer of at least 2 (the two terminals count). Exceeding it raises `ResourceLimitExceeded("max_nodes")`. |
| `timeout` | Seconds allowed per public call, a positive number or `None` (no limit). A batch call such as `certify_many` counts as one call. Exceeding it raises `ResourceLimitExceeded("timeout")`. |
| `variable_order` | Optional permutation of `rules.atoms`, root-most first. Affects diagram size and which witness worlds are returned. It never changes statuses, certificates or relevant unknowns. Default: sorted atom names. |

Raises `RuleError` for an invalid rule set and `ValueError` for an invalid `max_nodes`,
`timeout` or `variable_order`.

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(engine.rules.atoms)
```

```text
('is_adult', 'is_banned')
```

Properties:

- `engine.rules` is the immutable `RuleSet`.
- `engine.node_count` is the number of live diagram nodes. Queries do not change it. Compiling a
  goal for the first time does.

Guarantees:

- **No state leakage.** Every query leaves the engine as it found it. Temporary nodes created
  while restricting the diagram are rolled back, so memory does not grow with the number of
  queries and `certify_many` runs in bounded memory.
- **Compiled goals are cached** across calls.
- **Not thread-safe.** Use one engine per thread, or guard calls with a lock.

All query methods take the evidence as `Mapping[str, bool | None]` (or `None` for no evidence).
See [Evidence rules](#evidence-rules). Unknown goals raise `RuleError`.

### `evaluate`

<!-- no-run -->
```python
def evaluate(self, goal: str, evidence: Mapping[str, bool | None] | None = None) -> Status
```

The status of `goal` under completion semantics. The cheapest query: it does not build a
certificate or witnesses.

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(engine.evaluate("eligible"))
print(engine.evaluate("eligible", {"is_adult": False}))
```

```text
UNKNOWN
FALSE
```

### `certify`

<!-- no-run -->
```python
def certify(self, goal: str, evidence=None, *, witnesses: bool = True) -> CertificationResult
```

Status plus the supporting information: a subset-minimal certificate if the goal is decided; the
relevant unknowns and (unless `witnesses=False`) a pair of witness worlds if it is UNKNOWN. See
[`CertificationResult`](#certificationresult).

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
r = engine.certify("eligible", {"is_adult": True})
print(r.status, r.relevant_unknowns, r.certificate)
r = engine.certify("eligible", {"is_adult": True, "is_banned": False})
print(r.status, dict(r.certificate), r.relevant_unknowns)
```

```text
UNKNOWN ('is_banned',) None
TRUE {'is_adult': True, 'is_banned': False} ()
```

### `find_certificate`, `find_relevant_unknowns`, `find_witnesses`

<!-- no-run -->
```python
def find_certificate(self, goal, evidence=None) -> dict[str, bool] | None
def find_relevant_unknowns(self, goal, evidence=None) -> tuple[str, ...]
def find_witnesses(self, goal, evidence=None) -> Witnesses | None
```

Single-purpose shortcuts over `certify`.

| Method | Returns | When |
|---|---|---|
| `find_certificate` | The certificate as a plain `dict` (possibly `{}`) | `None` iff the goal is UNKNOWN |
| `find_relevant_unknowns` | Sorted tuple of atom names | `()` iff the goal is decided |
| `find_witnesses` | `Witnesses` | `None` iff the goal is decided |

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(engine.find_certificate("eligible", {"is_adult": False}))
print(engine.find_certificate("eligible", {"is_adult": True}))
print(engine.find_relevant_unknowns("eligible", {"is_adult": True}))
print(engine.find_witnesses("eligible", {"is_adult": False}))
```

```text
{'is_adult': False}
None
('is_banned',)
None
```

### `certify_many`

<!-- no-run -->
```python
def certify_many(self, goal, evidences: Iterable[Mapping | None], *, witnesses: bool = True) -> list[CertificationResult]
```

`certify` for each evidence mapping, in order, on one compiled engine with bounded working memory.
`evidences` may be any iterable, including a generator. The call counts as one call for `timeout`.
If any item is invalid the call raises and returns nothing.

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
cases = ({"is_adult": True, "is_banned": b} for b in (False, True))
for r in engine.certify_many("eligible", cases, witnesses=False):
    print(r.status)
```

```text
TRUE
FALSE
```

### `compile`

<!-- no-run -->
```python
def compile(self, *goals: str) -> AskCert
```

Compiles the given goals (every rule when none are given) ahead of time and returns the engine.
Use it to pay the compile cost at start-up and to make the first query fast. Raises
`ResourceLimitExceeded` if a limit is hit; the engine is then left as it was.

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}}).compile()
before = engine.node_count
engine.certify("eligible", {"is_adult": True})
print(engine.node_count == before)
```

```text
True
```

## `compile_rules`

<!-- no-run -->
```python
def compile_rules(spec: RuleSet | Mapping, *, goals: Iterable[str] | None = None, **engine_kwargs) -> AskCert
```

Shorthand for `AskCert(spec, **engine_kwargs).compile(*goals)`. With `goals=None`, every rule is
compiled. `engine_kwargs` are `max_nodes`, `timeout` and `variable_order`.

```python
from askcert import compile_rules

engine = compile_rules({"a": {"all": ["x", "y"]}, "b": {"any": ["x", "z"]}}, goals=["a"], max_nodes=1000)
print(engine.evaluate("a", {"x": False}))
```

```text
FALSE
```

## `RuleSet`

<!-- no-run -->
```python
class RuleSet:
    def __init__(self, rules: Mapping[str, Expr | dict | str | bool], atoms: Iterable[str] | None = None): ...
```

A validated, immutable, hashable rule set. The constructor takes a mapping `name -> expression`
(expression nodes or the JSON forms) and optional declared atoms. The usual way to build one is
from a document:

| Member | Description |
|---|---|
| `RuleSet.from_dict(spec)` | Build from a document, shorthand or flat-list mapping. |
| `RuleSet.from_json(text)` | Same, from JSON text; duplicate keys raise `RuleError`. |
| `RuleSet.load(path)` | Read a UTF-8 JSON file. |
| `rs.rules` | Read-only `Mapping[str, Expr]` of the rules in definition order. |
| `rs.atoms` | Sorted tuple of all base atoms (declared plus referenced). |
| `rs.declared_atoms` | Sorted tuple of declared atoms, or `None` when not strict. |
| `rs.cone(goal)` | Sorted tuple of base atoms reachable from `goal`. |
| `rs.to_dict()`, `rs.to_json(**kw)` | Canonical document. `RuleSet.from_dict(rs.to_dict()) == rs`. |

Equality is on `(rules, declared_atoms)`. All errors are `RuleError`: invalid names, reserved
names, cycles, undefined references in strict mode, malformed expressions, unknown goals (in
`cone`). Details and examples: [rule-format.md](rule-format.md).

```python
from askcert import RuleSet

rs = RuleSet.from_dict(
    {"academic_ok": {"all": ["enrolled", "gpa_ok"]}, "eligible": {"all": ["academic_ok", "resident"]}}
)
print(rs)
print(rs.cone("academic_ok"))
print(list(rs.rules))
```

```text
RuleSet(rules=['academic_ok', 'eligible'], atoms=['enrolled', 'gpa_ok', 'resident'])
('enrolled', 'gpa_ok')
['academic_ok', 'eligible']
```

### Expression nodes (`askcert.rules`)

The parsed form of a rule is an immutable, hashable tree of dataclasses with structural equality.
You can build rule sets from them instead of dictionaries.

| Node | Fields | Meaning |
|---|---|---|
| `Const` | `value: bool` | Constant. |
| `Ref` | `name: str` | Rule or atom reference. |
| `Not` | `arg` | Negation. |
| `All` | `args`, `unless=()` | Conjunction, and not any `unless`. |
| `Any` | `args`, `unless=()` | Disjunction, and not any `unless`. |
| `Xor` | `args` | Odd parity. |
| `Implies` | `left`, `right` | `not left or right`. |

`askcert.rules.Expr` is the union of these types. Construction validates the fields and raises
`RuleError`. (`Any` here is a node class and has nothing to do with `typing.Any`.)

```python
from askcert import AskCert
from askcert.rules import All, Not, Ref, RuleSet

rs = RuleSet({"eligible": All((Ref("is_adult"), Not(Ref("is_banned"))))})
print(rs.to_dict()["rules"])
print(AskCert(rs).evaluate("eligible", {"is_adult": True, "is_banned": False}))
```

```text
{'eligible': {'all': ['is_adult', {'not': 'is_banned'}]}}
TRUE
```

## `Status`

<!-- no-run -->
```python
class Status(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"
```

The outcome of a decision. A `str` enum, so `Status.TRUE == "TRUE"`, `str(Status.TRUE) == "TRUE"`
and it serialises to JSON as a plain string.

```python
from askcert import Status

print(Status.TRUE == "TRUE", str(Status.UNKNOWN), Status("FALSE") is Status.FALSE)
```

```text
True UNKNOWN True
```

## `CertificationResult`

<!-- no-run -->
```python
@dataclass(frozen=True)
class CertificationResult:
    goal: str
    status: Status
    evidence: Mapping[str, bool]
    certificate: Mapping[str, bool] | None
    relevant_unknowns: tuple[str, ...]
    witnesses: Witnesses | None
```

The immutable outcome of certifying one goal against one body of evidence. Mappings are read-only
and sorted by key. Instances compare by value and can be pickled; they are not hashable (they hold mappings), so do not use them as dictionary keys or set members.

| Field | Meaning |
|---|---|
| `goal` | The goal as given. |
| `status` | `Status.TRUE`, `FALSE` or `UNKNOWN`. |
| `evidence` | The known facts supplied (entries with value `None` dropped). This includes facts outside the goal's cone. |
| `certificate` | Subset-minimal sufficient facts, restricted to the goal's cone. `None` iff UNKNOWN. Can be `{}`. |
| `relevant_unknowns` | Unknown atoms that can still change the outcome, sorted. `()` iff decided. |
| `witnesses` | A `Witnesses` pair. `None` if decided **or** if `witnesses=False` was passed. |

Members:

- `decided` (property): `True` iff the status is TRUE or FALSE.
- `to_dict()`: JSON-compatible dictionary, schema version 1. See [results.md](results.md).
- `to_json(**json_kwargs)`: the same as JSON text. `json_kwargs` go to `json.dumps`
  (`NaN` and `Infinity` are refused unless you override `allow_nan`).
- `CertificationResult.from_dict(d)`: inverse of `to_dict`. Malformed input raises `EvidenceError`.
  `CertificationResult.from_dict(r.to_dict()) == r` always holds.

```python
from askcert import AskCert, CertificationResult

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
r = engine.certify("eligible", {"is_adult": True})
print(r.decided)
print(r.to_json())
print(CertificationResult.from_dict(r.to_dict()) == r)
```

```text
False
{"schema_version": "1", "goal": "eligible", "status": "UNKNOWN", "evidence": {"is_adult": true}, "certificate": null, "relevant_unknowns": ["is_banned"], "witnesses": {"true": {"is_adult": true, "is_banned": false}, "false": {"is_adult": true, "is_banned": true}}}
True
```

## `Witnesses`

<!-- no-run -->
```python
@dataclass(frozen=True)
class Witnesses:
    true_world: Mapping[str, bool]
    false_world: Mapping[str, bool]
```

Two complete assignments over the goal's cone atoms. Both agree with the evidence; the goal is
true in `true_world` and false in `false_world`. The mappings are read-only and sorted.

- `to_dict()` returns `{"true": {...}, "false": {...}}`.
- `Witnesses.from_dict(d)` is the inverse; malformed input raises `EvidenceError`.

```python
from askcert import Witnesses

w = Witnesses({"a": True, "b": False}, {"a": False, "b": False})
print(w.to_dict())
print(Witnesses.from_dict(w.to_dict()) == w)
```

```text
{'true': {'a': True, 'b': False}, 'false': {'a': False, 'b': False}}
True
```

## Exceptions

All errors raised by AskCert derive from `AskCertError`.

```text
AskCertError
├── RuleError (also ValueError)
├── EvidenceError (also ValueError)
│   └── ObservationConflictError
└── ResourceLimitExceeded
```

| Exception | Raised for |
|---|---|
| `AskCertError` | Base class. `except AskCertError` catches every library error. |
| `RuleError` | Invalid rules, schema or goal: bad names, cycles, undefined references (strict mode), malformed expressions, unknown goal. |
| `EvidenceError` | Invalid evidence: not a mapping, unknown atom, assignment to a derived rule, non-boolean value; malformed serialized results. |
| `ObservationConflictError` | Session API: a known fact was re-observed with the opposite value without `replace=True`. |
| `ResourceLimitExceeded` | A computation hit a limit. Attributes: `limit` (`"max_nodes"`, `"timeout"` or `"recursion"`) and `value` (the bound). **Not** the same as UNKNOWN: nothing was decided. |

Invalid constructor arguments such as `timeout=0` raise a plain `ValueError`.

```python
from askcert import AskCert, AskCertError, EvidenceError, ResourceLimitExceeded, RuleError

rules = {"eligible": {"all": ["is_adult", {"not": "is_banned"}]}}
engine = AskCert(rules)

for call in (
    lambda: engine.evaluate("nope"),
    lambda: engine.evaluate("eligible", {"is_adult": "yes"}),
    lambda: AskCert(rules, max_nodes=2).evaluate("eligible"),
):
    try:
        call()
    except AskCertError as exc:
        print(type(exc).__name__, "|", exc)

try:
    AskCert(rules, timeout=1e-9).evaluate("eligible")
except ResourceLimitExceeded as exc:
    print(exc.limit, exc.value)
print(issubclass(RuleError, ValueError), issubclass(EvidenceError, ValueError))
```

```text
RuleError | unknown goal 'nope'
EvidenceError | evidence value for 'is_adult' must be True, False or None, got 'yes'
ResourceLimitExceeded | resource limit exceeded: max_nodes (limit value 2)
timeout 1e-09
True True
```

## Evidence rules

Evidence maps base-atom names to `True`, `False` or `None`.

- `None`, or absence from the mapping, means unknown. It is never read as false.
- The evidence argument itself may be `None` or omitted (no evidence). Any other non-mapping raises
  `EvidenceError`.
- Keys must be base atoms of the rule set. An unknown name raises `EvidenceError` ("unknown atom").
  A rule name raises `EvidenceError` ("cannot assign derived rule"): derived values are computed,
  not observed.
- Values must be exactly `bool` or `None`. The integers `0` and `1`, strings such as `"true"` and
  NumPy booleans are rejected.
- Evidence about atoms outside the goal's cone is accepted and ignored for that goal. It still
  appears in `CertificationResult.evidence`.

```python
from askcert import AskCert, EvidenceError

engine = AskCert(
    {"eligible": {"all": ["is_adult", {"not": "is_banned"}]}, "library": {"any": ["member", "staff"]}}
)
print(engine.certify("library", {"member": True, "is_adult": False}).evidence)
for bad in ({"typo": True}, {"eligible": True}, {"is_adult": 1}, [("is_adult", True)]):
    try:
        engine.evaluate("eligible", bad)
    except EvidenceError as exc:
        print(exc)
```

```text
{'is_adult': False, 'member': True}
unknown atom 'typo'
cannot assign derived rule 'eligible'; evidence must name base atoms
evidence value for 'is_adult' must be True, False or None, got 1
evidence must be a mapping, got list
```

## Session API

`Reasoner`, `Rule`, `Decision` and `Question` form a stateful, backward-compatible API: a
`Reasoner` holds a rule list and a mutable fact base and answers questions about the current
facts, including a ranked list of questions to ask next. It is built on `AskCert`; see the
docstrings in `askcert.session` for details.

## `__version__`

`askcert.__version__` is the installed version string (`"0.1.0"`). The command line prints it with
`askcert --version`.
