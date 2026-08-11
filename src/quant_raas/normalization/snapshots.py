"""Shared point-in-time validation for estimate and vendor snapshots."""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def select_snapshots_as_of(
    frame: pd.DataFrame,
    *,
    as_of: datetime,
    entity_columns: list[str],
    available_column: str = "available_at",
) -> pd.DataFrame:
    """Select the latest knowable vintage for each entity definition."""

    required = {*entity_columns, available_column}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"snapshot data is missing columns: {', '.join(missing)}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    work = frame.copy()
    work[available_column] = pd.to_datetime(work[available_column], utc=True, errors="coerce")
    if work[available_column].isna().any():
        raise ValueError(f"{available_column} contains invalid timestamps")
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    work = work.loc[work[available_column] <= cutoff]
    work = work.sort_values([*entity_columns, available_column], kind="mergesort")
    return work.groupby(entity_columns, sort=False, as_index=False).tail(1).reset_index(drop=True)
