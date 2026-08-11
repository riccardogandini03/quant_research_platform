"""Conservative identifier cleanup before security-master resolution."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def canonicalize_identifier(value: str) -> str:
    """Trim and uppercase an external identifier without guessing its scheme."""

    normalized = _WHITESPACE.sub(" ", value.strip()).upper()
    if not normalized:
        raise ValueError("identifier cannot be empty")
    return normalized


def canonicalize_scheme(value: str) -> str:
    """Normalize known scheme labels while retaining vendor-specific schemes."""

    scheme = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "bbgid": "figi",
        "bloomberg_global_id": "figi",
        "reuters_instrument_code": "ric",
        "yahoo": "yahoo_symbol",
    }
    scheme = aliases.get(scheme, scheme)
    if not scheme:
        raise ValueError("identifier scheme cannot be empty")
    return scheme
