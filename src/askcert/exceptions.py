"""Exception hierarchy. Every error raised by AskCert derives from :class:`AskCertError`."""

from __future__ import annotations


class AskCertError(Exception):
    """Base class of all AskCert errors."""


class RuleError(AskCertError, ValueError):
    """Invalid rules, rule schema, cycle, undefined reference or unknown goal."""


class EvidenceError(AskCertError, ValueError):
    """Invalid evidence: unknown atom, assignment to a derived rule, or a non-boolean value."""


class ObservationConflictError(EvidenceError):
    """Session API: a known fact was re-observed with the opposite value without ``replace=True``."""


class ResourceLimitExceeded(AskCertError):
    """A computation hit a resource limit; the answer is *not* UNKNOWN, it was not computed.

    ``limit`` is ``"max_nodes"``, ``"timeout"`` or ``"recursion"``; ``value`` is the configured
    bound (node count, seconds, or the interpreter recursion limit).
    """

    def __init__(self, limit: str, value: float | None = None) -> None:
        super().__init__(limit, value)
        self.limit = limit
        self.value = value

    def __str__(self) -> str:
        return f"resource limit exceeded: {self.limit} (limit value {self.value})"
