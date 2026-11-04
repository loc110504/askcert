"""Batch certification: compile the rules once, certify many cases.

Reads the FICTIONAL scholarship rules in examples/data (the same files the CLI docs use),
certifies the JSON Lines cases, then certifies every one of the 3^6 = 729 combinations of
true / false / unknown for the six atoms.

Run:  python examples/07_batch_certification.py
"""

import itertools
import json
import time
from collections import Counter
from pathlib import Path

from askcert import AskCert, RuleSet

DATA = Path(__file__).resolve().parent / "data"  # works from any working directory

rules = RuleSet.load(DATA / "eligibility_rules.json")
engine = AskCert(rules).compile("eligible")  # compile once; every query below reuses it

# 1. The JSON Lines cases (blank lines are skipped, as the CLI does).
cases = [
    json.loads(line)
    for line in (DATA / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
for case, result in zip(cases, engine.certify_many("eligible", cases, witnesses=False), strict=True):
    print(f"{result.status:7} {case}")

# 2. Exhaustive sweep: each atom is True, False or unknown (None).
atoms = rules.declared_atoms or rules.atoms
sweep = [
    dict(zip(atoms, values, strict=True))
    for values in itertools.product((True, False, None), repeat=len(atoms))
]
start = time.perf_counter()
results = engine.certify_many("eligible", sweep)  # one engine, bounded memory
elapsed = time.perf_counter() - start

counts = Counter(str(r.status) for r in results)
print(f"\ncertified {len(results)} evidence bodies: {dict(sorted(counts.items()))}")
print(f"timing (varies by machine): {elapsed * 1000:.1f} ms, {elapsed / len(results) * 1e6:.0f} us per case")
