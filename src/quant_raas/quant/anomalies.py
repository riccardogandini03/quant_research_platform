"""Backward-looking anomaly scores and factor-residual return models."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class AbnormalReturnResult:
    """Outputs of a rolling market/factor model.

    At timestamp ``t`` every coefficient and residual-volatility estimate is
    fitted exclusively with observations through ``t-1``. Current factor
    returns may be used to form the contemporaneous expected return.
    """

    expected_return: pd.Series
    residual_return: pd.Series
    residual_volatility: pd.Series
    abnormal_score: pd.Series
    coefficients: pd.DataFrame
    warnings: tuple[str, ...] = ()


def _numeric_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)


def rolling_zscore(
    values: pd.Series,
    *,
    window: int = 63,
    min_periods: int | None = None,
    lag: int = 1,
    ddof: int = 1,
) -> pd.Series:
    """Score each value against a trailing baseline ending ``lag`` rows earlier."""

    if window < 2 or lag < 0 or ddof < 0:
        raise ValueError("window must exceed one; lag/ddof cannot be negative")
    required = window if min_periods is None else min_periods
    if required <= ddof or required > window:
        raise ValueError("min_periods must exceed ddof and not exceed window")
    clean = _numeric_series(values)
    history = clean.shift(lag)
    mean = history.rolling(window, min_periods=required).mean()
    standard_deviation = history.rolling(window, min_periods=required).std(ddof=ddof)
    return (
        clean.sub(mean)
        .div(standard_deviation.where(standard_deviation > 0.0))
        .rename(f"{values.name or 'value'}_zscore")
    )


def volume_zscore(
    volume: pd.Series,
    *,
    window: int = 63,
    min_periods: int | None = None,
    lag: int = 1,
) -> pd.Series:
    """Score log-volume against history, leaving missing/negative volume missing."""

    clean = _numeric_series(volume).where(lambda value: value >= 0.0)
    logged = np.log1p(clean)
    logged.name = "log_volume"
    return rolling_zscore(logged, window=window, min_periods=min_periods, lag=lag)


def fit_abnormal_return_model(
    asset_returns: pd.Series,
    factor_returns: pd.DataFrame,
    *,
    window: int = 126,
    minimum_observations: int = 63,
    add_intercept: bool = True,
    residual_ddof: int | None = None,
) -> AbnormalReturnResult:
    """Fit a rolling OLS factor model with a strict one-row estimation lag."""

    if window < 2:
        raise ValueError("window must be at least two")
    if minimum_observations < 2 or minimum_observations > window:
        raise ValueError("minimum_observations must be in [2, window]")
    if asset_returns.index.has_duplicates or factor_returns.index.has_duplicates:
        raise ValueError("return indices must be unique")
    if (
        not asset_returns.index.is_monotonic_increasing
        or not factor_returns.index.is_monotonic_increasing
    ):
        raise ValueError("return indices must be sorted")
    if factor_returns.columns.has_duplicates or factor_returns.shape[1] == 0:
        raise ValueError("factor_returns must have at least one uniquely named column")

    y = _numeric_series(asset_returns)
    x = (
        factor_returns.reindex(y.index)
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    coefficient_names = [
        *(["intercept"] if add_intercept else []),
        *(str(column) for column in x.columns),
    ]
    expected = pd.Series(np.nan, index=y.index, dtype="float64", name="expected_return")
    residual = pd.Series(np.nan, index=y.index, dtype="float64", name="residual_return")
    residual_vol = pd.Series(np.nan, index=y.index, dtype="float64", name="residual_volatility")
    coefficients = pd.DataFrame(np.nan, index=y.index, columns=coefficient_names, dtype="float64")
    warning_set: set[str] = set()

    predictor_count = len(coefficient_names)
    required = max(minimum_observations, predictor_count + 1)
    if required > window:
        raise ValueError("window is too short for the number of model parameters")
    effective_ddof = predictor_count if residual_ddof is None else residual_ddof
    if effective_ddof < 0:
        raise ValueError("residual_ddof cannot be negative")

    for position in range(len(y)):
        start = max(0, position - window)
        training = pd.concat(
            [y.iloc[start:position].rename("asset"), x.iloc[start:position]], axis=1
        ).dropna()
        if len(training) < required:
            continue
        current_factors = x.iloc[position]
        if current_factors.isna().any():
            continue
        training_x = training[x.columns].to_numpy(dtype=float)
        current_x = current_factors.to_numpy(dtype=float)
        if add_intercept:
            training_x = np.column_stack([np.ones(len(training_x)), training_x])
            current_x = np.concatenate([[1.0], current_x])
        coefficients_array, _, rank, _ = np.linalg.lstsq(
            training_x, training["asset"].to_numpy(dtype=float), rcond=None
        )
        if rank < training_x.shape[1]:
            warning_set.add("rank_deficient_training_windows_skipped")
            continue
        training_residuals = (
            training["asset"].to_numpy(dtype=float) - training_x @ coefficients_array
        )
        if len(training_residuals) <= effective_ddof:
            continue
        sigma = float(np.std(training_residuals, ddof=effective_ddof))
        prediction = float(current_x @ coefficients_array)
        index_value = y.index[position]
        coefficients.loc[index_value] = coefficients_array
        expected.loc[index_value] = prediction
        if np.isfinite(sigma) and sigma > 0.0:
            residual_vol.loc[index_value] = sigma
        actual = y.iloc[position]
        if pd.notna(actual):
            residual.loc[index_value] = float(actual - prediction)

    abnormal_score = residual.div(residual_vol).rename("abnormal_score")
    return AbnormalReturnResult(
        expected_return=expected,
        residual_return=residual,
        residual_volatility=residual_vol,
        abnormal_score=abnormal_score,
        coefficients=coefficients,
        warnings=tuple(sorted(warning_set)),
    )


def anomaly_flags(scores: pd.Series, *, threshold: float = 2.0) -> pd.Series:
    """Return nullable flags; unavailable scores remain ``pd.NA`` rather than false."""

    if threshold <= 0.0:
        raise ValueError("threshold must be positive")
    clean = _numeric_series(scores)
    flags = pd.Series(pd.NA, index=clean.index, dtype="boolean", name="is_anomaly")
    available = clean.notna()
    flags.loc[available] = clean.loc[available].abs() >= threshold
    return flags
