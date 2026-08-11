"""Deterministic offline demo bootstrap for local evaluation."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import numpy as np
import pandas as pd

from quant_raas.config import Settings
from quant_raas.connectors.fixture import FixturePriceProvider
from quant_raas.domain.enums import IdentifierScheme, SecurityStatus, SecurityType
from quant_raas.domain.market import PriceBarRequest, PriceRequestItem
from quant_raas.domain.security import Security, SecurityIdentifier
from quant_raas.ingestion.prices import PriceIngestionService, PriceIngestionSummary
from quant_raas.runtime import materiality_scorer, repositories_for
from quant_raas.security_master.importer import parse_coverage_csv, parse_holdings_csv
from quant_raas.security_master.service import SecurityMasterService
from quant_raas.services.daily_research import (
    DailyResearchRequest,
    DailyResearchResult,
    DailyResearchService,
)
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    securities: int
    coverage_list_id: UUID
    ingestion: PriceIngestionSummary
    research: DailyResearchResult


def _required_csv_value(row: Mapping[str, str | None], field: str) -> str:
    """Return a required CSV value with a field-specific validation error."""

    value = row.get(field)
    if not value:
        raise ValueError(f"demo universe row is missing {field!r}")
    return value


def _optional_iso_date(value: str | None) -> date | None:
    """Parse optional ISO dates before crossing the typed domain boundary."""

    return date.fromisoformat(value) if value else None


def generate_demo_price_frames(
    *,
    end_date: datetime,
    periods: int = 500,
) -> dict[str, pd.DataFrame]:
    """Create correlated synthetic OHLCV with one intentional final-day anomaly."""

    if end_date.tzinfo is None or end_date.utcoffset() is None:
        raise ValueError("end_date must be timezone-aware")
    if periods < 260:
        raise ValueError("demo requires at least 260 business sessions")
    dates = pd.bdate_range(end=end_date.date(), periods=periods)
    rng = np.random.default_rng(20260811)
    us_market = rng.normal(0.0003, 0.009, periods)
    eu_market = rng.normal(0.0002, 0.010, periods)
    return_map = {
        "SPX": us_market,
        "MSCI_EUROPE": eu_market,
        "AAPL US": 1.10 * us_market + rng.normal(0.0001, 0.006, periods),
        "MSFT US": 1.05 * us_market + rng.normal(0.0001, 0.0055, periods),
        "ASML NA": 1.20 * eu_market + rng.normal(0.0002, 0.007, periods),
        "SAP GY": 0.90 * eu_market + rng.normal(0.0001, 0.006, periods),
    }
    # The shock is synthetic and deliberate: it demonstrates residual/volume
    # materiality without implying a real historical event in the sample names.
    return_map["ASML NA"][-1] -= 0.09

    frames: dict[str, pd.DataFrame] = {}
    for index, (identifier, returns) in enumerate(return_map.items(), start=1):
        close = (80.0 + index * 20.0) * np.cumprod(1.0 + returns)
        previous = np.concatenate([[close[0]], close[:-1]])
        open_price = previous * (1.0 + rng.normal(0.0, 0.002, periods))
        high = np.maximum(open_price, close) * (1.0 + rng.uniform(0.001, 0.009, periods))
        low = np.minimum(open_price, close) * (1.0 - rng.uniform(0.001, 0.009, periods))
        volume = rng.lognormal(mean=16.0, sigma=0.25, size=periods)
        if identifier == "ASML NA":
            volume[-1] *= 5.0
        frames[identifier] = pd.DataFrame(
            {
                "session_date": dates,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "adjusted_close": close,
                "volume": volume,
                "currency": "EUR" if identifier in {"ASML NA", "SAP GY", "MSCI_EUROPE"} else "USD",
            }
        )
    return frames


def seed_demo(settings: Settings, *, now: datetime | None = None) -> DemoSeedResult:
    """Seed security master, synthetic prices, context, and daily cards atomically by stage."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    engine = create_sql_engine(settings)
    create_schema(engine)
    factory = create_session_factory(engine)
    universe_path = settings.config_directory / "universes" / "demo.csv"
    project_root = settings.config_directory.resolve().parent
    coverage_path = project_root / "examples" / "coverage.csv"
    holdings_path = project_root / "examples" / "holdings.csv"

    with factory.begin() as session:
        repos = repositories_for(session)
        master = SecurityMasterService(repos.securities, repos.portfolios)
        universe_rows = list(csv.DictReader(universe_path.read_text(encoding="utf-8").splitlines()))
        for row in universe_rows:
            security_id = UUID(_required_csv_value(row, "security_id"))
            security = Security(
                security_id=security_id,
                name=_required_csv_value(row, "name"),
                security_type=SecurityType(_required_csv_value(row, "security_type")),
                status=SecurityStatus(_required_csv_value(row, "status")),
                primary_currency=_required_csv_value(row, "primary_currency"),
                exchange_mic=row["exchange_mic"] or None,
                exchange_timezone=row["exchange_timezone"] or None,
                country_code=row["country_code"] or None,
                sector=row["sector"] or None,
                first_trade_date=_optional_iso_date(row["first_trade_date"]),
                last_trade_date=_optional_iso_date(row["last_trade_date"]),
            )
            identifier = SecurityIdentifier(
                security_id=security_id,
                scheme=IdentifierScheme(_required_csv_value(row, "identifier_scheme")),
                value=_required_csv_value(row, "identifier"),
                provider=row["provider"] or None,
                exchange_mic=row["exchange_mic"] or None,
                valid_from=datetime.fromisoformat(
                    _required_csv_value(row, "valid_from").replace("Z", "+00:00")
                ),
                valid_to=(
                    datetime.fromisoformat(row["valid_to"].replace("Z", "+00:00"))
                    if row["valid_to"]
                    else None
                ),
                is_primary=True,
            )
            master.register_security(security, [identifier])

        parsed_coverage = parse_coverage_csv(coverage_path)
        if not parsed_coverage.is_valid:
            raise ValueError(f"bundled coverage example is invalid: {parsed_coverage.issues}")
        coverage = master.import_coverage(
            parsed_coverage.rows,
            name="Offline Demo Coverage",
            as_of=current - timedelta(days=7),
            description="Synthetic data only; safe for local workflow evaluation.",
        )
        if not coverage.is_valid or coverage.coverage_list is None:
            raise ValueError(f"demo coverage could not be resolved: {coverage.issues}")

        parsed_holdings = parse_holdings_csv(holdings_path)
        if not parsed_holdings.is_valid:
            raise ValueError(f"bundled holdings example is invalid: {parsed_holdings.issues}")
        holdings = master.import_holdings(
            parsed_holdings.rows,
            portfolio_name="Offline Demo Holdings Context",
            as_of=current - timedelta(days=7),
            source_name=str(holdings_path),
            source_hash=parsed_holdings.source_hash,
        )
        if not holdings.is_valid:
            raise ValueError(f"demo holdings could not be resolved: {holdings.issues}")
        position_weights = {
            position.security_id: float(position.weight) for position in holdings.positions
        }
        coverage_list_id = coverage.coverage_list.coverage_list_id

    # End before the current UTC date so the demo never treats an incomplete
    # live session as a completed price bar.
    frames = generate_demo_price_frames(end_date=current - timedelta(days=1))
    identifier_to_id = {
        _required_csv_value(row, "identifier"): UUID(_required_csv_value(row, "security_id"))
        for row in universe_rows
    }
    request = PriceBarRequest(
        items=tuple(
            PriceRequestItem(security_id=identifier_to_id[name], provider_identifier=name)
            for name in sorted(frames)
        ),
        start_date=min(frame["session_date"].min().date() for frame in frames.values()),
        end_date=max(frame["session_date"].max().date() for frame in frames.values()),
        requested_at=current,
    )
    with factory.begin() as session:
        repos = repositories_for(session)
        ingestion = PriceIngestionService(
            provider=FixturePriceProvider(frames, clock=lambda: current),
            repository=repos.market_data,
        ).ingest(request)

    latest_session = datetime.combine(request.end_date, datetime.min.time(), tzinfo=UTC)
    with factory.begin() as session:
        repos = repositories_for(session)
        research = DailyResearchService(
            securities=repos.securities,
            portfolios=repos.portfolios,
            market_data=repos.market_data,
            features=repos.features,
            research=repos.research,
            materiality=materiality_scorer(settings),
            clock=lambda: current,
        ).run(
            DailyResearchRequest(
                coverage_list_id=coverage_list_id,
                as_of=latest_session,
                data_cutoff_at=current,
                source="fixture",
            ),
            position_weights=position_weights,
        )
    return DemoSeedResult(
        securities=len(universe_rows),
        coverage_list_id=coverage_list_id,
        ingestion=ingestion,
        research=research,
    )
