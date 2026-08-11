"""Statistical inference primitives for auditable quantitative research."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


@dataclass(frozen=True, slots=True)
class StatisticalTestResult:
    """Typed result that never represents an invalid test as a significant one."""

    method: str
    observations: int
    estimate: float | None
    standard_error: float | None
    statistic: float | None
    p_value: float | None
    confidence_interval: tuple[float, float] | None
    valid: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Moving-block bootstrap estimate for a serially dependent sample."""

    observations: int
    estimate: float | None
    standard_error: float | None
    confidence_interval: tuple[float, float] | None
    block_size: int
    resamples: int
    valid: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FDRResult:
    """Benjamini-Hochberg adjusted p-values in original input order."""

    adjusted_p_values: tuple[float | None, ...]
    rejected: tuple[bool, ...]
    alpha: float
    hypotheses: int


@dataclass(frozen=True, slots=True)
class DescriptiveStatistics:
    observations: int
    mean: float | None
    median: float | None
    standard_deviation: float | None
    win_rate: float | None
    minimum: float | None
    maximum: float | None


def _clean(values: pd.Series | Iterable[float]) -> np.ndarray:
    series = pd.Series(values, dtype="float64")
    return series.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)


def _invalid_result(method: str, values: np.ndarray, warning: str) -> StatisticalTestResult:
    estimate = float(values.mean()) if values.size else None
    return StatisticalTestResult(
        method, len(values), estimate, None, None, None, None, False, (warning,)
    )


def _has_effectively_zero_variance(values: np.ndarray, sample_std: float) -> bool:
    """Treat dispersion below floating-point resolution as zero variance."""

    scale = max(1.0, float(np.max(np.abs(values))))
    absolute_tolerance = float(np.finfo(float).eps * scale)
    return not np.isfinite(sample_std) or math.isclose(
        sample_std,
        0.0,
        rel_tol=0.0,
        abs_tol=absolute_tolerance,
    )


def descriptive_statistics(
    values: pd.Series | Iterable[float],
    *,
    ddof: int = 1,
) -> DescriptiveStatistics:
    """Summarize finite values; missing observations never count as losses."""

    if ddof < 0:
        raise ValueError("ddof cannot be negative")
    clean = _clean(values)
    if clean.size == 0:
        return DescriptiveStatistics(0, None, None, None, None, None, None)
    standard_deviation = float(np.std(clean, ddof=ddof)) if clean.size > ddof else None
    return DescriptiveStatistics(
        observations=len(clean),
        mean=float(np.mean(clean)),
        median=float(np.median(clean)),
        standard_deviation=standard_deviation,
        win_rate=float(np.mean(clean > 0.0)),
        minimum=float(np.min(clean)),
        maximum=float(np.max(clean)),
    )


def mean_test_iid(
    values: pd.Series | Iterable[float],
    *,
    null_mean: float = 0.0,
    minimum_observations: int = 20,
    confidence: float = 0.95,
) -> StatisticalTestResult:
    """Two-sided one-sample t-test under an IID assumption.

    This is suitable for controlled exploratory work.  Time-series research
    should generally prefer :func:`mean_test_hac` or the block bootstrap.
    """

    if minimum_observations < 2:
        raise ValueError("minimum_observations must be at least two")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    clean = _clean(values)
    if clean.size < minimum_observations:
        return _invalid_result("iid_t", clean, "insufficient_observations")
    sample_std = float(np.std(clean, ddof=1))
    if _has_effectively_zero_variance(clean, sample_std):
        return _invalid_result("iid_t", clean, "zero_sample_variance")
    standard_error = sample_std / math.sqrt(clean.size)
    statistic = (float(np.mean(clean)) - null_mean) / standard_error
    degrees_of_freedom = clean.size - 1
    p_value = float(2.0 * stats.t.sf(abs(statistic), df=degrees_of_freedom))
    critical = float(stats.t.ppf((1.0 + confidence) / 2.0, df=degrees_of_freedom))
    estimate = float(np.mean(clean))
    return StatisticalTestResult(
        method="iid_t",
        observations=len(clean),
        estimate=estimate,
        standard_error=standard_error,
        statistic=statistic,
        p_value=p_value,
        confidence_interval=(
            estimate - critical * standard_error,
            estimate + critical * standard_error,
        ),
        valid=True,
    )


