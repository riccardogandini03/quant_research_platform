"""Macro-release surprises, event studies, and rolling sensitivities."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import cast

import numpy as np
import pandas as pd

from quant_raas.quant.anomalies import rolling_zscore
from quant_raas.quant.event_study import EventStudyResult, EventStudySpec, extract_event_windows
from quant_raas.quant.factors import rolling_factor_exposures

_TimestampInput = int | float | str | date | datetime | np.datetime64


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def latest_macro_vintages_as_of(
    releases: pd.DataFrame,
    *,
    as_of: object,
    key_columns: Sequence[str] = ("series_id", "period_end"),
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Select the latest macro vintage that was knowable at ``as_of``."""

    required = [*key_columns, available_col]
    missing = sorted(set(required).difference(releases.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    cutoff = _aware_timestamp(as_of, name="as_of")
    work = releases.copy()
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


def macro_surprise(actual: pd.Series, consensus: pd.Series) -> pd.Series:
    """Return the raw release surprise ``actual - consensus``."""

    actual_values = pd.to_numeric(actual, errors="coerce").replace([np.inf, -np.inf], np.nan)
    consensus_values = pd.to_numeric(consensus, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return actual_values.sub(consensus_values).rename("macro_surprise")


def rolling_standardized_surprise(
    surprises: pd.Series,
    *,
    window: int = 24,
    minimum_observations: int = 12,
    lag: int = 1,
    ddof: int = 1,
) -> pd.Series:
    """Standardize each release against only earlier surprise observations."""

    result = rolling_zscore(
        surprises,
        window=window,
        min_periods=minimum_observations,
        lag=lag,
        ddof=ddof,
    )
    return result.rename("standardized_macro_surprise")


def standardized_macro_changes(
    levels: pd.Series,
    *,
    difference_periods: int = 1,
    window: int = 126,
    minimum_observations: int = 63,
    lag: int = 1,
) -> pd.Series:
    """Convert macro levels to changes and standardize them on prior history."""

    if difference_periods < 1:
        raise ValueError("difference_periods must be positive")
    clean = pd.to_numeric(levels, errors="coerce").replace([np.inf, -np.inf], np.nan)
    changes = clean.diff(difference_periods).rename("macro_change")
    return rolling_zscore(
        changes,
        window=window,
        min_periods=minimum_observations,
        lag=lag,
    ).rename("standardized_macro_change")


def macro_event_study(
    session_returns: pd.Series,
    releases: pd.DataFrame,
    spec: EventStudySpec,
    *,
    release_time_col: str = "release_at",
    event_id_col: str = "event_id",
    available_col: str | None = "available_at",
    as_of: object | None = None,
) -> EventStudyResult:
    """Run a timestamp-aware event study over normalized macro releases."""

    return extract_event_windows(
        session_returns,
        releases,
        spec,
        event_time_col=release_time_col,
        event_id_col=event_id_col,
        timing_col=None,
        available_col=available_col,
        as_of=as_of,
    )


def rolling_macro_sensitivities(
    asset_returns: pd.Series,
    standardized_factor_changes: pd.DataFrame,
    *,
    window: int = 126,
    minimum_observations: int = 63,
) -> pd.DataFrame:
    """Estimate macro betas through ``t-1`` from standardized factor changes."""

    return rolling_factor_exposures(
        asset_returns,
        standardized_factor_changes,
        window=window,
        minimum_observations=minimum_observations,
    )
