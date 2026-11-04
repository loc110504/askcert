"""Result types: :class:`Status`, :class:`Witnesses` and :class:`CertificationResult`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .exceptions import EvidenceError
from .serialization import SCHEMA_VERSION, dumps


class Status(StrEnum):
    """Outcome of a decision under incomplete evidence (a ``str`` enum: ``Status.TRUE == "TRUE"``)."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


def _frozen(mapping: Mapping[str, bool]) -> Mapping[str, bool]:
    return MappingProxyType(dict(sorted(mapping.items())))


def _bool_map(obj: object, what: str) -> dict[str, bool]:
    if not isinstance(obj, Mapping) or not all(
        isinstance(k, str) and type(v) is bool for k, v in obj.items()
    ):
        raise EvidenceError(f"{what} must be an object mapping names to booleans")
    return dict(obj)


@dataclass(frozen=True)
class Witnesses:
    """Two complete worlds over the goal's cone atoms that both agree with the evidence:
    the goal is true in ``true_world`` and false in ``false_world``."""

    true_world: Mapping[str, bool]
    false_world: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "true_world", _frozen(self.true_world))
        object.__setattr__(self, "false_world", _frozen(self.false_world))

    def __reduce__(self) -> tuple[Any, ...]:
        return (Witnesses, (dict(self.true_world), dict(self.false_world)))

    def to_dict(self) -> dict[str, Any]:
        return {"true": dict(self.true_world), "false": dict(self.false_world)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Witnesses:
        if not isinstance(d, Mapping) or set(d) != {"true", "false"}:
            raise EvidenceError("witnesses must be an object with keys 'true' and 'false'")
        return cls(_bool_map(d["true"], "witness world"), _bool_map(d["false"], "witness world"))


@dataclass(frozen=True)
class CertificationResult:
    """Outcome of certifying one goal against one body of evidence.

    ``status`` follows completion semantics. If decided, ``certificate`` is a subset-minimal
    subset of the evidence (restricted to the goal's atoms) that alone fixes the status; it may
    be empty (tautology). If UNKNOWN, ``relevant_unknowns`` lists the unknown atoms whose value
    could change the outcome and ``witnesses`` (unless disabled) show both outcomes.
    """

    goal: str
    status: Status
    evidence: Mapping[str, bool]
    certificate: Mapping[str, bool] | None
    relevant_unknowns: tuple[str, ...]
    witnesses: Witnesses | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", Status(self.status))
        object.__setattr__(self, "evidence", _frozen(self.evidence))
        if self.certificate is not None:
            object.__setattr__(self, "certificate", _frozen(self.certificate))
        object.__setattr__(self, "relevant_unknowns", tuple(self.relevant_unknowns))

    def __reduce__(self) -> tuple[Any, ...]:
        return (CertificationResult.from_dict, (self.to_dict(),))

    @property
    def decided(self) -> bool:
        """True iff the status is TRUE or FALSE."""
        return self.status is not Status.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """Stable JSON-compatible form (schema version 1; keys sorted inside mappings)."""
        return {
            "schema_version": SCHEMA_VERSION,
            "goal": self.goal,
            "status": self.status.value,
            "evidence": dict(self.evidence),
            "certificate": None if self.certificate is None else dict(self.certificate),
            "relevant_unknowns": list(self.relevant_unknowns),
            "witnesses": None if self.witnesses is None else self.witnesses.to_dict(),
        }

    def to_json(self, **json_kwargs: Any) -> str:
        return dumps(self.to_dict(), **json_kwargs)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CertificationResult:
        """Inverse of :meth:`to_dict`; malformed input raises :class:`EvidenceError`."""
        if not isinstance(d, Mapping):
            raise EvidenceError("result must be an object")
        if d.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise EvidenceError(f"unsupported schema_version {d['schema_version']!r}")
        missing = {"goal", "status", "evidence", "certificate", "relevant_unknowns"} - set(d)
        if missing:
            raise EvidenceError(f"result is missing {sorted(missing)}")
        unknowns = d["relevant_unknowns"]
        if (
            not isinstance(d["goal"], str)
            or not isinstance(unknowns, (list, tuple))
            or not all(isinstance(a, str) for a in unknowns)
        ):
            raise EvidenceError("result has a malformed 'goal' or 'relevant_unknowns'")
        try:
            status = Status(d["status"])
        except ValueError:
            raise EvidenceError(f"invalid status {d['status']!r}") from None
        certificate = d["certificate"]
        witnesses = d.get("witnesses")
        return cls(
            d["goal"],
            status,
            _bool_map(d["evidence"], "evidence"),
            None if certificate is None else _bool_map(certificate, "certificate"),
            tuple(unknowns),
            None if witnesses is None else Witnesses.from_dict(witnesses),
        )
