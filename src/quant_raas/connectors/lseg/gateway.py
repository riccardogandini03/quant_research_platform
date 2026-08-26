"""Bounded, desktop-only access to the optional LSEG data SDK."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from numbers import Real
from typing import Literal, Never, Protocol, cast

import pandas as pd

from quant_raas.connectors.base import (
    ProviderDataError,
    ProviderEntitlementError,
    ProviderError,
    ProviderNotConfigured,
    ProviderQuotaError,
    ProviderSessionError,
)
from quant_raas.domain.enums import PriceFailureCategory
from quant_raas.domain.market import PriceItemFailure

LSEG_PRICE_FIELD_MAP_VERSION = "lseg_interday_price_v1"
LSEG_RAW_FIELD_MAP = {
    "OPEN_PRC": "open",
    "HIGH_1": "high",
    "LOW_1": "low",
    "TRDPRC_1": "close",
    "ACVOL_UNS": "volume",
}
LSEG_RAW_ADJUSTMENTS = ("unadjusted",)
LSEG_ADJUSTED_FIELDS = ("TRDPRC_1",)
LSEG_ADJUSTED_ADJUSTMENTS = (
    "exchangeCorrection",
    "manualCorrection",
    "CCH",
    "CRE",
    "RPO",
    "RTS",
)
LSEG_CURRENCY_FIELDS = ("TR.PriceClose.currency",)
LSEG_CURRENCY_COLUMN_ALIASES = (
    "TR.PriceClose.currency",
    "Currency",
)
LSEG_INTERVAL = "1D"
LSEG_MAX_CHUNK_DAYS = 366


class LsegHeaderType(Protocol):
    NAME: object


class LsegDataModule(Protocol):
    HeaderType: LsegHeaderType

    def open_session(self, *, name: str) -> object | None: ...

    def close_session(self) -> None: ...

    def get_data(self, *, universe: list[str], fields: list[str]) -> pd.DataFrame: ...

    def get_history(
        self,
        *,
        universe: list[str],
        fields: list[str],
        interval: str,
        start: str,
        end: str,
        adjustments: list[str],
        header_type: object,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True, slots=True)
class LsegDailyChunk:
    start_date: date
    end_date: date
    raw_frame: pd.DataFrame
    adjusted_frame: pd.DataFrame


@dataclass(frozen=True, slots=True)
class LsegItemResult:
    provider_identifier: str
    currency_frame: pd.DataFrame
    chunks: tuple[LsegDailyChunk, ...]


@dataclass(frozen=True, slots=True)
class LsegGatewayResult:
    items: tuple[LsegItemResult, ...]
    failures: tuple[PriceItemFailure, ...] = ()


class LsegPriceGateway(Protocol):
    def fetch_daily_prices(
        self,
        provider_identifiers: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> LsegGatewayResult: ...


def load_lseg_data() -> LsegDataModule:
    try:
        module = importlib.import_module("lseg.data")
    except ImportError:
        raise ProviderNotConfigured(
            "Install the 'lseg' extra to use the Workspace desktop connector"
        ) from None
    return cast(LsegDataModule, module)


def daily_chunks(start_date: date, end_date: date) -> tuple[tuple[date, date], ...]:
    chunks: list[tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=365), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return tuple(chunks)


def _is_open_state(open_state: object) -> bool:
    state_name = getattr(open_state, "name", open_state)
    token = str(state_name).strip().lower()
    return token == "open" or token.endswith(".open")


SdkFailureKind = Literal["entitlement", "quota", "session", "invalid_identifier"]


def _classify_token(value: object) -> SdkFailureKind | None:
    parts = [str(value)]
    for attribute in ("name", "value"):
        nested = getattr(value, attribute, None)
        if nested is not None and nested is not value:
            parts.append(str(nested))
    token = " ".join(parts).casefold().replace("-", "_").replace(" ", "_")
    if token == "403" or any(
        marker in token for marker in ("permission", "entitlement", "forbidden", "unauthoriz")
    ):
        return "entitlement"
    if token == "429" or any(
        marker in token for marker in ("quota", "rate_limit", "too_many_requests")
    ):
        return "quota"
    if any(marker in token for marker in ("connection", "session", "proxy", "closed")):
        return "session"
    if "invalid" in token and any(marker in token for marker in ("instrument", "identifier")):
        return "invalid_identifier"
    return None


def _classify_sdk_exception(error: Exception) -> SdkFailureKind | None:
    for attribute in ("http_status", "status_code", "code"):
        value = getattr(error, attribute, None)
        if value is not None and (classification := _classify_token(value)) is not None:
            return classification

    fallback = f"{type(error).__name__} {error}"
    classification = _classify_token(fallback)
    if classification == "invalid_identifier":
        return None
    return classification


def _raise_provider_error(error: Exception) -> Never:
    classification = _classify_sdk_exception(error)
    if classification == "entitlement":
        raise ProviderEntitlementError("LSEG desktop request is not entitled") from None
    if classification == "quota":
        raise ProviderQuotaError("LSEG desktop request exceeded a provider limit") from None
    if classification == "session":
        raise ProviderSessionError("LSEG desktop session failed") from None
    raise ProviderError("LSEG desktop request failed") from None


_FALSE_INDICATOR_TEXT = frozenset(
    {"", "0", "false", "none", "no", "off", "ok", "complete", "completed", "success"}
)
_TRUE_INDICATOR_TEXT = frozenset({"1", "true", "yes", "on"})
_NEGATIVE_TRUNCATION_MARKERS = (
    "truncation_not_reached",
    "not_reached_truncation",
    "without_truncation",
    "not_truncated",
    "non_truncated",
    "no_truncation",
    "not_truncation",
    "untruncated",
    "not_trunc",
    "nottrunc",
    "non_trunc",
    "nontrunc",
    "no_trunc",
    "without_trunc",
    "untrunc",
)
_POSITIVE_TRUNCATION_MARKERS = (
    "truncation_reached",
    "truncated",
    "truncation",
)
_NEGATIVE_LIMIT_MARKERS = (
    "limit_not_reached",
    "not_reached_limit",
    "without_limitation",
    "within_limit",
    "not_limited",
    "non_limited",
    "no_limitation",
    "not_limitation",
    "unlimited",
    "not_limit",
    "notlimit",
    "non_limit",
    "nonlimit",
    "no_limit",
    "without_limit",
    "unlimit",
)
_POSITIVE_LIMIT_MARKERS = (
    "limit_reached",
    "reached_limit",
    "limit_exceeded",
    "exceeded_limit",
    "limited",
)


def _normalized_indicator_text(value: str) -> str:
    return "_".join(value.strip().casefold().replace("-", "_").split())


def _concept_has_affirmative_claim(
    token: str,
    *,
    negative_markers: Sequence[str],
    positive_markers: Sequence[str],
) -> bool:
    unnegated = token
    for marker in negative_markers:
        unnegated = unnegated.replace(marker, "")
    return any(marker in unnegated for marker in positive_markers)


def _text_indicator_is_affirmative(value: str) -> bool:
    token = _normalized_indicator_text(value)
    if token in _FALSE_INDICATOR_TEXT:
        return False
    if token in _TRUE_INDICATOR_TEXT:
        return True
    try:
        return float(token) > 0
    except ValueError:
        return _concept_has_affirmative_claim(
            token,
            negative_markers=_NEGATIVE_LIMIT_MARKERS,
            positive_markers=_POSITIVE_LIMIT_MARKERS,
        ) or _concept_has_affirmative_claim(
            token,
            negative_markers=_NEGATIVE_TRUNCATION_MARKERS,
            positive_markers=_POSITIVE_TRUNCATION_MARKERS,
        )


def _positive_indicator(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Real):
        return float(value) > 0
    if isinstance(value, str):
        return _text_indicator_is_affirmative(value)

    item = getattr(value, "item", None)
    if callable(item) and getattr(value, "ndim", None) == 0:
        try:
            scalar = item()
        except (TypeError, ValueError):
            return False
        if scalar is not value:
            return _positive_indicator(scalar)
    return False


def _frame_reports_limit_or_truncation(frame: pd.DataFrame) -> bool:
    for key, value in frame.attrs.items():
        key_token = str(key).casefold()
        if ("limit" in key_token or "trunc" in key_token) and _positive_indicator(value):
            return True
        if "status" in key_token and _positive_indicator(value):
            return True
    return False


def _validate_history_frame(frame: pd.DataFrame) -> None:
    if _frame_reports_limit_or_truncation(frame):
        raise ProviderDataError("LSEG history response reported a limit or truncation") from None


class LsegDesktopGateway:
    def __init__(
        self,
        *,
        session_mode: str | None,
        module_loader: Callable[[], LsegDataModule] = load_lseg_data,
    ) -> None:
        self._session_mode = session_mode
        self._module_loader = module_loader
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open

    def fetch_daily_prices(
        self,
        provider_identifiers: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> LsegGatewayResult:
        if self._session_mode != "workspace_desktop":
            raise ProviderNotConfigured("LSEG Workspace desktop mode is not configured") from None

        module = self._module_loader()
        opened = False
        try:
            try:
                open_state = module.open_session(name="desktop.workspace")
            except Exception as error:
                _raise_provider_error(error)
            opened = True
            self._is_open = True
            if open_state is not None and not _is_open_state(open_state):
                raise ProviderSessionError("LSEG desktop session did not open") from None

            chunks = daily_chunks(start_date, end_date)
            items: list[LsegItemResult] = []
            failures: list[PriceItemFailure] = []
            for provider_identifier in provider_identifiers:
                try:
                    currency_frame = module.get_data(
                        universe=[provider_identifier],
                        fields=list(LSEG_CURRENCY_FIELDS),
                    )
                    item_chunks: list[LsegDailyChunk] = []
                    for chunk_start, chunk_end in chunks:
                        raw_frame = module.get_history(
                            universe=[provider_identifier],
                            fields=list(LSEG_RAW_FIELD_MAP),
                            interval=LSEG_INTERVAL,
                            start=chunk_start.isoformat(),
                            end=chunk_end.isoformat(),
                            adjustments=list(LSEG_RAW_ADJUSTMENTS),
                            header_type=module.HeaderType.NAME,
                        )
                        _validate_history_frame(raw_frame)
                        adjusted_frame = module.get_history(
                            universe=[provider_identifier],
                            fields=list(LSEG_ADJUSTED_FIELDS),
                            interval=LSEG_INTERVAL,
                            start=chunk_start.isoformat(),
                            end=chunk_end.isoformat(),
                            adjustments=list(LSEG_ADJUSTED_ADJUSTMENTS),
                            header_type=module.HeaderType.NAME,
                        )
                        _validate_history_frame(adjusted_frame)
                        item_chunks.append(
                            LsegDailyChunk(
                                start_date=chunk_start,
                                end_date=chunk_end,
                                raw_frame=raw_frame,
                                adjusted_frame=adjusted_frame,
                            )
                        )
                except ProviderError:
                    raise
                except Exception as error:
                    if _classify_sdk_exception(error) == "invalid_identifier":
                        failures.append(
                            PriceItemFailure(
                                provider_identifier=provider_identifier,
                                category=PriceFailureCategory.INVALID_IDENTIFIER,
                                message=f"Invalid LSEG identifier: {provider_identifier}",
                            )
                        )
                        continue
                    _raise_provider_error(error)
                if not any(not chunk.raw_frame.empty for chunk in item_chunks):
                    failures.append(
                        PriceItemFailure(
                            provider_identifier=provider_identifier,
                            category=PriceFailureCategory.NO_DATA,
                            message=f"No LSEG history data for {provider_identifier}",
                        )
                    )
                    continue
                items.append(
                    LsegItemResult(
                        provider_identifier=provider_identifier,
                        currency_frame=currency_frame,
                        chunks=tuple(item_chunks),
                    )
                )
            return LsegGatewayResult(items=tuple(items), failures=tuple(failures))
        finally:
            if opened:
                try:
                    module.close_session()
                except Exception as error:
                    _raise_provider_error(error)
                finally:
                    self._is_open = False
