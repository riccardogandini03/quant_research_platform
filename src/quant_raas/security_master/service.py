"""Application service for canonical resolution and contextual uploads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from quant_raas.common.clock import ensure_utc, utc_now
from quant_raas.common.errors import QuantRaasError
from quant_raas.domain.enums import BenchmarkKind
from quant_raas.domain.portfolio import (
    CoverageList,
    CoverageMember,
    CoverageUploadRow,
    HoldingUploadRow,
    PortfolioPosition,
    PortfolioSnapshot,
)
from quant_raas.domain.protocols import PortfolioRepository, SecurityRepository
from quant_raas.domain.security import (
    BenchmarkMapping,
    Security,
    SecurityIdentifier,
    SecurityReference,
    SecurityUploadRow,
)


@dataclass(frozen=True, slots=True)
class ResolutionIssue:
    row_number: int
    identifier: str
    message: str


@dataclass(frozen=True, slots=True)
class HoldingsImportResult:
    snapshot: PortfolioSnapshot | None
    positions: tuple[PortfolioPosition, ...]
    issues: tuple[ResolutionIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class CoverageImportResult:
    coverage_list: CoverageList | None
    members: tuple[CoverageMember, ...]
    issues: tuple[ResolutionIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class SecurityUniverseImportResult:
    securities: tuple[Security, ...]
    benchmark_mappings: tuple[BenchmarkMapping, ...]
    issues: tuple[ResolutionIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


class SecurityMasterService:
    """Resolve user identifiers without treating tickers as global IDs."""

    def __init__(
        self,
        security_repository: SecurityRepository,
        portfolio_repository: PortfolioRepository,
        *,
        default_benchmark_identifier: str | None = None,
        sector_benchmark_identifiers: Mapping[str, str] | None = None,
    ) -> None:
        self.securities = security_repository
        self.portfolios = portfolio_repository
        self.default_benchmark_identifier = default_benchmark_identifier
        self.sector_benchmarks = dict(sector_benchmark_identifiers or {})

    def register_security(
        self,
        security: Security,
        identifiers: Iterable[SecurityIdentifier],
    ) -> Security:
        """Persist one canonical security and all of its identifier vintages."""

        saved = self.securities.add_security(security)
        for identifier in identifiers:
            if identifier.security_id != saved.security_id:
                raise ValueError("identifier belongs to another security")
            self.securities.add_identifier(identifier)
        return saved

    def import_security_universe(
        self,
        rows: Iterable[SecurityUploadRow],
        *,
        config_version: str = "v0",
    ) -> SecurityUniverseImportResult:
        """Register a typed universe, then resolve its configured benchmarks.

        The caller owns the transaction and should roll it back if benchmark
        issues are unacceptable. Registering every security first allows rows
        to reference a benchmark that appears later in the same CSV.
        """

        materialized = tuple(rows)
        saved = tuple(
            self.register_security(row.to_security(), (row.to_identifier(),))
            for row in materialized
        )
        mappings: list[BenchmarkMapping] = []
        issues: list[ResolutionIssue] = []
        for row_number, row in enumerate(materialized, start=2):
            if not row.benchmark:
                continue
            try:
                mappings.append(
                    self.configure_benchmark(
                        SecurityReference(
                            identifier=row.identifier,
                            scheme=row.identifier_scheme,
                            provider=row.provider,
                            exchange_mic=row.exchange_mic,
                        ),
                        SecurityReference(identifier=row.benchmark),
                        kind=BenchmarkKind.MARKET,
                        valid_from=row.valid_from,
                        valid_to=row.valid_to,
                        config_version=config_version,
                    )
                )
            except QuantRaasError as exc:
                issues.append(ResolutionIssue(row_number, row.identifier, str(exc)))
        return SecurityUniverseImportResult(saved, tuple(mappings), tuple(issues))

    def resolve(
        self,
        reference: SecurityReference,
        *,
        as_of: datetime,
    ) -> Security:
        return self.securities.resolve(reference, as_of=ensure_utc(as_of))

    def configure_benchmark(
        self,
        security_reference: SecurityReference,
        benchmark_reference: SecurityReference,
        *,
        kind: BenchmarkKind,
        valid_from: datetime,
        valid_to: datetime | None = None,
        config_version: str = "v0",
    ) -> BenchmarkMapping:
        """Resolve and persist a temporal benchmark mapping from configuration."""

        start = ensure_utc(valid_from)
        subject = self.resolve(security_reference, as_of=start)
        benchmark = self.resolve(benchmark_reference, as_of=start)
        mapping = BenchmarkMapping(
            security_id=subject.security_id,
            benchmark_security_id=benchmark.security_id,
            kind=kind,
            valid_from=start,
            valid_to=ensure_utc(valid_to) if valid_to else None,
            config_version=config_version,
        )
        return self.securities.add_benchmark_mapping(mapping)

    def import_holdings(
        self,
        rows: Iterable[HoldingUploadRow],
        *,
        portfolio_name: str,
        as_of: datetime,
        source_name: str | None = None,
        source_hash: str | None = None,
    ) -> HoldingsImportResult:
        """Resolve all rows before persisting an immutable portfolio snapshot."""

        at = ensure_utc(as_of)
        resolved: list[tuple[HoldingUploadRow, Security, UUID | None]] = []
        issues: list[ResolutionIssue] = []
        for row_number, row in enumerate(rows, start=2):
            try:
                security = self.resolve(row.security_reference(), as_of=at)
                benchmark_id = self._resolve_benchmark(row.benchmark, security, as_of=at)
                resolved.append((row, security, benchmark_id))
            except QuantRaasError as exc:
                issues.append(ResolutionIssue(row_number, row.identifier, str(exc)))
        if issues:
            return HoldingsImportResult(None, (), tuple(issues))

        snapshot = PortfolioSnapshot(
            portfolio_name=portfolio_name,
            as_of=at,
            created_at=utc_now(),
            source_name=source_name,
            source_hash=source_hash,
        )
        positions = tuple(
            PortfolioPosition(
                snapshot_id=snapshot.snapshot_id,
                security_id=security.security_id,
                weight=row.weight,
                thesis_id=row.thesis_id,
                benchmark_security_id=benchmark_id,
                source_identifier=row.identifier,
            )
            for row, security, benchmark_id in resolved
        )
        saved = self.portfolios.add_portfolio_snapshot(snapshot, positions)
        return HoldingsImportResult(saved, positions, ())

    def import_coverage(
        self,
        rows: Iterable[CoverageUploadRow],
        *,
        name: str,
        as_of: datetime,
        description: str | None = None,
    ) -> CoverageImportResult:
        """Create a research universe without inventing portfolio positions."""

        at = ensure_utc(as_of)
        resolved: list[tuple[CoverageUploadRow, Security, UUID | None]] = []
        issues: list[ResolutionIssue] = []
        for row_number, row in enumerate(rows, start=2):
            try:
                security = self.resolve(row.security_reference(), as_of=at)
                benchmark_id = self._resolve_benchmark(row.benchmark, security, as_of=at)
                resolved.append((row, security, benchmark_id))
            except QuantRaasError as exc:
                issues.append(ResolutionIssue(row_number, row.identifier, str(exc)))
        if issues:
            return CoverageImportResult(None, (), tuple(issues))

        coverage = self.portfolios.add_coverage_list(
            CoverageList(name=name, description=description)
        )
        members = tuple(
            CoverageMember(
                coverage_list_id=coverage.coverage_list_id,
                security_id=security.security_id,
                added_at=at,
                thesis_id=row.thesis_id,
                benchmark_security_id=benchmark_id,
                peer_group=row.peer_group,
                source_identifier=row.identifier,
            )
            for row, security, benchmark_id in resolved
        )
        self.portfolios.add_coverage_members(members)
        return CoverageImportResult(coverage, members, ())

    def _resolve_benchmark(
        self,
        explicit_identifier: str | None,
        security: Security,
        *,
        as_of: datetime,
    ) -> UUID | None:
        identifier = explicit_identifier
        if identifier is None and security.sector:
            identifier = self.sector_benchmarks.get(security.sector)
        identifier = identifier or self.default_benchmark_identifier
        if identifier is None:
            mapping = self.securities.benchmark_as_of(
                security.security_id, BenchmarkKind.MARKET, as_of=as_of
            )
            return mapping.benchmark_security_id if mapping else None
        benchmark = self.resolve(SecurityReference(identifier=identifier), as_of=as_of)
        return benchmark.security_id
