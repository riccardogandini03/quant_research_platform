"""Canonicalize daily OHLCV data without losing source provenance."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REQUIRED_PRICE_COLUMNS = ("session_date", "open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class PriceBarQualityReport:
    input_rows: int
    output_rows: int
    duplicate_rows_removed: int
    missing_sessions: int
    warnings: tuple[str, ...]


def normalize_price_frame(
    frame: pd.DataFrame,
    *,
    calendar_sessions: pd.DatetimeIndex | None = None,
) -> tuple[pd.DataFrame, PriceBarQualityReport]:
    """Validate and sort provider bars into the canonical daily shape.

    Raw OHLC values remain raw.  ``adjusted_close`` is kept separately so an
    overnight gap never mixes adjusted history with an executable raw open.
    """

    missing = sorted(set(REQUIRED_PRICE_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"price data is missing columns: {', '.join(missing)}")

    work = frame.copy()
    input_rows = len(work)
    work["session_date"] = pd.to_datetime(work["session_date"], errors="coerce").dt.normalize()
    if work["session_date"].isna().any():
        raise ValueError("session_date contains invalid values")

    numeric_columns = ["open", "high", "low", "close", "volume"]
    if "adjusted_close" in work:
        numeric_columns.append("adjusted_close")
    for column in numeric_columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if work[numeric_columns].isna().any().any():
        bad = work.index[work[numeric_columns].isna().any(axis=1)].tolist()[:5]
        raise ValueError(f"OHLCV values are missing or non-numeric at rows {bad}")
    if not np.isfinite(work[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("OHLCV values must be finite")

    price_columns = [column for column in numeric_columns if column != "volume"]
    if (work[price_columns] <= 0.0).any().any():
        raise ValueError("prices must be strictly positive")
    if (work["volume"] < 0.0).any():
        raise ValueError("volume cannot be negative")
    invalid_range = (work["high"] < work[["open", "low", "close"]].max(axis=1)) | (
        work["low"] > work[["open", "high", "close"]].min(axis=1)
    )
    if invalid_range.any():
        bad = work.index[invalid_range].tolist()[:5]
        raise ValueError(f"OHLC range is inconsistent at rows {bad}")

    duplicate_subset = ["session_date"]
    if "security_id" in work:
        duplicate_subset.insert(0, "security_id")
    duplicate_count = int(work.duplicated(duplicate_subset, keep="last").sum())
    # A provider correction can repeat a session in one response.  The last row
    # is deterministic, while the raw response remains available in the audit lake.
    work = work.drop_duplicates(duplicate_subset, keep="last")
    work = work.sort_values(duplicate_subset, kind="mergesort").reset_index(drop=True)

    warnings: list[str] = []
    missing_sessions = 0
    if calendar_sessions is not None and not work.empty:
        observed = pd.DatetimeIndex(work["session_date"].unique()).normalize()
        expected = pd.DatetimeIndex(calendar_sessions).normalize()
        expected = expected[(expected >= observed.min()) & (expected <= observed.max())]
        missing_sessions = len(expected.difference(observed))
        if missing_sessions:
            warnings.append(f"{missing_sessions} expected trading sessions are absent")

    if "adjusted_close" not in work:
        work["adjusted_close"] = work["close"]
        warnings.append("adjusted_close was unavailable; price returns will be unadjusted")

    report = PriceBarQualityReport(
        input_rows=input_rows,
        output_rows=len(work),
        duplicate_rows_removed=duplicate_count,
        missing_sessions=missing_sessions,
        warnings=tuple(warnings),
    )
    return work, report
