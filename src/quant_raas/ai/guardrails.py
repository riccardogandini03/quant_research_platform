"""Numerical-integrity checks applied to generated research prose."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum


class NumericUnit(StrEnum):
    NUMBER = "number"
    PERCENT = "percent"
    BASIS_POINTS = "basis_points"
    MULTIPLE = "multiple"
    CURRENCY = "currency"


@dataclass(frozen=True, slots=True)
class NumericFact:
    """One number that a text generator is permitted to mention.

    Values use analytical units: 4.1% is stored as ``0.041`` and 38 bps as
    ``0.0038``.  Display conversion happens only in this validation boundary.
    """

    name: str
    value: float
    unit: NumericUnit = NumericUnit.NUMBER
    absolute_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("numeric facts must be finite")
        if self.absolute_tolerance < 0:
            raise ValueError("absolute_tolerance cannot be negative")


@dataclass(frozen=True, slots=True)
class NumericClaim:
    raw: str
    value: float
    unit: NumericUnit
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class NumericValidationResult:
    valid: bool
    claims: tuple[NumericClaim, ...]
    unsupported_claims: tuple[NumericClaim, ...]


_NUMERIC_CLAIM = re.compile(
    r"(?<![\w])(?P<currency>[$€£])?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"\s*(?P<unit>%|bps?\b|x\b)?",
    flags=re.IGNORECASE,
)


def extract_numeric_claims(text: str) -> tuple[NumericClaim, ...]:
    """Extract explicit numbers without trying to infer finance from prose."""

    claims: list[NumericClaim] = []
    for match in _NUMERIC_CLAIM.finditer(text):
        raw_unit = (match.group("unit") or "").lower()
        display_value = float(match.group("number").replace(",", ""))
        if raw_unit == "%":
            unit, value = NumericUnit.PERCENT, display_value / 100.0
        elif raw_unit.startswith("bp"):
            unit, value = NumericUnit.BASIS_POINTS, display_value / 10_000.0
        elif raw_unit == "x":
            unit, value = NumericUnit.MULTIPLE, display_value
        elif match.group("currency"):
            unit, value = NumericUnit.CURRENCY, display_value
        else:
            unit, value = NumericUnit.NUMBER, display_value
        claims.append(
            NumericClaim(
                raw=match.group(0),
                value=value,
                unit=unit,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(claims)


def validate_numeric_claims(
    text: str,
    allowed: list[NumericFact] | tuple[NumericFact, ...],
) -> NumericValidationResult:
    """Reject numbers that cannot be reconciled with structured input facts.

    Unit matching is strict by design.  A future renderer may add explicit unit
    aliases, but silently treating a percentage as a raw value would defeat the
    integrity check.
    """

    claims = extract_numeric_claims(text)
    unsupported: list[NumericClaim] = []
    for claim in claims:
        supported = any(
            fact.unit == claim.unit
            and math.isclose(
                fact.value,
                claim.value,
                rel_tol=1e-6,
                abs_tol=fact.absolute_tolerance,
            )
            for fact in allowed
        )
        if not supported:
            unsupported.append(claim)
    return NumericValidationResult(
        valid=not unsupported,
        claims=claims,
        unsupported_claims=tuple(unsupported),
    )


def require_evidence_ids(evidence_ids: list[str] | tuple[str, ...]) -> None:
    """Prevent release of an evidence-free generated research statement."""

    if not evidence_ids or any(not item.strip() for item in evidence_ids):
        raise ValueError("generated research requires non-empty evidence IDs")