def mean_test_hac(
    values: pd.Series | Iterable[float],
    *,
    null_mean: float = 0.0,
    max_lags: int | None = None,
    minimum_observations: int = 20,
    confidence: float = 0.95,
) -> StatisticalTestResult:
    """Test a mean with Newey-West/HAC standard errors and a constant model."""

    if minimum_observations < 2:
        raise ValueError("minimum_observations must be at least two")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    clean = _clean(values)
    if clean.size < minimum_observations:
        return _invalid_result("hac_mean", clean, "insufficient_observations")
    sample_std = float(np.std(clean, ddof=1))
    if _has_effectively_zero_variance(clean, sample_std):
        return _invalid_result("hac_mean", clean, "zero_sample_variance")
    selected_lags = (
        math.floor(4.0 * (clean.size / 100.0) ** (2.0 / 9.0)) if max_lags is None else max_lags
    )
    if selected_lags < 0:
        raise ValueError("max_lags cannot be negative")
    selected_lags = min(selected_lags, clean.size - 1)
    fitted = sm.OLS(clean, np.ones((clean.size, 1), dtype=float)).fit(
        cov_type="HAC", cov_kwds={"maxlags": selected_lags}, use_t=True
    )
    estimate = float(fitted.params[0])
    standard_error = float(fitted.bse[0])
    if not np.isfinite(standard_error) or standard_error == 0.0:
        return _invalid_result("hac_mean", clean, "invalid_hac_standard_error")
    statistic = (estimate - null_mean) / standard_error
    degrees_of_freedom = clean.size - 1
    p_value = float(2.0 * stats.t.sf(abs(statistic), df=degrees_of_freedom))
    critical = float(stats.t.ppf((1.0 + confidence) / 2.0, df=degrees_of_freedom))
    return StatisticalTestResult(
        method=f"hac_mean(max_lags={selected_lags})",
        observations=len(clean),
        estimate=estimate,
        standard_error=standard_error,
        statistic=statistic,
        p_value=p_value,
        confidence_interval=(
            estimate - critical * standard_error,
            estimate + critical * standard_error,
        ),
        valid=True,
    )


def block_bootstrap_mean(
    values: pd.Series | Iterable[float],
    *,
    block_size: int | None = None,
    resamples: int = 2_000,
    minimum_observations: int = 20,
    confidence: float = 0.95,
    seed: int | None = None,
) -> BootstrapResult:
    """Estimate a mean CI using a circular moving-block bootstrap."""

    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if minimum_observations < 2:
        raise ValueError("minimum_observations must be at least two")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must lie strictly between zero and one")
    clean = _clean(values)
    selected_block = max(1, round(clean.size ** (1.0 / 3.0))) if block_size is None else block_size
    if selected_block < 1:
        raise ValueError("block_size must be positive")
    if clean.size < minimum_observations:
        return BootstrapResult(
            len(clean),
            float(clean.mean()) if clean.size else None,
            None,
            None,
            selected_block,
            resamples,
            False,
            ("insufficient_observations",),
        )
    selected_block = min(selected_block, clean.size)
    blocks_needed = math.ceil(clean.size / selected_block)
    offsets = np.arange(selected_block)
    rng = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    for sample_number in range(resamples):
        starts = rng.integers(0, clean.size, size=blocks_needed)
        indices = ((starts[:, None] + offsets[None, :]) % clean.size).ravel()[: clean.size]
        means[sample_number] = float(clean[indices].mean())
    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(means, [tail, 1.0 - tail])
    return BootstrapResult(
        observations=len(clean),
        estimate=float(clean.mean()),
        standard_error=float(np.std(means, ddof=1)),
        confidence_interval=(float(lower), float(upper)),
        block_size=selected_block,
        resamples=resamples,
        valid=True,
    )


def benjamini_hochberg(
    p_values: Iterable[float | None],
    *,
    alpha: float = 0.05,
) -> FDRResult:
    """Apply Benjamini-Hochberg FDR control while preserving missing p-values."""

    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must lie strictly between zero and one")
    raw = list(p_values)
    valid: list[tuple[int, float]] = []
    for index, value in enumerate(raw):
        if value is None or pd.isna(value):
            continue
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("p-values must lie between zero and one")
        valid.append((index, numeric))
    adjusted: list[float | None] = [None] * len(raw)
    rejected = [False] * len(raw)
    if not valid:
        return FDRResult(tuple(adjusted), tuple(rejected), alpha, 0)
    ordered = sorted(valid, key=lambda item: item[1])
    count = len(ordered)
    running_minimum = 1.0
    for rank_from_end in range(count, 0, -1):
        original_index, p_value = ordered[rank_from_end - 1]
        candidate = p_value * count / rank_from_end
        running_minimum = min(running_minimum, candidate)
        adjusted[original_index] = min(1.0, running_minimum)
    for index, value in enumerate(adjusted):
        rejected[index] = value is not None and value <= alpha
    return FDRResult(tuple(adjusted), tuple(rejected), alpha, count)
