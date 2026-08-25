"""Application-specific exceptions shared across adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class QuantRaasError(Exception):
    """Base class for errors callers may safely translate at an API boundary."""


class DomainValidationError(QuantRaasError):
    """Raised when a cross-record domain invariant is violated."""


class IdentifierNotFoundError(QuantRaasError):
    """Raised when a security reference cannot be resolved at an instant."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"No active security identifier matches {identifier!r}")
        self.identifier = identifier


class AmbiguousIdentifierError(QuantRaasError):
    """Raised when an identifier maps to several active securities."""

    def __init__(self, identifier: str, candidates: Sequence[Any]) -> None:
        super().__init__(
            f"Security identifier {identifier!r} is ambiguous; "
            "provide a scheme, provider, or exchange MIC"
        )
        self.identifier = identifier
        self.candidates = tuple(candidates)


class RepositoryConflictError(QuantRaasError):
    """Raised when an idempotent natural key conflicts with different data."""


class ThesisNotFoundError(QuantRaasError):
    """Raised when a requested public thesis key does not exist."""


class ThesisConflictError(QuantRaasError):
    """Raised when a thesis lifecycle mutation conflicts with persisted state."""


class ThesisReferenceError(QuantRaasError):
    """Raised when a thesis or security reference is invalid for the requested use."""
