"""Composition helpers shared by API, dashboard, CLI, and workers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from quant_raas.config import Settings
from quant_raas.research.materiality import MaterialityConfig, MaterialityScorer
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyMarketDataRepository,
    SqlAlchemyPortfolioRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)


@dataclass(frozen=True, slots=True)
class Repositories:
    securities: SqlAlchemySecurityRepository
    portfolios: SqlAlchemyPortfolioRepository
    market_data: SqlAlchemyMarketDataRepository
    features: SqlAlchemyFeatureRepository
    research: SqlAlchemyResearchRepository


def repositories_for(session: Session) -> Repositories:
    """Bind all repository adapters to one caller-owned transaction."""

    return Repositories(
        securities=SqlAlchemySecurityRepository(session),
        portfolios=SqlAlchemyPortfolioRepository(session),
        market_data=SqlAlchemyMarketDataRepository(session),
        features=SqlAlchemyFeatureRepository(session),
        research=SqlAlchemyResearchRepository(session),
    )


def materiality_scorer(settings: Settings) -> MaterialityScorer:
    path = settings.config_directory / "materiality" / "default.yaml"
    return MaterialityScorer(MaterialityConfig.from_yaml(path))
