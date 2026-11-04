"""Boolean-function backends. v0.1 ships a single pure-Python ROBDD."""

from .base import Backend
from .bdd import BDD

__all__ = ["BDD", "Backend"]
