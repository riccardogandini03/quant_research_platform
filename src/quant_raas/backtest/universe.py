"""Point-in-time universe membership helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from quant_raas.backtest.validation import normalize_utc, require_columns


def members_as_of(membership: pd.DataFrame, as_of: datetime) -> set[str]:
    """Resolve members using effective intervals rather than today's index list."""

    require_columns(membership, ["security_id", "valid_from", "valid_to"])
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    valid_from = normalize_utc(membership["valid_from"], name="valid_from")
    valid_to = pd.to_datetime(membership["valid_to"], utc=True, errors="coerce")
    active = (valid_from <= cutoff) & (valid_to.isna() | (valid_to > cutoff))
    return set(membership.loc[active, "security_id"].astype(str))
