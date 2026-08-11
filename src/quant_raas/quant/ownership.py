"""Ownership, insider, and short-interest diagnostics with explicit unknowns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, SupportsFloat, SupportsIndex, cast

import numpy as np
import pandas as pd

DataStatus = Literal["OK", "PARTIAL", "UNKNOWN"]
_TimestampInput = int | float | str | date | datetime | np.datetime64
_MissingScalarInput = str | float | pd.Timestamp | np.datetime64


@dataclass(frozen=True, slots=True)
class InsiderActivity:
    """Classified open-market insider activity over an as-of window."""

    buy_value: float | None
    sell_value: float | None
    net_value: float | None
    buy_sell_ratio: float | None
    classified_transactions: int
    unclassified_transactions: int
    status: DataStatus
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InstitutionalChange:
    observations: int
    mean_share_change: float | None
    median_share_change: float | None
    total_share_change: float | None
    status: DataStatus


@dataclass(frozen=True, slots=True)
class ShortInterestMetrics:
    """Raw short-interest diagnostics; no squeeze label is inferred."""

    shares_short: float | None
    short_percent_of_float: float | None
    days_to_cover: float | None
    shares_short_prior: float | None
    change_in_shares_short: float | None
    change_percent: float | None
    status: DataStatus


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def latest_ownership_snapshots_as_of(
    snapshots: pd.DataFrame,
    *,
    as_of: object,
    key_columns: Sequence[str] = ("security_id",),
    available_col: str = "available_at",
) -> pd.DataFrame:
    """Select each ownership series' latest point-in-time snapshot."""

    required = [*key_columns, available_col]
    missing = sorted(set(required).difference(snapshots.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
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


def insider_activity(
    transactions: pd.DataFrame,
    *,
    as_of: object,
    lookback_days: int = 365,
    action_col: str = "transaction_type",
    value_col: str = "value",
    available_col: str = "available_at",
) -> InsiderActivity:
    """Aggregate classified open-market buys/sells known by an exact cutoff."""

    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    missing = sorted({action_col, value_col, available_col}.difference(transactions.columns))
    if missing:
        return InsiderActivity(
            None,
            None,
            None,
            None,
            0,
            len(transactions),
            "UNKNOWN",
            tuple(f"missing_{item}" for item in missing),
        )
    cutoff = _aware_timestamp(as_of, name="as_of")
    work = transactions.copy()
    work[available_col] = work[available_col].map(
        lambda value: _aware_timestamp(value, name=available_col)
    )
    work = work.loc[
        (work[available_col] <= cutoff)
        & (work[available_col] >= cutoff - timedelta(days=lookback_days))
    ]
    if work.empty:
        return InsiderActivity(
            None, None, None, None, 0, 0, "UNKNOWN", ("no_transactions_in_window",)
        )
    actions = work[action_col].astype("string").str.lower().fillna("")
    excluded = actions.str.contains(
        r"gift|grant|award|exercise|option|tax|withhold|conversion", regex=True
    )
    buys = ~excluded & actions.str.contains(
        r"open[\s_-]*market[\s_-]*purchase|purchase|\bbuy\b", regex=True
    )
    sells = ~excluded & actions.str.contains(
        r"open[\s_-]*market[\s_-]*sale|\bsale\b|\bsell\b", regex=True
    )
    classified = buys | sells
    numeric_values = (
        pd.to_numeric(work[value_col], errors="coerce").abs().replace([np.inf, -np.inf], np.nan)
    )
    warnings: list[str] = []
    if numeric_values.loc[classified].isna().any():
        warnings.append("classified_transactions_missing_value")
    buy_values = numeric_values.loc[buys].dropna()
    sell_values = numeric_values.loc[sells].dropna()
    classified_count = int(classified.sum())
    unclassified_count = int((~classified).sum())
    if classified_count == 0 or (buy_values.empty and sell_values.empty):
        return InsiderActivity(
            None,
            None,
            None,
            None,
            classified_count,
            unclassified_count,
            "UNKNOWN",
            tuple(sorted({*warnings, "no_classified_open_market_transactions"})),
        )
    buy_value = float(buy_values.sum()) if not buy_values.empty else 0.0
    sell_value = float(sell_values.sum()) if not sell_values.empty else 0.0
    if sell_value > 0.0:
        ratio: float | None = buy_value / sell_value
    elif buy_value > 0.0:
        ratio = float("inf")
    else:
        ratio = None
    if unclassified_count:
        warnings.append("unclassified_transactions_present")
    status: DataStatus = "PARTIAL" if warnings else "OK"
    return InsiderActivity(
        buy_value=buy_value,
        sell_value=sell_value,
        net_value=buy_value - sell_value,
        buy_sell_ratio=ratio,
        classified_transactions=classified_count,
        unclassified_transactions=unclassified_count,
        status=status,
        warnings=tuple(sorted(set(warnings))),
    )


def institutional_position_change(
    holders: pd.DataFrame,
    *,
    change_col: str = "share_change",
) -> InstitutionalChange:
    """Summarize holder share changes; absent change data remains unknown."""

    if change_col not in holders:
        return InstitutionalChange(0, None, None, None, "UNKNOWN")
    changes = (
        pd.to_numeric(holders[change_col], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if changes.empty:
        return InstitutionalChange(0, None, None, None, "UNKNOWN")
    status: DataStatus = "PARTIAL" if len(changes) < len(holders) else "OK"
    return InstitutionalChange(
        observations=len(changes),
        mean_share_change=float(changes.mean()),
        median_share_change=float(changes.median()),
        total_share_change=float(changes.sum()),
        status=status,
    )


def _optional_number(
    values: Mapping[str, object],
    key: str,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float | None:
    value = values.get(key)
    if value is None or pd.isna(cast(_MissingScalarInput, value)):
        return None
    try:
        # Conversion handles NaN/NA below and preserves the permissive mapping
        # boundary while making the accepted scalar protocol explicit.
        numeric = float(cast(str | bytes | SupportsFloat | SupportsIndex, value))
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric) or numeric < minimum:
        return None
    if maximum is not None and numeric > maximum:
        return None
    return numeric


def short_interest_metrics(
    snapshot: Mapping[str, object],
    *,
    shares_short_key: str = "shares_short",
    short_percent_float_key: str = "short_percent_of_float",
    days_to_cover_key: str = "days_to_cover",
    prior_shares_short_key: str = "shares_short_prior",
) -> ShortInterestMetrics:
    """Normalize short metrics while preserving units and missing values."""

    shares_short = _optional_number(snapshot, shares_short_key)
    # Percent-of-float is represented as a decimal fraction in this contract.
    short_percent = _optional_number(snapshot, short_percent_float_key, maximum=1.0)
    days_to_cover = _optional_number(snapshot, days_to_cover_key)
    prior = _optional_number(snapshot, prior_shares_short_key)
    change = shares_short - prior if shares_short is not None and prior is not None else None
    change_percent = (
        change / prior if change is not None and prior is not None and prior != 0.0 else None
    )
    known_count = sum(
        value is not None for value in (shares_short, short_percent, days_to_cover, prior)
    )
    if known_count == 0:
        status: DataStatus = "UNKNOWN"
    elif known_count < 4:
        status = "PARTIAL"
    else:
        status = "OK"
    return ShortInterestMetrics(
        shares_short=shares_short,
        short_percent_of_float=short_percent,
        days_to_cover=days_to_cover,
        shares_short_prior=prior,
        change_in_shares_short=change,
        change_percent=change_percent,
        status=status,
    )
