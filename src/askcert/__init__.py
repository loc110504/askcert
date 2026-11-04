"""AskCert: certifiable Boolean reasoning under incomplete evidence.

Decide a goal as TRUE, FALSE or UNKNOWN over *all completions* of the missing evidence, with a
subset-minimal supporting certificate, the decision-relevant unknowns and opposite-outcome
witnesses. Pure Python, no dependencies.
"""

from .api import AskCert, compile_rules
from .exceptions import (
    AskCertError,
    EvidenceError,
    ObservationConflictError,
    ResourceLimitExceeded,
    RuleError,
)
from .models import CertificationResult, Status, Witnesses
from .rules import RuleSet
from .session import Decision, Question, Reasoner, Rule

__version__ = "0.1.0"

__all__ = [
    "AskCert",
    "AskCertError",
    "CertificationResult",
    "Decision",
    "EvidenceError",
    "ObservationConflictError",
    "Question",
    "Reasoner",
    "ResourceLimitExceeded",
    "Rule",
    "RuleError",
    "RuleSet",
    "Status",
    "Witnesses",
    "__version__",
    "compile_rules",
]
