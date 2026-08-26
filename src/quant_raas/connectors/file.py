"""Strict CSV and optional Parquet daily-price ingestion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from quant_raas.common.clock import utc_now
from quant_raas.connectors.base import (
    ProviderDataError,
    ProviderNotConfigured,
    acquisition_started_at,
    require_utc,
)
from quant_raas.domain.enums import DataQualityFlag, DataUsageMode, PriceFailureCategory
from quant_raas.domain.market import (
    PriceBarRequest,
    PriceIngestionResult,
    PriceItemFailure,
)
from quant_raas.normalization.price_bars import normalize_price_frame
from quant_raas.normalization.price_content import (
    NormalizedPriceRow,
    build_price_ingestion_result,
    date_key_effective_at,
    normalize_original_source,
)

FILE_PRICE_FIELD_MAP_VERSION = "file_daily_price_v1"
FILE_REQUIRED_COLUMNS = (
    "provider_identifier",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "currency",
)
FILE_OPTIONAL_COLUMNS = (
    "adjusted_close",
    "effective_at",
    "available_at",
    "source_record_id",
)


class FilePriceProvider:
    """Load one explicitly declared daily-price snapshot file."""

    name = "file"

    def __init__(
        self,
        path: Path,
        *,
        source: str,
        usage_mode: DataUsageMode,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._path = Path(path)
        self._source = normalize_original_source(source)
        self._usage_mode = usage_mode
        self._clock = clock
        if self._source == "lseg" and usage_mode != DataUsageMode.RESEARCH_ONLY:
            raise ProviderNotConfigured("an LSEG-derived file must use research_only handling")

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult:
        started_at = acquisition_started_at(request, self._clock())
        frame = self._prepare_frame(self._read_frame())
        requested_identifiers = {item.provider_identifier for item in request.items}
        selected = frame.loc[
            frame["provider_identifier"].isin(requested_identifiers)
            & (frame["session_date"] >= request.start_date)
            & (frame["session_date"] <= request.end_date)
        ].copy()
        if selected.duplicated(["provider_identifier", "session_date"], keep=False).any():
            raise ProviderDataError(
                "price file contains duplicate provider_identifier/session_date rows"
            )

        rows: list[NormalizedPriceRow] = []
        failures: list[PriceItemFailure] = []
        for item in request.items:
            item_frame = selected.loc[
                selected["provider_identifier"] == item.provider_identifier
            ].copy()
            if item_frame.empty:
                failures.append(_no_data_failure(item.provider_identifier))
                continue
            adjusted_column_present = "adjusted_close" in item_frame.columns
            try:
                normalized, _ = normalize_price_frame(item_frame)
                for raw_row in normalized.to_dict(orient="records"):
                    session_date = pd.Timestamp(raw_row["session_date"]).date()
                    close = float(raw_row["close"])
                    adjusted_close = float(raw_row["adjusted_close"])
                    currency = _optional_text(raw_row.get("currency"))
                    if currency is None or len(currency) != 3 or not currency.isalpha():
                        raise ValueError("invalid currency")
                    supplied_source_record_id = _optional_text(raw_row.get("source_record_id"))
                    supplied_effective_at = _optional_utc_timestamp(
                        raw_row.get("effective_at"),
                        column="effective_at",
                    )
                    supplied_available_at = _optional_utc_timestamp(
                        raw_row.get("available_at"),
                        column="available_at",
                    )
                    source_record_id = supplied_source_record_id or (
                        f"{self._source}:{item.provider_identifier}:"
                        f"{session_date.isoformat()}:{FILE_PRICE_FIELD_MAP_VERSION}"
                    )
                    effective_at = supplied_effective_at or date_key_effective_at(session_date)
                    quality_flags = tuple(
                        flag
                        for flag, required in (
                            (
                                DataQualityFlag.ESTIMATED_TIMESTAMP,
                                supplied_effective_at is None,
                            ),
                            (DataQualityFlag.UNADJUSTED, not adjusted_column_present),
                        )
                        if required
                    )
                    rows.append(
                        NormalizedPriceRow(
                            security_id=item.security_id,
                            provider_identifier=item.provider_identifier,
                            source_record_id=source_record_id,
                            session_date=session_date,
                            effective_at=effective_at,
                            source_available_at=supplied_available_at,
                            open=float(raw_row["open"]),
                            high=float(raw_row["high"]),
                            low=float(raw_row["low"]),
                            close=close,
                            adjusted_close=adjusted_close,
                            volume=float(raw_row["volume"]),
                            currency=currency.upper(),
                            adjustment_factor=adjusted_close / close,
                            total_return_factor=None,
                            source=self._source,
                            usage_mode=self._usage_mode,
                            quality_flags=quality_flags,
                            field_map_version=FILE_PRICE_FIELD_MAP_VERSION,
                        )
                    )
            except ProviderDataError:
                raise
            except (TypeError, ValueError):
                raise ProviderDataError("price file failed daily-price validation") from None

        completed_at = max(
            require_utc(self._clock(), field_name="acquisition clock"),
            started_at,
        )
        try:
            return build_price_ingestion_result(
                provider=self.name,
                original_source=self._source,
                dataset="daily_price_bar",
                request=request,
                field_map_version=FILE_PRICE_FIELD_MAP_VERSION,
                usage_mode=self._usage_mode,
                rows=tuple(rows),
                failures=tuple(failures),
                started_at=started_at,
                completed_at=completed_at,
            )
        except ProviderDataError:
            raise
        except (TypeError, ValueError):
            raise ProviderDataError("price file failed daily-price validation") from None

    def _read_frame(self) -> pd.DataFrame:
        suffix = self._path.suffix.lower()
        if suffix == ".csv":
            try:
                return pd.read_csv(self._path)
            except Exception:
                raise ProviderDataError("CSV price file could not be read") from None
        if suffix == ".parquet":
            try:
                return pd.read_parquet(self._path)
            except ImportError:
                raise ProviderNotConfigured(
                    "Install the 'parquet' extra to read Parquet price files"
                ) from None
            except Exception:
                raise ProviderDataError("Parquet price file could not be read") from None
        raise ProviderDataError("price file must use .csv or .parquet")

    @staticmethod
    def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
        normalized_columns = [str(column).strip().casefold() for column in frame.columns]
        if len(normalized_columns) != len(set(normalized_columns)):
            raise ProviderDataError("price file contains duplicate normalized columns")
        frame = frame.copy()
        frame.columns = normalized_columns
        missing = sorted(set(FILE_REQUIRED_COLUMNS).difference(frame.columns))
        if missing:
            raise ProviderDataError(f"price file is missing required columns: {', '.join(missing)}")

        try:
            provider_identifiers = frame["provider_identifier"].map(_required_identifier)
        except (TypeError, ValueError):
            raise ProviderDataError("price file provider_identifier failed validation") from None
        try:
            parsed_session_dates = pd.to_datetime(
                frame["session_date"],
                format="%Y-%m-%d",
                exact=True,
                errors="raise",
            )
        except (TypeError, ValueError):
            raise ProviderDataError("price file session_date failed validation") from None
        if parsed_session_dates.isna().any():
            raise ProviderDataError("price file session_date failed validation")
        return frame.assign(
            provider_identifier=provider_identifiers,
            session_date=parsed_session_dates.dt.date,
        )


def _required_identifier(value: object) -> str:
    if value is None or (not isinstance(value, str) and bool(pd.isna(cast(Any, value)))):
        raise ValueError("missing identifier")
    identifier = str(value).strip()
    if not 1 <= len(identifier) <= 128:
        raise ValueError("invalid identifier")
    return identifier


def _optional_text(value: object) -> str | None:
    if value is None or (not isinstance(value, str) and bool(pd.isna(cast(Any, value)))):
        return None
    text_value = str(value).strip()
    return text_value or None


def _optional_utc_timestamp(value: object, *, column: str) -> datetime | None:
    text_value = _optional_text(value)
    if text_value is None:
        return None
    try:
        parsed = pd.Timestamp(text_value)
    except (TypeError, ValueError):
        raise ProviderDataError("price file timestamps failed validation") from None
    if parsed.tzinfo is None:
        raise ProviderDataError(f"{column} must include an explicit timezone")
    return parsed.tz_convert("UTC").to_pydatetime()


def _no_data_failure(provider_identifier: str) -> PriceItemFailure:
    return PriceItemFailure(
        provider_identifier=provider_identifier,
        category=PriceFailureCategory.NO_DATA,
        message=f"{provider_identifier}: no rows in requested file subset",
    )
