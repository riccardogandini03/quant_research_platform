"""Small ports that keep domain/quant code independent of infrastructure."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from quant_raas.domain.enums import BenchmarkKind
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
    PortfolioPosition,
    PortfolioSnapshot,
)
from quant_raas.domain.research import (
    EvidenceReference,
    MaterialityFeedback,
    ResearchCard,
    ResearchFinding,
    ResearchRun,
)
from quant_raas.domain.security import (
    BenchmarkMapping,
    Security,
    SecurityIdentifier,
    SecurityReference,
)


@runtime_checkable
class PriceDataProvider(Protocol):
    """Capability port for normalized daily pricing."""

    @property
    def name(self) -> str: ...

    def fetch_daily_bars(self, request: PriceBarRequest) -> PriceIngestionResult: ...


@runtime_checkable
class SecurityRepository(Protocol):
    """Persistence operations required by the security-master service."""

    def add_security(self, security: Security) -> Security: ...

    def get_security(self, security_id: UUID) -> Security | None: ...

    def list_securities(self, *, active_only: bool = True) -> Sequence[Security]: ...

    def add_identifier(self, identifier: SecurityIdentifier) -> SecurityIdentifier: ...

    def resolve(
        self,
        reference: SecurityReference,
        *,
        as_of: datetime,
    ) -> Security: ...

    def add_benchmark_mapping(self, mapping: BenchmarkMapping) -> BenchmarkMapping: ...

    def benchmark_as_of(
        self,
        security_id: UUID,
        kind: BenchmarkKind,
        *,
        as_of: datetime,
    ) -> BenchmarkMapping | None: ...


@runtime_checkable
class PortfolioRepository(Protocol):
    def add_coverage_list(self, coverage_list: CoverageList) -> CoverageList: ...

    def add_coverage_members(self, members: Iterable[CoverageMember]) -> int: ...

    def active_coverage_members(
        self, coverage_list_id: UUID, *, as_of: datetime
    ) -> Sequence[CoverageMember]: ...

    def add_portfolio_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        positions: Iterable[PortfolioPosition],
    ) -> PortfolioSnapshot: ...


@runtime_checkable
class MarketDataRepository(Protocol):
    def add_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch: ...

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int: ...

    def price_history_as_of(
        self,
        security_ids: Sequence[UUID],
        *,
        start: datetime,
        end: datetime,
        knowledge_time: datetime,
        source: str | None = None,
    ) -> Sequence[PriceBar]: ...


@runtime_checkable
class EventRepository(Protocol):
    def upsert_company_events(self, events: Iterable[CompanyEvent]) -> int: ...

    def upsert_corporate_actions(self, actions: Iterable[CorporateAction]) -> int: ...

    def events_as_of(
        self,
        *,
        effective_start: datetime,
        effective_end: datetime,
        knowledge_time: datetime,
        security_id: UUID | None = None,
    ) -> Sequence[CompanyEvent]: ...


@runtime_checkable
class FeatureRepository(Protocol):
    def upsert_many(self, snapshots: Iterable[FeatureSnapshot]) -> int: ...

    def panel_as_of(
        self,
        security_ids: Sequence[UUID],
        feature_versions: Mapping[str, str],
        *,
        config_version: str,
        as_of: datetime,
    ) -> Sequence[FeatureSnapshot]: ...

    def latest_as_of(
        self,
        security_id: UUID,
        feature_names: Sequence[str],
        *,
        effective_at: datetime,
        knowledge_time: datetime,
    ) -> Sequence[FeatureSnapshot]: ...


@runtime_checkable
class ResearchRepository(Protocol):
    def add_run(self, run: ResearchRun) -> ResearchRun: ...

    def add_evidence(self, evidence: EvidenceReference) -> EvidenceReference: ...

    def add_finding(self, finding: ResearchFinding) -> ResearchFinding: ...

    def add_card(self, card: ResearchCard) -> ResearchCard: ...

    def add_feedback(self, feedback: MaterialityFeedback) -> MaterialityFeedback: ...

    def cards_as_of(
        self,
        *,
        knowledge_time: datetime,
        security_id: UUID | None = None,
    ) -> Sequence[ResearchCard]: ...
