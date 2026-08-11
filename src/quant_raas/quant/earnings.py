"""Earnings-event features built on the generic event-study engine."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_raas.quant.anomalies import volume_zscore
from quant_raas.quant.event_study import EventStudyResult, EventStudySpec, extract_event_windows
from quant_raas.quant.returns import overnight_gap, simple_returns


@dataclass(frozen=True, slots=True)
class EarningsAnalysis:
    """Event-study output augmented with gap, volume, and surprise features."""

    observations: pd.DataFrame
    event_study: EventStudyResult


def surprise_ratio(actual: pd.Series, consensus: pd.Series) -> pd.Series:
    """Calculate ``(actual - consensus) / abs(consensus)``.

    The absolute denominator preserves the intuitive sign when EPS estimates
    are negative. Zero consensus remains missing.
    """

    actual_values = pd.to_numeric(actual, errors="coerce").replace([np.inf, -np.inf], np.nan)
    consensus_values = pd.to_numeric(consensus, errors="coerce").replace([np.inf, -np.inf], np.nan)
    denominator = consensus_values.abs().where(consensus_values != 0.0)
    return actual_values.sub(consensus_values).div(denominator).rename("surprise_ratio")


def earnings_event_features(
    price_bars: pd.DataFrame,
    earnings_events: pd.DataFrame,
    spec: EventStudySpec,
    *,
    open_col: str = "open",
    close_col: str = "close",
    volume_col: str = "volume",
    event_time_col: str = "event_at",
    event_id_col: str = "event_id",
    timing_col: str | None = "timing",
    available_col: str | None = "available_at",
    actual_col: str | None = "actual_eps",
    consensus_col: str | None = "consensus_eps",
    as_of: object | None = None,
    volume_window: int = 63,
    volume_minimum_observations: int = 20,
) -> EarningsAnalysis:
    """Calculate daily earnings-response features with explicit event timing."""

    missing = sorted({open_col, close_col}.difference(price_bars.columns))
    if missing:
        raise ValueError(f"missing price-bar columns: {', '.join(missing)}")
    events = earnings_events.copy()
    if event_id_col not in events:
        events[event_id_col] = events.index.map(str)
    events[event_id_col] = events[event_id_col].astype(str)
    close = pd.to_numeric(price_bars[close_col], errors="coerce")
    daily_returns = simple_returns(close).rename("daily_return")
    event_study = extract_event_windows(
        daily_returns,
        events,
        spec,
        event_time_col=event_time_col,
        event_id_col=event_id_col,
        timing_col=timing_col,
        available_col=available_col,
        as_of=as_of,
    )
    observations = event_study.observations.copy()
    gaps = overnight_gap(price_bars[open_col], close)
    response_sessions = observations["response_session"]
    observations["overnight_gap"] = gaps.reindex(response_sessions).to_numpy()

    if volume_col in price_bars:
        volume_scores = volume_zscore(
            price_bars[volume_col],
            window=volume_window,
            min_periods=volume_minimum_observations,
            lag=1,
        )
        observations["volume_zscore"] = volume_scores.reindex(response_sessions).to_numpy()
    else:
        observations["volume_zscore"] = np.nan

    event_columns = [event_id_col]
    if actual_col is not None and actual_col in events:
        event_columns.append(actual_col)
    if consensus_col is not None and consensus_col in events:
        event_columns.append(consensus_col)
    event_details = events[event_columns].rename(columns={event_id_col: "event_id"})
    observations = observations.merge(
        event_details, on="event_id", how="left", validate="one_to_one"
    )
    if (
        actual_col is not None
        and consensus_col is not None
        and actual_col in observations
        and consensus_col in observations
    ):
        observations["eps_surprise"] = surprise_ratio(
            observations[actual_col], observations[consensus_col]
        )
    else:
        observations["eps_surprise"] = np.nan
    return EarningsAnalysis(observations=observations, event_study=event_study)
