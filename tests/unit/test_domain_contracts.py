"""Unit tests for durable UTC, finite-number, and lineage contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from math import inf
from uuid import UUID

import pytest
from pydantic import ValidationError

from quant_raas.common.clock import ensure_utc
from quant_raas.domain.enums import EventType, IdentifierScheme, SourceType
from quant_raas.domain.events import CompanyEvent
from quant_raas.domain.market import FeatureSnapshot, PriceBar
from quant_raas.domain.research import EvidenceReference, QuantMetric
from quant_raas.domain.security import Security, SecurityIdentifier


def test_ensure_utc_rejects_naive_and_normalizes_offset() -> None:
    with pytest.raises(ValueError, match="explicit timezone"):
        ensure_utc(datetime(2024, 1, 2, 10, 0))

    plus_two = timezone(timedelta(hours=2))
    converted = ensure_utc(datetime(2024, 1, 2, 10, 0, tzinfo=plus_two))
    assert converted == datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
    assert converted.tzinfo is UTC


def test_security_normalizes_codes_and_validates_iana_timezone() -> None:
    stamp = datetime(2024, 1, 1, tzinfo=UTC)
    security = Security(
        name="Test issuer",
        primary_currency="eur",
        exchange_mic="xams",
        exchange_timezone="Europe/Amsterdam",
        country_code="nl",
        created_at=stamp,
        updated_at=stamp,
    )
    assert security.primary_currency == "EUR"
    assert security.exchange_mic == "XAMS"
    assert security.country_code == "NL"

    with pytest.raises(ValidationError, match="IANA timezone"):
        Security(
            name="Bad timezone issuer",
            primary_currency="USD",
            exchange_timezone="Mars/Olympus_Mons",
            created_at=stamp,
            updated_at=stamp,
        )


def test_temporal_identifier_rejects_naive_or_reversed_interval(security_id: UUID) -> None:
    aware = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="explicit timezone"):
        SecurityIdentifier(
            security_id=security_id,
            scheme=IdentifierScheme.TICKER,
            value="ABC",
            valid_from=datetime(2024, 1, 1),
            created_at=aware,
        )
    with pytest.raises(ValidationError, match="valid_to must be later"):
        SecurityIdentifier(
            security_id=security_id,
            scheme=IdentifierScheme.TICKER,
            value="ABC",
            valid_from=aware,
            valid_to=aware,
            created_at=aware,
        )


def test_numeric_contracts_reject_non_finite_values(
    security_id: UUID,
    ingestion_batch_id: UUID,
) -> None:
    stamp = datetime(2024, 1, 2, 21, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="finite"):
        QuantMetric(name="residual_zscore", value=inf, unit="zscore", as_of=stamp)

    with pytest.raises(ValidationError, match="finite"):
        PriceBar(
            security_id=security_id,
            session_date=date(2024, 1, 2),
            effective_at=stamp,
            available_at=stamp,
            ingested_at=stamp,
            open=100.0,
            high=inf,
            low=99.0,
            close=100.0,
            currency="USD",
            source="fixture",
            source_record_id="ABC:2024-01-02",
            ingestion_batch_id=ingestion_batch_id,
        )


def test_evidence_allows_known_future_event_but_enforces_knowledge_lineage() -> None:
    announced = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    event_time = datetime(2024, 2, 1, 21, 0, tzinfo=UTC)
    evidence = EvidenceReference(
        source_type=SourceType.COMPANY_EVENT,
        provider="issuer",
        source_record_id="earnings-calendar-1",
        effective_at=event_time,
        available_at=announced,
        ingested_at=announced + timedelta(minutes=1),
    )
    assert evidence.effective_at > evidence.available_at

    with pytest.raises(ValidationError, match="available_at cannot be later"):
        EvidenceReference(
            source_type=SourceType.COMPANY_EVENT,
            provider="issuer",
            source_record_id="bad-lineage",
            effective_at=event_time,
            available_at=announced + timedelta(minutes=2),
            ingested_at=announced + timedelta(minutes=1),
        )


def test_company_event_uses_availability_not_event_time_for_lineage(
    security_id: UUID,
    ingestion_batch_id: UUID,
) -> None:
    published = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    event = CompanyEvent(
        security_id=security_id,
        event_type=EventType.EARNINGS,
        title="Scheduled results",
        effective_at=datetime(2024, 2, 1, 21, 0, tzinfo=UTC),
        available_at=published,
        ingested_at=published + timedelta(seconds=5),
        source="issuer",
        source_record_id="event-1",
        ingestion_batch_id=ingestion_batch_id,
    )
    assert event.available_at < event.effective_at


def test_feature_snapshot_rejects_post_calculation_inputs(
    security_id: UUID,
    research_run_id: UUID,
) -> None:
    calculated = datetime(2024, 1, 3, 21, 10, tzinfo=UTC)
    with pytest.raises(ValidationError, match="available_at cannot be later"):
        FeatureSnapshot(
            security_id=security_id,
            feature_name="return_1d",
            feature_version="v1",
            effective_at=calculated - timedelta(minutes=10),
            available_at=calculated + timedelta(seconds=1),
            calculated_at=calculated,
            value=0.01,
            research_run_id=research_run_id,
            code_version="test",
            config_version="test",
        )
