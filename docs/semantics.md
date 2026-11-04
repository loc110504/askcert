# Semantics

This page defines exactly what AskCert computes. The semantics is completion-based (supervaluation)
semantics for partial information, in the tradition of van Fraassen (1966): a statement is
settled when it has the same value under every way of completing the missing facts. The
definitions below are checked in the test suite against two independent oracles.

Code blocks on this page are complete and runnable, and the output shown is what they print.

## Contents

- [Rules, goals and cones](#rules-goals-and-cones)
- [Evidence and completions](#evidence-and-completions)
- [Decision status](#decision-status)
- [Supporting certificates](#supporting-certificates)
- [Relevant unknowns](#relevant-unknowns)
- [Witnesses](#witnesses)
- [Proposition 1: decision locality](#proposition-1-decision-locality)
- [How it is computed](#how-it-is-computed)
- [What is not supported](#what-is-not-supported)

## Rules, goals and cones

A *rule set* is a finite, acyclic collection of named Boolean rules over *base atoms*. A rule is
an expression built from atoms, constants, other rules and the operators `all`, `any`, `not`,
`xor`, `implies` and `unless` (see [rule-format.md](rule-format.md)).

A *goal* $g$ is a rule name or a base atom. Expanding every rule reference turns $g$ into a Boolean
function

$$f_g : \{0,1\}^{A_g} \to \{0,1\}$$

where $A_g$ is the set of base atoms reachable from $g$, called the *cone* of $g$. Atoms outside
the cone cannot influence $g$ and are ignored for that goal.

```python
from askcert import RuleSet

rules = RuleSet.from_dict(
    {
        "academic_ok": {"all": ["enrolled", "gpa_ok"]},
        "eligible": {"all": ["academic_ok", "resident"], "unless": ["has_sanction"]},
        "library_ok": {"any": ["enrolled", "staff"]},
    }
)
print(rules.cone("eligible"))
print(rules.cone("library_ok"))
```

```text
('enrolled', 'gpa_ok', 'has_sanction', 'resident')
('enrolled', 'staff')
```

## Evidence and completions

*Evidence* $K$ is a partial assignment of truth values to base atoms,
$K : A \rightharpoonup \{0,1\}$. An atom with a value is *known*. An atom without a value (absent
from the mapping, or mapped to `None`) is *unknown*. **Unknown is not false.**

The *completions* of $K$ are the complete assignments over the cone that agree with $K$:

$$\Omega(K) = \{\, w \in \{0,1\}^{A_g} : w(a) = K(a) \text{ for all } a \in \operatorname{dom}(K) \cap A_g \,\}$$

Defining $\Omega(K)$ over all atoms $A$ instead of the cone gives the same decisions, because
$f_g$ does not depend on atoms outside $A_g$.

## Decision status

Following completion-based semantics, the status of goal $g$ under evidence $K$ is

$$
\operatorname{Dec}(g,K) =
\begin{cases}
\text{TRUE}, & \text{if } f_g(w) = 1 \text{ for every } w \in \Omega(K),\\
\text{FALSE}, & \text{if } f_g(w) = 0 \text{ for every } w \in \Omega(K),\\
\text{UNKNOWN}, & \text{otherwise.}
\end{cases}
$$

A conclusion is decided only when its value is the same under every way of filling in the unknown
facts. UNKNOWN therefore has one meaning: *both outcomes are still possible*. It never means that
the computation failed. A computation that hits a resource limit raises
[`ResourceLimitExceeded`](api.md#exceptions) instead.

### Completion semantics is not Kleene logic

Strong Kleene three-valued logic evaluates an expression bottom-up and gives `UNKNOWN` to any
operation that touches an unknown input without being forced. AskCert instead asks about all
completions of the unknown atoms, so it recognises tautologies and contradictions:

```python
from askcert import AskCert

engine = AskCert(
    {
        "excluded_middle": {"any": ["x", {"not": "x"}]},
        "contradiction": {"all": ["x", {"not": "x"}]},
        "either_way": {"any": [{"all": ["a", "b"]}, {"all": ["a", {"not": "b"}]}]},
        "just_x": "x",
    }
)
for goal in ["excluded_middle", "contradiction", "either_way", "just_x"]:
    print(goal, engine.evaluate(goal, {"a": True}))
```

```text
excluded_middle TRUE
contradiction FALSE
either_way TRUE
just_x UNKNOWN
```

Here `x` and `b` are unknown. A bottom-up Kleene evaluation returns UNKNOWN for the first three
goals. `either_way` simplifies to `a`, which is known to be true, and AskCert reports exactly that.

### Completion semantics is not closed-world evaluation

A closed-world evaluator treats every fact that is not listed as false. AskCert never does. The
same rule can be settled or unsettled depending on what is known:

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
print(engine.evaluate("eligible", {"is_adult": True}))
print(engine.evaluate("eligible", {"is_adult": True, "is_banned": False}))
print(engine.evaluate("eligible", {"is_adult": True, "is_banned": None}))
```

```text
UNKNOWN
TRUE
UNKNOWN
```

A closed-world run would answer TRUE for the first line by assuming `is_banned` is false.

## Supporting certificates

If $s = \operatorname{Dec}(g,K) \in \{\text{TRUE}, \text{FALSE}\}$, a *supporting certificate* is a
partial assignment $S \subseteq K$ (viewing assignments as sets of atom-value pairs) with
$\operatorname{Dec}(g,S) = s$. In plain terms: known facts that are by themselves enough to
sustain the decision. AskCert restricts certificates to atoms of the cone.

A certificate is *subset-minimal* if no proper subset remains sufficient:

$$\operatorname{Dec}(g,S) = s \quad\text{and}\quad \operatorname{Dec}\bigl(g,\, S \setminus \{(a,v)\}\bigr) \neq s \quad \text{for all } (a,v) \in S.$$

`certify` returns a subset-minimal certificate. Three properties matter in practice.

1. **Subset-minimal, not minimum-cardinality.** No fact can be removed, but a smaller certificate
   built from different facts may exist.
2. **Not necessarily unique.** A decision can have several subset-minimal certificates.
   AskCert returns one of them.
3. **Deterministic.** Start with $S = K \cap A_g$. Visit the atoms of $S$ in lexicographic order
   of atom name. For each atom, delete it if the status is still $s$ without it. The result
   depends only on the rules, the goal and the evidence. It does not depend on the internal
   variable order.

Because deletion visits atoms in name order, the *lexicographically smallest* atoms are the first
to be dropped. With `any(a, b)` and both facts true, `a` is dropped first, so the certificate keeps
`b` even though `{a}` would also do:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["a", "b"]}})
print(dict(engine.certify("g", {"a": True, "b": True}).certificate))
```

```text
{'b': True}
```

Subset-minimal does not mean smallest. In the next example `{a: True}` alone settles the goal, but
`a` is the first atom visited, it is deletable (because `b` and `c` still prove the goal), and the
procedure ends with a two-fact certificate:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["a", {"all": ["b", "c"]}]}})
result = engine.certify("g", {"a": True, "b": True, "c": True})
print(dict(result.certificate))
print(dict(engine.certify("g", {"a": True}).certificate))
```

```text
{'b': True, 'c': True}
{'a': True}
```

The certificate may be empty. When the goal is a tautology or a contradiction, no fact is needed:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["x", {"not": "x"}]}})
result = engine.certify("g", {"x": True})
print(result.status, dict(result.certificate))
```

```text
TRUE {}
```

## Relevant unknowns

If $\operatorname{Dec}(g,K) = \text{UNKNOWN}$, an unknown atom is *decision-relevant* if changing
only that atom can change the goal value under some completion consistent with $K$:

$$
\operatorname{Rel}(g,K) = \{\, a \in A_g \setminus \operatorname{dom}(K) :
\exists\, w, w' \in \Omega(K),\ w|_{A_g \setminus \{a\}} = w'|_{A_g \setminus \{a\}},\ f_g(w) \neq f_g(w') \,\}.
$$

These are the atoms on which the goal still depends after conditioning on the evidence. An unknown
outside $\operatorname{Rel}(g,K)$ cannot affect the decision while the known facts stay fixed.

The set is **exact**. It is neither an over-approximation (all unknown atoms in the cone) nor an
under-approximation. Relevance is a property of the function, not of the rule text. An atom that
appears in a rule but is logically redundant is not relevant:

```python
from askcert import AskCert

engine = AskCert({"g": {"any": ["a", {"all": ["a", "b"]}]}})  # equivalent to "a"
result = engine.certify("g")
print(result.relevant_unknowns)
```

```text
('a',)
```

The tuple is sorted by atom name. It is empty exactly when the goal is decided.

Relevance depends on the current evidence. After one answer arrives, the set can shrink or the goal
can become decided:

```python
from askcert import AskCert

engine = AskCert({"g": {"all": ["a", {"any": ["b", "c"]}]}})
for evidence in [{}, {"a": True}, {"a": True, "b": False}, {"a": True, "b": True}]:
    r = engine.certify("g", evidence)
    print(evidence, r.status, r.relevant_unknowns)
```

```text
{} UNKNOWN ('a', 'b', 'c')
{'a': True} UNKNOWN ('b', 'c')
{'a': True, 'b': False} UNKNOWN ('c',)
{'a': True, 'b': True} TRUE ()
```

## Witnesses

When the status is UNKNOWN, a *witness pair* shows both outcomes are possible: two complete
assignments over the cone, both agreeing with the evidence, one under which $f_g = 1$ (the
`true_world`) and one under which $f_g = 0$ (the `false_world`).

```python
from askcert import AskCert

engine = AskCert({"eligible": {"all": ["is_adult", {"not": "is_banned"}]}})
w = engine.certify("eligible", {"is_adult": True}).witnesses
print(dict(w.true_world))
print(dict(w.false_world))
```

```text
{'is_adult': True, 'is_banned': False}
{'is_adult': True, 'is_banned': True}
```

Construction is deterministic: AskCert follows a path through the restricted decision diagram,
trying the `False` branch first, and sets every cone atom that is neither known nor fixed by the
path to `False`. Statuses, certificates and relevant unknowns never depend on the variable order of
the engine, but the particular witness worlds can (any pair of valid worlds is a valid witness).
Witnesses are produced only for UNKNOWN goals, and `certify(..., witnesses=False)` skips them.

## Proposition 1: decision locality

Fix a rule program and a partial assignment $K$.

1. If $s = \operatorname{Dec}(g,K) \neq \text{UNKNOWN}$ and $S \subseteq K$ is a supporting
   certificate, then every partial assignment $K'$ with $S \subseteq K'$ satisfies
   $\operatorname{Dec}(g,K') = s$.
2. If $\operatorname{Dec}(g,K) = \text{UNKNOWN}$, then every extension $K' \supseteq K$ with
   $\operatorname{Rel}(g,K) \subseteq \operatorname{dom}(K')$ has a decided outcome.

*Proof.* (1) Since $S \subseteq K'$, every completion of $K'$ is a completion of $S$, so
$\Omega(K') \subseteq \Omega(S)$. By the definition of a certificate, $f_g$ is constantly $s$ on
$\Omega(S)$, hence also on $\Omega(K')$, which is nonempty.

(2) Let $R = \operatorname{Rel}(g,K)$. We first show that $f_g$ restricted to $\Omega(K)$ depends
only on the atoms in $R$. Take $w, w' \in \Omega(K)$ that agree on $R$. They can differ only on
unknown atoms outside $R$. Change $w$ into $w'$ one such atom at a time. Every intermediate
assignment agrees with $K$, so it lies in $\Omega(K)$. Because no atom outside $R$ is relevant,
each single change leaves $f_g$ unchanged, so $f_g(w) = f_g(w')$. Now let $K' \supseteq K$ with
$R \subseteq \operatorname{dom}(K')$. All completions of $K'$ lie in $\Omega(K)$ and agree on $R$
(namely with $K'$), so $f_g$ takes a single value on $\Omega(K')$. $\blacksquare$

What the proposition says in practice:

- **Decided goals.** A certificate lists the known facts that matter. Whatever else is later
  learned about other atoms, as long as the certificate facts are kept, the decision cannot change.
  If a decision looks wrong, re-examine the certificate facts first. The other facts play no role.
- **Undecided goals.** Obtaining values for *all* relevant unknowns always settles the goal. Values
  for atoms outside the relevant set cannot settle it on their own.

Part 2 gives sufficiency, not necessity: the relevant set can be larger than the smallest set of
questions that would settle the goal (for `any(a, b)` both atoms are relevant, but learning `a=true`
already decides). AskCert does not compute a smallest question set.

```python
from itertools import product
from askcert import AskCert

engine = AskCert({"g": {"all": ["a", {"any": ["b", "c"]}, {"not": "d"}]}})
evidence = {"a": True}
relevant = engine.find_relevant_unknowns("g", evidence)
print(relevant)
statuses = set()
for values in product([False, True], repeat=len(relevant)):
    extended = {**evidence, **dict(zip(relevant, values))}
    statuses.add(engine.evaluate("g", extended).value)
print(sorted(statuses))
```

```text
('b', 'c', 'd')
['FALSE', 'TRUE']
```

Every one of the eight ways to answer the three relevant unknowns decides the goal (TRUE or
FALSE, never UNKNOWN).

## How it is computed

AskCert compiles each goal into a reduced ordered binary decision diagram (ROBDD) over the base
atoms. The diagram is canonical, so a function is constant exactly when its node is a terminal.

- **Status.** Restrict the diagram by the evidence. If the result is the terminal 1 the status is
  TRUE, if it is the terminal 0 the status is FALSE, otherwise UNKNOWN.
- **Relevant unknowns.** The support of the restricted diagram, that is, the variables that still
  occur in it. In a reduced diagram every remaining variable is essential, which is the
  definition of relevance above.
- **Certificate.** The deletion procedure described above, with one restriction of the diagram
  per known cone atom.
- **Witnesses.** A depth-first path to each terminal, `False` branch first.

The pure-Python diagram is the only backend in version 0.1. Diagram size depends on the rules and
on the variable order, and for some functions it grows exponentially with the number of atoms. The
`max_nodes` and `timeout` limits bound this; when one is hit, AskCert raises
`ResourceLimitExceeded`.

## What is not supported

AskCert is deliberately small. These are outside its scope in version 0.1:

- **First-order logic.** There are no variables, quantifiers, predicates with arguments or
  functions. Atoms are propositional. Instantiate first-order rules by hand if you need them.
- **Probabilistic or weighted logic.** Atoms are true, false or unknown. There are no
  probabilities, confidence scores, fuzzy values or "probably true" evidence.
- **Cyclic or recursive rules.** A rule set must be acyclic. A cycle is rejected when the rule set
  is built, with the cycle path in the message.
- **Defeasible priorities.** `unless` is a classical Boolean exception (`core AND NOT exception`).
  There are no rule priorities, overriding or conflict resolution between rules.
- **Negation as failure.** `not` and `!name` are classical negation of a Boolean value, not a
  test for the absence of a fact.
- **Minimum-cardinality certificates.** Certificates are subset-minimal only. There is no option to
  search for a smallest one.
- **Minimum question sets.** Relevant unknowns are exact, but AskCert does not compute the smallest
  or cheapest set of unknowns to ask about. (The session API ranks questions
  with a heuristic score; the score is not an optimality guarantee.)
- **Non-Boolean values.** Atoms cannot be numbers, strings or enumerations. Encode a comparison
  such as `income > 1000` as a Boolean atom in advance.
- **Contradictory evidence.** Evidence assigns one value per atom. The engine has no way to
  represent two conflicting observations of the same atom.
