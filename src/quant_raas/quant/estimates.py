"""Point-in-time analyst-estimate revision features."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd

_TimestampInput = int | float | str | date | datetime | np.datetime64


@dataclass(frozen=True, slots=True)
class EstimateDispersion:
    """Cross-contributor dispersion for one estimate snapshot."""

    observations: int
    mean: float | None
    sample_standard_deviation: float | None
    coefficient_of_variation: float | None


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must contain timezone-aware timestamps")
    return timestamp.tz_convert("UTC")


def latest_estimates_as_of(
    snapshots: pd.DataFrame,
    *,
    as_of: object,
    key_columns: Sequence[str] = ("security_id", "metric", "fiscal_period"),
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Select each estimate series' latest vintage knowable at ``as_of``."""

    _require_columns(snapshots, [*key_columns, available_col])
    cutoff = _aware_timestamp(as_of, name="as_of")
    work = snapshots.copy()
    work[available_col] = work[available_col].map(
        lambda value: _aware_timestamp(value, name=available_col)
    )
    work = work.loc[work[available_col] <= cutoff]
    if work.empty:
        return work
    work = work.sort_values([*key_columns, available_col], kind="mergesort")
    return (
        work.groupby(list(key_columns), sort=False, as_index=False).tail(1).reset_index(drop=True)
    )


def estimate_revisions(
    snapshots: pd.DataFrame,
    *,
    as_of: object,
    lookback_days: Sequence[int] = (1, 7, 30),
    key_columns: Sequence[str] = ("security_id", "metric", "fiscal_period"),
    value_col: str = "consensus",
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Calculate percentage revisions against point-in-time historical vintages."""

    lookbacks = tuple(dict.fromkeys(int(days) for days in lookback_days))
    if not lookbacks or any(days < 1 for days in lookbacks):
        raise ValueError("lookback_days must contain positive integers")
    _require_columns(snapshots, [*key_columns, value_col, available_col])
    cutoff = _aware_timestamp(as_of, name="as_of")
    current = latest_estimates_as_of(
        snapshots,
        as_of=cutoff,
        key_columns=key_columns,
        available_col=available_col,
    )
    current = current[[*key_columns, value_col, available_col]].rename(
        columns={value_col: "consensus_now", available_col: "available_at_now"}
    )
    current["consensus_now"] = pd.to_numeric(current["consensus_now"], errors="coerce")
    result = current
    for days in lookbacks:
        historical = latest_estimates_as_of(
            snapshots,
            as_of=cutoff - timedelta(days=days),
            key_columns=key_columns,
            available_col=available_col,
        )[[*key_columns, value_col]]
        historical_name = f"consensus_{days}d_ago"
        historical = historical.rename(columns={value_col: historical_name})
        historical[historical_name] = pd.to_numeric(historical[historical_name], errors="coerce")
        result = result.merge(historical, on=list(key_columns), how="left", validate="one_to_one")
        denominator = result[historical_name].where(result[historical_name] != 0.0)
        result[f"revision_{days}d"] = result["consensus_now"].div(denominator).sub(1.0)
    return result


def revision_breadth(
    contributor_snapshots: pd.DataFrame,
    *,
    as_of: object,
    lookback_days: int = 30,
    group_columns: Sequence[str] = ("security_id", "metric", "fiscal_period"),
    contributor_col: str = "contributor_id",
    value_col: str = "estimate",
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Compute ``(raises - cuts) / changed contributors`` over a PIT window."""

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    keys = (*group_columns, contributor_col)
    _require_columns(contributor_snapshots, [*keys, value_col, available_col])
    cutoff = _aware_timestamp(as_of, name="as_of")
    current = latest_estimates_as_of(
        contributor_snapshots,
        as_of=cutoff,
        key_columns=keys,
        available_col=available_col,
    )[[*keys, value_col]].rename(columns={value_col: "estimate_now"})
    prior = latest_estimates_as_of(
        contributor_snapshots,
        as_of=cutoff - timedelta(days=lookback_days),
        key_columns=keys,
        available_col=available_col,
    )[[*keys, value_col]].rename(columns={value_col: "estimate_prior"})
    paired = current.merge(prior, on=list(keys), how="inner", validate="one_to_one")
    paired["estimate_now"] = pd.to_numeric(paired["estimate_now"], errors="coerce")
    paired["estimate_prior"] = pd.to_numeric(paired["estimate_prior"], errors="coerce")
    paired = paired.dropna(subset=["estimate_now", "estimate_prior"])
    paired["direction"] = np.sign(paired["estimate_now"] - paired["estimate_prior"])

    rows: list[dict[str, object]] = []
    for key, group in paired.groupby(list(group_columns), dropna=False, sort=False):
        key_values = key if isinstance(key, tuple) else (key,)
        raises = int((group["direction"] > 0).sum())
        cuts = int((group["direction"] < 0).sum())
        unchanged = int((group["direction"] == 0).sum())
        changed = raises + cuts
        row = dict(zip(group_columns, key_values, strict=True))
        row.update(
            {
                "raises": raises,
                "cuts": cuts,
                "unchanged": unchanged,
                "contributors_paired": len(group),
                "contributors_changed": changed,
                "revision_breadth": (raises - cuts) / changed if changed else np.nan,
            }
        )
        rows.append(row)
    columns = [
        *group_columns,
        "raises",
        "cuts",
        "unchanged",
        "contributors_paired",
        "contributors_changed",
        "revision_breadth",
    ]
    return pd.DataFrame(rows, columns=columns)


def estimate_dispersion(values: pd.Series, *, ddof: int = 1) -> EstimateDispersion:
    """Summarize contributor dispersion without filling missing estimates."""

    if ddof < 0:
        raise ValueError("ddof cannot be negative")
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return EstimateDispersion(0, None, None, None)
    mean = float(clean.mean())
    standard_deviation = float(clean.std(ddof=ddof)) if len(clean) > ddof else None
    coefficient = (
        None if standard_deviation is None or mean == 0.0 else abs(standard_deviation / mean)
    )
    return EstimateDispersion(len(clean), mean, standard_deviation, coefficient)
