"""UTC clock helpers used by all point-in-time contracts.

Naive datetimes are rejected instead of being interpreted in the machine's
local timezone. Silent timezone assumptions are a common source of look-ahead
errors around earnings releases and other after-market events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, rejecting ambiguous naive values."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include an explicit timezone")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC value."""

    return datetime.now(UTC)


# Pydantic parses an incoming ISO string before this validator runs. This lets
# every domain contract share exactly the same UTC normalization rule.
UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]
