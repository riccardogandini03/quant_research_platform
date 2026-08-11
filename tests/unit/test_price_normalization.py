"""Known-shape tests for provider-neutral daily bar normalization."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_raas.normalization.price_bars import normalize_price_frame


def test_normalization_sorts_deduplicates_and_does_not_mutate_input(
    ohlcv_frame: pd.DataFrame,
) -> None:
    correction = ohlcv_frame.iloc[[2]].copy()
    correction["close"] = 100.0
    correction["adjusted_close"] = 100.0
    shuffled = pd.concat(
        [ohlcv_frame.iloc[::-1], correction],
        ignore_index=True,
    )
    original = shuffled.copy(deep=True)

    normalized, report = normalize_price_frame(shuffled)

    assert normalized["session_date"].is_monotonic_increasing
    assert report.input_rows == 7
    assert report.output_rows == 6
    assert report.duplicate_rows_removed == 1
    corrected = normalized.loc[normalized["session_date"] == pd.Timestamp("2024-01-04")]
    assert corrected["close"].item() == pytest.approx(100.0)
    assert_frame_equal(shuffled, original)


def test_normalization_reports_missing_sessions_and_unadjusted_prices(
    ohlcv_frame: pd.DataFrame,
) -> None:
    incomplete = ohlcv_frame.drop(index=2).drop(columns="adjusted_close")
    calendar = pd.bdate_range("2024-01-02", periods=6)
    normalized, report = normalize_price_frame(
        incomplete,
        calendar_sessions=calendar,
    )
    assert report.missing_sessions == 1
    assert any("expected trading sessions" in warning for warning in report.warnings)
    assert any("adjusted_close was unavailable" in warning for warning in report.warnings)
    assert normalized["adjusted_close"].equals(normalized["close"])


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("close", 0.0, "strictly positive"),
        ("volume", -1.0, "cannot be negative"),
        ("open", float("inf"), "must be finite"),
    ],
)
def test_normalization_rejects_impossible_numeric_values(
    ohlcv_frame: pd.DataFrame,
    column: str,
    value: float,
    message: str,
) -> None:
    broken = ohlcv_frame.copy()
    broken.loc[0, column] = value
    with pytest.raises(ValueError, match=message):
        normalize_price_frame(broken)


def test_normalization_rejects_inconsistent_ohlc_range(ohlcv_frame: pd.DataFrame) -> None:
    broken = ohlcv_frame.copy()
    broken.loc[0, "high"] = 99.5
    with pytest.raises(ValueError, match="OHLC range is inconsistent"):
        normalize_price_frame(broken)
