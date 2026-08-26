from __future__ import annotations

import traceback
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

import pandas as pd
import pytest

from quant_raas.connectors.base import (
    ProviderDataError,
    ProviderEntitlementError,
    ProviderError,
    ProviderNotConfigured,
    ProviderQuotaError,
    ProviderSessionError,
)
from quant_raas.connectors.lseg.gateway import (
    LSEG_ADJUSTED_ADJUSTMENTS,
    LSEG_RAW_ADJUSTMENTS,
    LsegDesktopGateway,
    daily_chunks,
)
from quant_raas.domain.enums import PriceFailureCategory

SENTINEL = "licensed-payload-secret-sentinel"


class FakeHeaderType:
    NAME = "header-name"


class FakeSdkError(RuntimeError):
    def __init__(
        self,
        message: str = SENTINEL,
        *,
        code: object | None = None,
        status_code: object | None = None,
        http_status: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.http_status = http_status


class FakeLsegDataModule:
    HeaderType = FakeHeaderType

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.open_state: object | None = "Open"
        self.open_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.currency_errors: dict[str, BaseException] = {}
        self.history_errors: dict[tuple[str, tuple[str, ...], str], BaseException] = {}
        self.currency_frames: dict[str, pd.DataFrame] = {}
        self.history_frames: dict[tuple[str, tuple[str, ...], str], pd.DataFrame] = {}

    def open_session(self, *, name: str) -> object | None:
        self.calls.append(("open", {"name": name}))
        if self.open_error is not None:
            raise self.open_error
        return self.open_state

    def close_session(self) -> None:
        self.calls.append(("close", {}))
        if self.close_error is not None:
            raise self.close_error

    def get_data(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("currency", kwargs))
        ric = kwargs["universe"][0]
        if error := self.currency_errors.get(ric):
            raise error
        return self.currency_frames.get(ric, pd.DataFrame({"Currency": ["USD"]}))

    def get_history(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(("history", kwargs))
        ric = kwargs["universe"][0]
        key = (ric, tuple(kwargs["adjustments"]), kwargs["start"])
        if error := self.history_errors.get(key):
            raise error
        return self.history_frames.get(key, pd.DataFrame({"value": [1.0]}))


def _gateway(
    module: FakeLsegDataModule,
    *,
    session_mode: str | None = "workspace_desktop",
) -> LsegDesktopGateway:
    return LsegDesktopGateway(session_mode=session_mode, module_loader=lambda: module)


def _assert_sanitized(error: BaseException) -> None:
    assert SENTINEL not in str(error)
    assert SENTINEL not in "".join(traceback.format_exception(error))


def test_gateway_rejects_non_desktop_mode_before_loading_sdk() -> None:
    loads = 0

    def loader() -> FakeLsegDataModule:
        nonlocal loads
        loads += 1
        return FakeLsegDataModule()

    gateway = LsegDesktopGateway(session_mode="platform", module_loader=loader)

    with pytest.raises(ProviderNotConfigured):
        gateway.fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert loads == 0
    assert gateway.is_open is False


def test_gateway_import_is_lazy_and_missing_sdk_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_imports: list[str] = []

    def missing_import(name: str) -> Any:
        attempted_imports.append(name)
        raise ImportError(SENTINEL)

    monkeypatch.setattr(
        "quant_raas.connectors.lseg.gateway.importlib.import_module", missing_import
    )
    gateway = LsegDesktopGateway(session_mode="workspace_desktop")
    assert attempted_imports == []

    with pytest.raises(ProviderNotConfigured) as exc_info:
        gateway.fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert attempted_imports == ["lseg.data"]
    _assert_sanitized(exc_info.value)


def test_gateway_opens_and_closes_once_per_request() -> None:
    module = FakeLsegDataModule()
    gateway = _gateway(module)

    result = gateway.fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert len(result.items) == 1
    assert [name for name, _ in module.calls].count("open") == 1
    assert [name for name, _ in module.calls].count("close") == 1
    assert module.calls[0] == ("open", {"name": "desktop.workspace"})
    assert module.calls[-1] == ("close", {})
    assert gateway.is_open is False


@pytest.mark.parametrize("failure_point", ["currency", "history"])
def test_gateway_closes_after_currency_or_history_exception(failure_point: str) -> None:
    module = FakeLsegDataModule()
    if failure_point == "currency":
        module.currency_errors["RIC"] = FakeSdkError()
    else:
        module.history_errors[("RIC", LSEG_RAW_ADJUSTMENTS, "2024-01-01")] = FakeSdkError()

    with pytest.raises(ProviderError):
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert [name for name, _ in module.calls].count("close") == 1
    assert module.calls[-1] == ("close", {})


def test_gateway_rejects_a_returned_closed_session() -> None:
    module = FakeLsegDataModule()
    module.open_state = "Closed"
    gateway = _gateway(module)

    with pytest.raises(ProviderSessionError) as exc_info:
        gateway.fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert module.calls == [
        ("open", {"name": "desktop.workspace"}),
        ("close", {}),
    ]
    assert gateway.is_open is False
    _assert_sanitized(exc_info.value)


def test_close_failure_is_sanitized_and_is_open_resets() -> None:
    module = FakeLsegDataModule()
    module.close_error = FakeSdkError(SENTINEL)
    gateway = _gateway(module)

    with pytest.raises(ProviderError) as exc_info:
        gateway.fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert type(exc_info.value) is ProviderError
    assert str(exc_info.value) == "LSEG desktop request failed"
    assert gateway.is_open is False
    _assert_sanitized(exc_info.value)


def test_gateway_uses_exact_fields_adjustments_header_type_and_sequential_ric_order() -> None:
    module = FakeLsegDataModule()

    _gateway(module).fetch_daily_prices(("RIC-1", "RIC-2"), date(2024, 1, 1), date(2025, 1, 1))

    expected_order = [
        ("open", None, None, None),
        ("currency", "RIC-1", None, None),
        ("history", "RIC-1", "2024-01-01", ("unadjusted",)),
        (
            "history",
            "RIC-1",
            "2024-01-01",
            ("exchangeCorrection", "manualCorrection", "CCH", "CRE", "RPO", "RTS"),
        ),
        ("history", "RIC-1", "2025-01-01", ("unadjusted",)),
        (
            "history",
            "RIC-1",
            "2025-01-01",
            ("exchangeCorrection", "manualCorrection", "CCH", "CRE", "RPO", "RTS"),
        ),
        ("currency", "RIC-2", None, None),
        ("history", "RIC-2", "2024-01-01", ("unadjusted",)),
        (
            "history",
            "RIC-2",
            "2024-01-01",
            ("exchangeCorrection", "manualCorrection", "CCH", "CRE", "RPO", "RTS"),
        ),
        ("history", "RIC-2", "2025-01-01", ("unadjusted",)),
        (
            "history",
            "RIC-2",
            "2025-01-01",
            ("exchangeCorrection", "manualCorrection", "CCH", "CRE", "RPO", "RTS"),
        ),
        ("close", None, None, None),
    ]
    observed_order = []
    for name, kwargs in module.calls:
        observed_order.append(
            (
                name,
                kwargs.get("universe", [None])[0],
                kwargs.get("start"),
                tuple(kwargs["adjustments"]) if "adjustments" in kwargs else None,
            )
        )
    assert observed_order == expected_order

    currency_calls = [kwargs for name, kwargs in module.calls if name == "currency"]
    assert currency_calls == [
        {"universe": ["RIC-1"], "fields": ["TR.PriceClose.currency"]},
        {"universe": ["RIC-2"], "fields": ["TR.PriceClose.currency"]},
    ]
    history_calls = [kwargs for name, kwargs in module.calls if name == "history"]
    for index, kwargs in enumerate(history_calls):
        raw_call = index % 2 == 0
        assert kwargs["fields"] == (
            ["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "ACVOL_UNS"] if raw_call else ["TRDPRC_1"]
        )
        assert kwargs["interval"] == "1D"
        assert kwargs["header_type"] == FakeHeaderType.NAME
        assert kwargs["end"] in {"2024-12-31", "2025-01-01"}


def test_daily_chunks_are_consecutive_non_overlapping_and_at_most_366_days() -> None:
    start = date(2020, 2, 29)
    end = date(2023, 3, 2)

    chunks = daily_chunks(start, end)

    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    assert all(
        next_start == chunk_end + timedelta(days=1)
        for (_, chunk_end), (next_start, _) in pairwise(chunks)
    )
    assert all((chunk_end - chunk_start).days + 1 <= 366 for chunk_start, chunk_end in chunks)


def test_structured_entitlement_status_beats_a_conflicting_exception_message() -> None:
    module = FakeLsegDataModule()
    module.currency_errors["RIC"] = FakeSdkError(
        f"connection quota {SENTINEL}", code="PERMISSION_DENIED"
    )

    with pytest.raises(ProviderEntitlementError) as exc_info:
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    _assert_sanitized(exc_info.value)


def test_http_429_maps_to_quota_without_exposing_exception_text() -> None:
    module = FakeLsegDataModule()
    module.currency_errors["RIC"] = FakeSdkError(SENTINEL, http_status=429, code="SESSION_CLOSED")

    with pytest.raises(ProviderQuotaError) as exc_info:
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    _assert_sanitized(exc_info.value)


def test_connection_failure_maps_to_sanitized_session_error() -> None:
    module = FakeLsegDataModule()
    module.open_error = ConnectionError(SENTINEL)

    with pytest.raises(ProviderSessionError) as exc_info:
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert [name for name, _ in module.calls] == ["open"]
    _assert_sanitized(exc_info.value)


def test_invalid_identifier_becomes_an_item_failure_and_the_next_ric_continues() -> None:
    module = FakeLsegDataModule()
    module.currency_errors["BAD"] = FakeSdkError(SENTINEL, status_code="INVALID_INSTRUMENT")

    result = _gateway(module).fetch_daily_prices(
        ("BAD", "GOOD"), date(2024, 1, 1), date(2024, 1, 2)
    )

    assert [item.provider_identifier for item in result.items] == ["GOOD"]
    assert len(result.failures) == 1
    assert result.failures[0].provider_identifier == "BAD"
    assert result.failures[0].category is PriceFailureCategory.INVALID_IDENTIFIER
    assert SENTINEL not in result.failures[0].message
    assert [
        kwargs["universe"][0] for name, kwargs in module.calls if name in {"currency", "history"}
    ] == ["BAD", "GOOD", "GOOD", "GOOD"]


def test_unknown_sdk_exception_becomes_a_sanitized_provider_error() -> None:
    module = FakeLsegDataModule()
    module.currency_errors["RIC"] = FakeSdkError(SENTINEL, code="MYSTERY")

    with pytest.raises(ProviderError) as exc_info:
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert type(exc_info.value) is ProviderError
    assert str(exc_info.value) == "LSEG desktop request failed"
    _assert_sanitized(exc_info.value)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("truncated", True), ("limit", 1), ("status", "response_limit_reached")],
)
def test_frame_limit_or_truncation_metadata_is_rejected(attribute: str, value: object) -> None:
    module = FakeLsegDataModule()
    raw_frame = pd.DataFrame({"value": [1.0]})
    raw_frame.attrs[attribute] = value
    module.history_frames[("RIC", LSEG_RAW_ADJUSTMENTS, "2024-01-01")] = raw_frame

    with pytest.raises(ProviderDataError) as exc_info:
        _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    assert str(exc_info.value) == "LSEG history response reported a limit or truncation"


def test_gateway_never_passes_a_proxy_port_or_cloud_credentials() -> None:
    module = FakeLsegDataModule()

    _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2024, 1, 2))

    prohibited = {"port", "app_key", "client_id", "client_secret", "grant", "token"}
    for _, kwargs in module.calls:
        assert prohibited.isdisjoint(kwargs)
    open_call = module.calls[0]
    assert open_call == ("open", {"name": "desktop.workspace"})


def test_empty_holiday_chunk_is_valid_when_another_chunk_has_raw_data() -> None:
    module = FakeLsegDataModule()
    for adjustments in (LSEG_RAW_ADJUSTMENTS, LSEG_ADJUSTED_ADJUSTMENTS):
        module.history_frames[("RIC", adjustments, "2024-01-01")] = pd.DataFrame()

    result = _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2025, 1, 1))

    assert len(result.items) == 1
    assert len(result.items[0].chunks) == 2
    assert result.failures == ()


def test_all_empty_raw_history_becomes_a_no_data_item_failure() -> None:
    module = FakeLsegDataModule()
    for chunk_start in ("2024-01-01", "2025-01-01"):
        module.history_frames[("RIC", LSEG_RAW_ADJUSTMENTS, chunk_start)] = pd.DataFrame()

    result = _gateway(module).fetch_daily_prices(("RIC",), date(2024, 1, 1), date(2025, 1, 1))

    assert result.items == ()
    assert len(result.failures) == 1
    assert result.failures[0].provider_identifier == "RIC"
    assert result.failures[0].category is PriceFailureCategory.NO_DATA
    assert SENTINEL not in result.failures[0].message
