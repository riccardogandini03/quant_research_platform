"""Typed contracts shared by all modules of the modular monolith."""

from quant_raas.domain.events import CompanyEvent
from quant_raas.domain.market import (
    CorporateAction,
    FeatureSnapshot,
    IngestionBatch,
    PriceBar,
    PriceBarRequest,
    PriceIngestionResult,
)
from quant_raas.domain.portfolio import (
    CoverageList,
    CoverageMember,
    CoverageUploadRow,
    HoldingUploadRow,
    PortfolioPosition,
    PortfolioSnapshot,
)
from quant_raas.domain.research import (
    EvidenceReference,
    ResearchCard,
    ResearchFinding,
    ResearchRun,
)
from quant_raas.domain.security import (
    BenchmarkMapping,
    Security,
    SecurityIdentifier,
    SecurityReference,
    SecurityUploadRow,
)

__all__ = [
    "BenchmarkMapping",
    "CompanyEvent",
    "CorporateAction",
    "CoverageList",
    "CoverageMember",
    "CoverageUploadRow",
    "EvidenceReference",
    "FeatureSnapshot",
    "HoldingUploadRow",
    "IngestionBatch",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "PriceBar",
    "PriceBarRequest",
    "PriceIngestionResult",
    "ResearchCard",
    "ResearchFinding",
    "ResearchRun",
    "Security",
    "SecurityIdentifier",
    "SecurityReference",
    "SecurityUploadRow",
]
