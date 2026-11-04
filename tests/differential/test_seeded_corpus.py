"""Seeded corpus: askcert vs the brute-force oracle on fixed formula/evidence pairs.

* ``test_seeded_corpus_1000_ci``   - 1,000 pairs, part of the default suite;
* ``test_seeded_corpus_10000``     - exactly 10,000 pairs from ``random.Random(20261104)``
  (``pytest -m slow``): the release gate "100% agreement with independent oracles".

Per pair: status; certificate validity (subset of evidence on the cone, sufficient,
subset-minimal, equal to the contract's lexicographic deletion result); relevant unknowns
(exact set equality); witness validity.
"""

from __future__ import annotations

import pytest

from tests.differential.corpus import SEED, corpus, run_corpus


def _gate(n, capsys):
    total, agree, stats, failures = run_corpus(n)
    with capsys.disabled():
        print(
            f"\n[askcert corpus] seed={SEED} pairs={total} agree={agree} disagree={total - agree} "
            f"({100.0 * agree / total:.2f}% agreement) "
            f"TRUE={stats['status_TRUE']} FALSE={stats['status_FALSE']} UNKNOWN={stats['status_UNKNOWN']} "
            f"cert_empty={stats['cert_empty']} cert_nonempty={stats['cert_nonempty']} "
            f"flat_list_docs={stats['flat']}"
        )
    assert total == n
    assert not failures, "\n".join(failures)
    assert agree == total == n  # 100% agreement
    # the gate is only meaningful if the corpus exercises every outcome
    for key in ("status_TRUE", "status_FALSE", "status_UNKNOWN", "cert_empty", "cert_nonempty", "flat"):
        assert stats[key] >= 0.04 * n, (key, dict(stats))


def test_corpus_is_deterministic_and_prefix_stable():
    first = list(corpus(50))
    assert first == list(corpus(50))
    assert first == list(corpus(120))[:50]
    assert first != list(corpus(50, seed=SEED + 1))


def test_seeded_corpus_1000_ci(capsys):
    _gate(1000, capsys)


@pytest.mark.slow
def test_seeded_corpus_10000(capsys):
    _gate(10_000, capsys)
