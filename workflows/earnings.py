"""Earnings event-study workflow wrapper."""

from __future__ import annotations

import pandas as pd

from quant_raas.quant.earnings import EarningsAnalysis, earnings_event_features
from quant_raas.quant.event_study import EventStudySpec


def run_earnings_study(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    *,
    spec: EventStudySpec,
    as_of: pd.Timestamp,
) -> EarningsAnalysis:
    """Delegate to the same pure event engine used by historical analysis."""

    return earnings_event_features(prices, events, spec=spec, as_of=as_of)
