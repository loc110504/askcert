"""Shared pytest/Hypothesis configuration.

Hypothesis profiles (select with ``HYPOTHESIS_PROFILE=<name>``, default ``dev``):

* ``dev``      200 examples   - local development, whole non-slow suite in well under a minute
* ``ci``       1000 examples  - continuous integration
* ``release``  10000 examples - release gate (``HYPOTHESIS_PROFILE=release pytest -m "slow or not slow"``)

All profiles are ``derandomize=True`` (reproducible examples, no example database) and
``deadline=None`` (pure-Python BDD timings vary between machines).
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

_COMMON = {
    "derandomize": True,
    "deadline": None,
    "database": None,
    "suppress_health_check": [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much],
}

settings.register_profile("dev", max_examples=200, **_COMMON)
settings.register_profile("ci", max_examples=1000, **_COMMON)
settings.register_profile("release", max_examples=10000, **_COMMON)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


def pytest_collection_modifyitems(config, items):
    """``slow`` tests are opt-in: run them with ``-m slow`` (or ``-m "slow or not slow"`` for everything)."""
    if "slow" in (config.getoption("-m") or "") or os.environ.get("ASKCERT_RUN_SLOW"):
        return
    import pytest

    skip = pytest.mark.skip(reason="slow corpus: run with -m slow (or ASKCERT_RUN_SLOW=1)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
