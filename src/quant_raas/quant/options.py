"""Missing-aware options snapshot metrics without directional storytelling."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, cast

import numpy as np
import pandas as pd

DataStatus = Literal["OK", "PARTIAL", "UNKNOWN"]
_TimestampInput = int | float | str | date | datetime | np.datetime64
_MissingScalarInput = str | float | pd.Timestamp | np.datetime64


@dataclass(frozen=True, slots=True)
class PutCallMetrics:
    """Aggregate put/call activity; ratios alone are not trading signals."""

    call_volume: float | None
    put_volume: float | None
    put_call_volume_ratio: float | None
    call_open_interest: float | None
    put_open_interest: float | None
    put_call_open_interest_ratio: float | None
    snapshot_at: pd.Timestamp | None
    status: DataStatus
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeltaRiskReversal:
    """Call-minus-put implied volatility at matched absolute delta."""

    target_delta: float
    call_delta: float | None
    put_delta: float | None
    call_implied_volatility: float | None
    put_implied_volatility: float | None
    call_minus_put_iv: float | None
    status: DataStatus
    warnings: tuple[str, ...] = ()


def _aware_timestamp(value: object, *, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(cast(_TimestampInput, value))
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _latest_snapshot(
    frame: pd.DataFrame,
    *,
    as_of: object | None,
    available_col: str,
) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    if available_col not in frame:
        if as_of is not None:
            raise ValueError(f"missing required availability column: {available_col}")
        return frame.copy(), None
    work = frame.copy()
    work[available_col] = work[available_col].map(
        lambda value: _aware_timestamp(value, name=available_col)
    )
    if as_of is not None:
        cutoff = _aware_timestamp(as_of, name="as_of")
        work = work.loc[work[available_col] <= cutoff]
    if work.empty:
        return work, None
    snapshot_at = max(work[available_col])
    return work.loc[work[available_col] == snapshot_at].copy(), snapshot_at


def _known_sum(frame: pd.DataFrame, column: str) -> tuple[float | None, tuple[str, ...]]:
    if column not in frame:
        return None, (f"missing_{column}",)
    numeric = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    warnings: list[str] = []
    if numeric.isna().any():
        warnings.append(f"partial_{column}")
    if (numeric.dropna() < 0.0).any():
        warnings.append(f"negative_{column}_excluded")
        numeric = numeric.where(numeric >= 0.0)
    available = numeric.dropna()
    return (None if available.empty else float(available.sum()), tuple(warnings))


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def put_call_ratios(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    *,
    as_of: object | None = None,
    expiry: object | None = None,
    available_col: str = "available_at",
    expiry_col: str = "expiry",
    volume_col: str = "volume",
    open_interest_col: str = "open_interest",
) -> PutCallMetrics:
    """Aggregate one synchronized chain snapshot with explicit unknown states."""

    call_frame, call_time = _latest_snapshot(calls, as_of=as_of, available_col=available_col)
    put_frame, put_time = _latest_snapshot(puts, as_of=as_of, available_col=available_col)
    warnings: list[str] = []
    if call_time is not None and put_time is not None and call_time != put_time:
        warnings.append("call_put_snapshot_mismatch")
    if expiry is not None:
        if expiry_col not in call_frame or expiry_col not in put_frame:
            raise ValueError(f"expiry filter requires {expiry_col} in both frames")
        target_date = pd.Timestamp(cast(_TimestampInput, expiry)).date()
        call_frame = call_frame.loc[pd.to_datetime(call_frame[expiry_col]).dt.date == target_date]
        put_frame = put_frame.loc[pd.to_datetime(put_frame[expiry_col]).dt.date == target_date]
    else:
        for frame in (call_frame, put_frame):
            if expiry_col in frame and pd.to_datetime(frame[expiry_col]).dt.date.nunique() > 1:
                warnings.append("multiple_expiries_aggregated")
                break

    call_volume, call_volume_warnings = _known_sum(call_frame, volume_col)
    put_volume, put_volume_warnings = _known_sum(put_frame, volume_col)
    call_open_interest, call_oi_warnings = _known_sum(call_frame, open_interest_col)
    put_open_interest, put_oi_warnings = _known_sum(put_frame, open_interest_col)
    warnings.extend(
        [*call_volume_warnings, *put_volume_warnings, *call_oi_warnings, *put_oi_warnings]
    )
    volume_ratio = _safe_ratio(put_volume, call_volume)
    open_interest_ratio = _safe_ratio(put_open_interest, call_open_interest)
    if call_volume == 0.0:
        warnings.append("zero_call_volume")
    if call_open_interest == 0.0:
        warnings.append("zero_call_open_interest")
    known = [call_volume, put_volume, call_open_interest, put_open_interest]
    if all(value is None for value in known):
        status: DataStatus = "UNKNOWN"
    elif warnings or any(value is None for value in known):
        status = "PARTIAL"
    else:
        status = "OK"
    snapshot_at = call_time if call_time == put_time else None
    return PutCallMetrics(
        call_volume,
        put_volume,
        volume_ratio,
        call_open_interest,
        put_open_interest,
        open_interest_ratio,
        snapshot_at,
        status,
        tuple(sorted(set(warnings))),
    )


def delta_risk_reversal(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    *,
    target_delta: float = 0.25,
    maximum_delta_distance: float = 0.10,
    delta_col: str = "delta",
    implied_volatility_col: str = "implied_volatility",
    open_interest_col: str = "open_interest",
    minimum_open_interest: float = 0.0,
) -> DeltaRiskReversal:
    """Match liquid call/+delta and put/-delta contracts and compare their IVs."""

    if not 0.0 < target_delta <= 0.5 or maximum_delta_distance <= 0.0:
        raise ValueError("target_delta must be in (0, .5] and distance positive")
    required = {delta_col, implied_volatility_col}
    if not required.issubset(calls.columns) or not required.issubset(puts.columns):
        return DeltaRiskReversal(
            target_delta, None, None, None, None, None, "UNKNOWN", ("missing_delta_or_iv",)
        )

    def candidates(frame: pd.DataFrame, target: float) -> pd.DataFrame:
        work = frame.copy()
        work[delta_col] = pd.to_numeric(work[delta_col], errors="coerce")
        work[implied_volatility_col] = pd.to_numeric(work[implied_volatility_col], errors="coerce")
        work = work.loc[work[implied_volatility_col] > 0.0]
        if minimum_open_interest > 0.0:
            if open_interest_col not in work:
                return work.iloc[0:0]
            open_interest = pd.to_numeric(work[open_interest_col], errors="coerce")
            work = work.loc[open_interest >= minimum_open_interest]
        work = work.dropna(subset=[delta_col, implied_volatility_col]).copy()
        work["delta_distance"] = (work[delta_col] - target).abs()
        return work.sort_values("delta_distance", kind="mergesort")

    call_candidates = candidates(calls, target_delta)
    put_candidates = candidates(puts, -target_delta)
    if call_candidates.empty or put_candidates.empty:
        return DeltaRiskReversal(
            target_delta, None, None, None, None, None, "UNKNOWN", ("no_liquid_delta_match",)
        )
    call = call_candidates.iloc[0]
    put = put_candidates.iloc[0]
    if (
        call["delta_distance"] > maximum_delta_distance
        or put["delta_distance"] > maximum_delta_distance
    ):
        return DeltaRiskReversal(
            target_delta, None, None, None, None, None, "UNKNOWN", ("delta_match_too_distant",)
        )
    call_iv = float(call[implied_volatility_col])
    put_iv = float(put[implied_volatility_col])
    return DeltaRiskReversal(
        target_delta=target_delta,
        call_delta=float(call[delta_col]),
        put_delta=float(put[delta_col]),
        call_implied_volatility=call_iv,
        put_implied_volatility=put_iv,
        call_minus_put_iv=call_iv - put_iv,
        status="OK",
    )


def select_target_expiry(
    expiries: Iterable[object],
    *,
    as_of: object,
    target_days: int = 30,
    minimum_days: int = 7,
) -> pd.Timestamp | None:
    """Choose the eligible expiry nearest a target maturity."""

    if target_days < minimum_days or minimum_days < 0:
        raise ValueError("target_days must be at least minimum_days, both non-negative")
    cutoff = _aware_timestamp(as_of, name="as_of")
    as_of_date = cutoff.date()
    parsed_dates: set[date] = set()
    for expiry in expiries:
        if expiry is None or pd.isna(cast(_MissingScalarInput, expiry)):
            continue
        timestamp = pd.Timestamp(cast(_TimestampInput, expiry))
        parsed_dates.add(timestamp.date())
    parsed = sorted(parsed_dates)
    eligible = [expiry for expiry in parsed if (expiry - as_of_date).days >= minimum_days]
    if not eligible:
        return None
    selected = min(eligible, key=lambda expiry: abs((expiry - as_of_date).days - target_days))
    return pd.Timestamp(selected)


def implied_realized_spread(
    implied_volatility: float | None,
    realized_volatility: float | None,
) -> float | None:
    """Return implied minus realized annualized volatility in decimal units."""

    if implied_volatility is None or realized_volatility is None:
        return None
    if not np.isfinite(implied_volatility) or not np.isfinite(realized_volatility):
        return None
    return float(implied_volatility - realized_volatility)
