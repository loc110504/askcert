"""Strict JSON helpers shared by rules, evidence and result (de)serialization."""

from __future__ import annotations

import json
from typing import Any, Literal

from .exceptions import AskCertError, EvidenceError, RuleError

SCHEMA_VERSION = "1"


def load_json(text: str, kind: Literal["rules", "evidence"]) -> Any:
    """Parse JSON, rejecting duplicate object keys, ``NaN``/``Infinity`` and absurd nesting.

    Problems raise :class:`RuleError` for ``kind="rules"`` and :class:`EvidenceError` for
    ``kind="evidence"``.
    """
    error: type[AskCertError] = RuleError if kind == "rules" else EvidenceError

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error(f"duplicate key {key!r} in JSON {kind}")
            result[key] = value
        return result

    def reject_constant(name: str) -> Any:
        raise error(f"invalid JSON {kind}: {name} is not allowed")

    try:
        return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise error(f"invalid JSON {kind}: {exc}") from exc
    except RecursionError as exc:
        raise error(f"invalid JSON {kind}: nested too deeply") from exc


def dumps(obj: Any, **json_kwargs: Any) -> str:
    """``json.dumps`` that refuses ``NaN``/``Infinity`` unless the caller overrides it."""
    json_kwargs.setdefault("allow_nan", False)
    return json.dumps(obj, **json_kwargs)
