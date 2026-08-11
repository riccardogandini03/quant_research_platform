"""Installable end-of-day workflow composition.

The scheduler-facing module under ``workflows/`` re-exports this callable. The
implementation lives in the package so the ``quant-raas`` console script also
works when invoked outside a source checkout.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, func, select

from quant_raas.common.clock import ensure_utc
from quant_raas.config import Settings
from quant_raas.runtime import materiality_scorer, repositories_for
from quant_raas.services.daily_research import (
    DailyResearchRequest,
    DailyResearchResult,
    DailyResearchService,
)
from quant_raas.storage.models import (
    CoverageListRecord,
    PortfolioPositionRecord,
    PortfolioSnapshotRecord,
    PriceBarRecord,
)
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine


def run_close_workflow(
    settings: Settings,
    *,
    coverage_list_id: UUID | None = None,
    as_of: datetime | None = None,
    data_cutoff_at: datetime | None = None,
    source: str | None = None,
) -> DailyResearchResult:
    """Run daily research from normalized prices already present in storage."""

    engine = create_sql_engine(settings)
    if settings.environment in {"development", "test"}:
        create_schema(engine)
    factory = create_session_factory(engine)
    cutoff = ensure_utc(data_cutoff_at or datetime.now(UTC))
    with factory.begin() as session:
        selected_coverage = coverage_list_id or session.scalar(
            select(CoverageListRecord.coverage_list_id)
            .order_by(desc(CoverageListRecord.created_at))
            .limit(1)
        )
        if selected_coverage is None:
            raise ValueError("no coverage list exists; import coverage or run seed-demo")
        effective = as_of or session.scalar(
            select(func.max(PriceBarRecord.effective_at)).where(
                PriceBarRecord.source == (source or settings.market_data_provider)
            )
        )
        if effective is None:
            raise ValueError("no normalized price bars exist for the configured source")

        latest_snapshot_id = session.scalar(
            select(PortfolioSnapshotRecord.snapshot_id)
            .where(PortfolioSnapshotRecord.as_of <= effective)
            .order_by(desc(PortfolioSnapshotRecord.as_of))
            .limit(1)
        )
        position_weights: dict[UUID, float] = {}
        if latest_snapshot_id is not None:
            positions = session.scalars(
                select(PortfolioPositionRecord).where(
                    PortfolioPositionRecord.snapshot_id == latest_snapshot_id
                )
            )
            position_weights = {
                position.security_id: float(position.weight) for position in positions
            }

        repos = repositories_for(session)
        service = DailyResearchService(
            securities=repos.securities,
            portfolios=repos.portfolios,
            market_data=repos.market_data,
            features=repos.features,
            research=repos.research,
            materiality=materiality_scorer(settings),
        )
        return service.run(
            DailyResearchRequest(
                coverage_list_id=selected_coverage,
                as_of=effective,
                data_cutoff_at=cutoff,
                source=source or settings.market_data_provider,
            ),
            position_weights=position_weights,
        )
