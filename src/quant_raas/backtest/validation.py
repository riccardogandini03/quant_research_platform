"""Look-ahead and shape validation for historical simulations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd


class PointInTimeViolation(ValueError):
    """Raised when a simulated decision can see data from its future."""


def require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    """Fail with one actionable message instead of a later pandas KeyError."""

    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def normalize_utc(series: pd.Series, *, name: str) -> pd.Series:
    """Normalize an input timestamp column and reject unparseable values."""

    values = pd.to_datetime(series, utc=True, errors="coerce")
    if values.isna().any():
        bad_rows = values.index[values.isna()].tolist()[:5]
        raise ValueError(f"{name} contains invalid timestamps at rows {bad_rows}")
    return values


def assert_available_by_decision(
    frame: pd.DataFrame,
    *,
    decision_col: str = "decision_at",
    available_col: str = "available_at",
) -> None:
    """Enforce the central point-in-time invariant row by row."""

    require_columns(frame, [decision_col, available_col])
    decisions = normalize_utc(frame[decision_col], name=decision_col)
    availability = normalize_utc(frame[available_col], name=available_col)
    leaked = availability > decisions
    if leaked.any():
        sample = frame.index[leaked].tolist()[:5]
        raise PointInTimeViolation(
            f"{int(leaked.sum())} rows were unavailable at decision time; sample rows: {sample}"
        )


def latest_vintage_as_of(
    frame: pd.DataFrame,
    *,
    as_of: datetime,
    keys: Sequence[str],
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Return each key's newest vintage that was knowable at ``as_of``.

    ``period_end`` is intentionally not used as a knowledge timestamp.  A later
    restatement of an old period must not leak into an earlier simulation.
    """

    require_columns(frame, [*keys, available_col])
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    work = frame.copy()
    work[available_col] = normalize_utc(work[available_col], name=available_col)
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    work = work.loc[work[available_col] <= cutoff]
    if work.empty:
        return work

    # Stable sorting makes the result deterministic when callers preserve a
    # vendor sequence column as part of the keys.
    work = work.sort_values([*keys, available_col], kind="mergesort")
    return work.groupby(list(keys), sort=False, as_index=False).tail(1).reset_index(drop=True)
