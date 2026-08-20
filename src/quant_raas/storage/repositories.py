"""SQLAlchemy implementations of the domain repository ports.

Repositories flush but never commit. The calling application service owns the
transaction, allowing a CSV import or daily research run to remain atomic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select
from sqlalchemy.orm import Session

from quant_raas.common.clock import ensure_utc
from quant_raas.common.errors import (
    AmbiguousIdentifierError,
    DomainValidationError,
    IdentifierNotFoundError,
    RepositoryConflictError,
)
from quant_raas.domain.enums import BenchmarkKind, SecurityStatus
from quant_raas.domain.events import CompanyEvent
from quant_raas.domain.market import CorporateAction, FeatureSnapshot, IngestionBatch, PriceBar
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
from quant_raas.storage.models import (
    BenchmarkMappingRecord,
    CompanyEventRecord,
    CorporateActionRecord,
    CoverageListRecord,
    CoverageMemberRecord,
    EvidenceReferenceRecord,
    FeatureSnapshotRecord,
    IngestionBatchRecord,
    MaterialityFeedbackRecord,
    PortfolioPositionRecord,
    PortfolioSnapshotRecord,
    PriceBarRecord,
    ResearchCardRecord,
    ResearchFindingRecord,
    ResearchRunRecord,
    SecurityIdentifierRecord,
    SecurityRecord,
    research_card_evidence,
    research_card_finding,
    research_finding_evidence,
)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _uuid_strings(values: Iterable[UUID]) -> list[str]:
    return [str(value) for value in values]


def _security_from_record(record: SecurityRecord) -> Security:
    return Security.model_validate(
        {
            "security_id": record.security_id,
            "name": record.name,
            "security_type": record.security_type,
            "status": record.status,
            "primary_currency": record.primary_currency,
            "exchange_mic": record.exchange_mic,
            "exchange_timezone": record.exchange_timezone,
            "country_code": record.country_code,
            "region": record.region,
            "sector": record.sector,
            "industry": record.industry,
            "first_trade_date": record.first_trade_date,
            "last_trade_date": record.last_trade_date,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    )


def _identifier_from_record(record: SecurityIdentifierRecord) -> SecurityIdentifier:
    return SecurityIdentifier.model_validate(
        {
            "identifier_id": record.identifier_id,
            "security_id": record.security_id,
            "scheme": record.scheme,
            "value": record.value,
            "provider": record.provider or None,
            "exchange_mic": record.exchange_mic or None,
            "valid_from": record.valid_from,
            "valid_to": record.valid_to,
            "is_primary": record.is_primary,
            "created_at": record.created_at,
        }
    )


def _mapping_from_record(record: BenchmarkMappingRecord) -> BenchmarkMapping:
    return BenchmarkMapping.model_validate(
        {
            "mapping_id": record.mapping_id,
            "security_id": record.security_id,
            "benchmark_security_id": record.benchmark_security_id,
            "kind": record.kind,
            "valid_from": record.valid_from,
            "valid_to": record.valid_to,
            "source": record.source,
            "config_version": record.config_version,
            "created_at": record.created_at,
        }
    )


class SqlAlchemySecurityRepository:
    """Security-master repository with temporal, ambiguity-safe resolution."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_security(self, security: Security) -> Security:
        existing = self.session.get(SecurityRecord, security.security_id)
        values = security.model_dump(mode="python")
        values["security_type"] = security.security_type.value
        values["status"] = security.status.value
        if existing is None:
            self.session.add(SecurityRecord(**values))
        else:
            # Stable UUID is authoritative; descriptive master data may improve.
            for key, value in values.items():
                if key != "security_id":
                    setattr(existing, key, value)
        self.session.flush()
        record = self.session.get(SecurityRecord, security.security_id)
        assert record is not None
        return _security_from_record(record)

    def get_security(self, security_id: UUID) -> Security | None:
        record = self.session.get(SecurityRecord, security_id)
        return _security_from_record(record) if record else None

    def list_securities(self, *, active_only: bool = True) -> Sequence[Security]:
        statement = select(SecurityRecord).order_by(SecurityRecord.name, SecurityRecord.security_id)
        if active_only:
            statement = statement.where(SecurityRecord.status == SecurityStatus.ACTIVE.value)
        return tuple(_security_from_record(row) for row in self.session.scalars(statement))

    def add_identifier(self, identifier: SecurityIdentifier) -> SecurityIdentifier:
        provider = identifier.provider or ""
        exchange_mic = identifier.exchange_mic or ""
        natural = select(SecurityIdentifierRecord).where(
            SecurityIdentifierRecord.scheme == identifier.scheme.value,
            SecurityIdentifierRecord.value == identifier.value,
            SecurityIdentifierRecord.provider == provider,
            SecurityIdentifierRecord.exchange_mic == exchange_mic,
            SecurityIdentifierRecord.valid_from == identifier.valid_from,
        )
        existing = self.session.scalar(natural)
        if existing:
            if existing.security_id != identifier.security_id:
                raise RepositoryConflictError(
                    "identifier natural key already belongs to another security"
                )
            return _identifier_from_record(existing)

        # Overlapping identifier vintages make an as-of lookup ambiguous even
        # if the collision happens to point at the same current security.
        overlap = select(SecurityIdentifierRecord).where(
            SecurityIdentifierRecord.scheme == identifier.scheme.value,
            SecurityIdentifierRecord.value == identifier.value,
            SecurityIdentifierRecord.provider == provider,
            SecurityIdentifierRecord.exchange_mic == exchange_mic,
            or_(
                SecurityIdentifierRecord.valid_to.is_(None),
                SecurityIdentifierRecord.valid_to > identifier.valid_from,
            ),
        )
        if identifier.valid_to is not None:
            overlap = overlap.where(SecurityIdentifierRecord.valid_from < identifier.valid_to)
        if self.session.scalar(overlap):
            raise DomainValidationError("security identifier validity intervals cannot overlap")

        record = SecurityIdentifierRecord(
            identifier_id=identifier.identifier_id,
            security_id=identifier.security_id,
            scheme=identifier.scheme.value,
            value=identifier.value,
            provider=provider,
            exchange_mic=exchange_mic,
            valid_from=identifier.valid_from,
            valid_to=identifier.valid_to,
            is_primary=identifier.is_primary,
            created_at=identifier.created_at,
        )
        self.session.add(record)
        self.session.flush()
        return _identifier_from_record(record)

    def resolve(
        self,
        reference: SecurityReference,
        *,
        as_of: datetime,
    ) -> Security:
        at = ensure_utc(as_of)
        statement = (
            select(SecurityRecord)
            .join(
                SecurityIdentifierRecord,
                SecurityIdentifierRecord.security_id == SecurityRecord.security_id,
            )
            .where(
                SecurityIdentifierRecord.value == reference.identifier,
                SecurityIdentifierRecord.valid_from <= at,
                or_(
                    SecurityIdentifierRecord.valid_to.is_(None),
                    SecurityIdentifierRecord.valid_to > at,
                ),
            )
        )
        if reference.scheme is not None:
            statement = statement.where(SecurityIdentifierRecord.scheme == reference.scheme.value)
        if reference.provider is not None:
            statement = statement.where(SecurityIdentifierRecord.provider == reference.provider)
        if reference.exchange_mic is not None:
            statement = statement.where(
                SecurityIdentifierRecord.exchange_mic == reference.exchange_mic
            )

        records = {row.security_id: row for row in self.session.scalars(statement)}
        if not records:
            raise IdentifierNotFoundError(reference.identifier)
        if len(records) > 1:
            raise AmbiguousIdentifierError(reference.identifier, tuple(records))
        return _security_from_record(next(iter(records.values())))

    def add_benchmark_mapping(self, mapping: BenchmarkMapping) -> BenchmarkMapping:
        existing = self.session.scalar(
            select(BenchmarkMappingRecord).where(
                BenchmarkMappingRecord.security_id == mapping.security_id,
                BenchmarkMappingRecord.kind == mapping.kind.value,
                BenchmarkMappingRecord.valid_from == mapping.valid_from,
            )
        )
        if existing:
            if existing.benchmark_security_id != mapping.benchmark_security_id:
                raise RepositoryConflictError(
                    "benchmark mapping natural key has a different benchmark"
                )
            return _mapping_from_record(existing)

        overlap = select(BenchmarkMappingRecord).where(
            BenchmarkMappingRecord.security_id == mapping.security_id,
            BenchmarkMappingRecord.kind == mapping.kind.value,
            or_(
                BenchmarkMappingRecord.valid_to.is_(None),
                BenchmarkMappingRecord.valid_to > mapping.valid_from,
            ),
        )
        if mapping.valid_to is not None:
            overlap = overlap.where(BenchmarkMappingRecord.valid_from < mapping.valid_to)
        if self.session.scalar(overlap):
            raise DomainValidationError("benchmark mapping intervals cannot overlap")

        record = BenchmarkMappingRecord(
            mapping_id=mapping.mapping_id,
            security_id=mapping.security_id,
            benchmark_security_id=mapping.benchmark_security_id,
            kind=mapping.kind.value,
            valid_from=mapping.valid_from,
            valid_to=mapping.valid_to,
            source=mapping.source,
            config_version=mapping.config_version,
            created_at=mapping.created_at,
        )
        self.session.add(record)
        self.session.flush()
        return _mapping_from_record(record)

    def benchmark_as_of(
        self,
        security_id: UUID,
        kind: BenchmarkKind,
        *,
        as_of: datetime,
    ) -> BenchmarkMapping | None:
        at = ensure_utc(as_of)
        record = self.session.scalar(
            select(BenchmarkMappingRecord)
            .where(
                BenchmarkMappingRecord.security_id == security_id,
                BenchmarkMappingRecord.kind == kind.value,
                BenchmarkMappingRecord.valid_from <= at,
                or_(
                    BenchmarkMappingRecord.valid_to.is_(None),
                    BenchmarkMappingRecord.valid_to > at,
                ),
            )
            .order_by(BenchmarkMappingRecord.valid_from.desc())
        )
        return _mapping_from_record(record) if record else None


class SqlAlchemyPortfolioRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_coverage_list(self, coverage_list: CoverageList) -> CoverageList:
        existing = self.session.get(CoverageListRecord, coverage_list.coverage_list_id)
        if existing is None:
            existing = self.session.scalar(
                select(CoverageListRecord).where(CoverageListRecord.name == coverage_list.name)
            )
        if existing:
            return CoverageList(
                coverage_list_id=existing.coverage_list_id,
                name=existing.name,
                description=existing.description,
                created_at=existing.created_at,
            )
        record = CoverageListRecord(**coverage_list.model_dump(mode="python"))
        self.session.add(record)
        self.session.flush()
        return coverage_list

    def add_coverage_members(self, members: Iterable[CoverageMember]) -> int:
        inserted = 0
        for member in members:
            overlap = select(CoverageMemberRecord).where(
                CoverageMemberRecord.coverage_list_id == member.coverage_list_id,
                CoverageMemberRecord.security_id == member.security_id,
                or_(
                    CoverageMemberRecord.removed_at.is_(None),
                    CoverageMemberRecord.removed_at > member.added_at,
                ),
            )
            if member.removed_at is not None:
                overlap = overlap.where(CoverageMemberRecord.added_at < member.removed_at)
            existing = self.session.scalar(overlap.order_by(CoverageMemberRecord.added_at.desc()))
            if existing:
                same_context = (
                    existing.thesis_id,
                    existing.benchmark_security_id,
                    existing.peer_group,
                    existing.source_identifier,
                ) == (
                    member.thesis_id,
                    member.benchmark_security_id,
                    member.peer_group,
                    member.source_identifier,
                )
                same_interval = (
                    existing.added_at == member.added_at
                    and existing.removed_at == member.removed_at
                )
                repeated_open_membership = (
                    existing.added_at <= member.added_at
                    and existing.removed_at is None
                    and member.removed_at is None
                )
                if same_context and (same_interval or repeated_open_membership):
                    # A later re-import of an unchanged active universe is a
                    # retry, not a new temporal membership interval.
                    continue
                raise RepositoryConflictError(
                    "coverage membership overlaps an existing interval with different context"
                )
            self.session.add(CoverageMemberRecord(**member.model_dump(mode="python")))
            inserted += 1
        self.session.flush()
        return inserted

    def active_coverage_members(
        self, coverage_list_id: UUID, *, as_of: datetime
    ) -> Sequence[CoverageMember]:
        at = ensure_utc(as_of)
        statement = select(CoverageMemberRecord).where(
            CoverageMemberRecord.coverage_list_id == coverage_list_id,
            CoverageMemberRecord.added_at <= at,
            or_(
                CoverageMemberRecord.removed_at.is_(None),
                CoverageMemberRecord.removed_at > at,
            ),
        )
        # Database row order is undefined without an explicit key. Stable
        # membership order makes research-card serialization reproducible.
        statement = statement.order_by(
            CoverageMemberRecord.security_id,
            CoverageMemberRecord.added_at,
        )
        return tuple(
            CoverageMember(
                membership_id=row.membership_id,
                coverage_list_id=row.coverage_list_id,
                security_id=row.security_id,
                added_at=row.added_at,
                removed_at=row.removed_at,
                thesis_id=row.thesis_id,
                benchmark_security_id=row.benchmark_security_id,
                peer_group=row.peer_group,
                source_identifier=row.source_identifier,
            )
            for row in self.session.scalars(statement)
        )

    def add_portfolio_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        positions: Iterable[PortfolioPosition],
    ) -> PortfolioSnapshot:
        existing = self.session.scalar(
            select(PortfolioSnapshotRecord).where(
                PortfolioSnapshotRecord.portfolio_name == snapshot.portfolio_name,
                PortfolioSnapshotRecord.as_of == snapshot.as_of,
            )
        )
        if existing:
            if snapshot.source_hash and existing.source_hash != snapshot.source_hash:
                raise RepositoryConflictError(
                    "portfolio snapshot natural key has different source content"
                )
            return PortfolioSnapshot(
                snapshot_id=existing.snapshot_id,
                portfolio_name=existing.portfolio_name,
                as_of=existing.as_of,
                created_at=existing.created_at,
                source_name=existing.source_name,
                source_hash=existing.source_hash,
            )

        snapshot_record = PortfolioSnapshotRecord(**snapshot.model_dump(mode="python"))
        self.session.add(snapshot_record)
        # There is deliberately no ORM relationship between the immutable
        # persistence records. Flush the parent explicitly so SQLite's foreign
        # key checks cannot observe a position before its snapshot. This is not
        # a commit: the caller still owns one atomic transaction for both.
        self.session.flush((snapshot_record,))
        for position in positions:
            if position.snapshot_id != snapshot.snapshot_id:
                raise DomainValidationError("position belongs to another snapshot")
            self.session.add(PortfolioPositionRecord(**position.model_dump(mode="python")))
        self.session.flush()
        return snapshot


class SqlAlchemyMarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_ingestion_batch(self, batch: IngestionBatch) -> IngestionBatch:
        existing = self.session.scalar(
            select(IngestionBatchRecord).where(IngestionBatchRecord.batch_key == batch.batch_key)
        )
        if existing:
            return IngestionBatch.model_validate(
                {
                    "batch_id": existing.batch_id,
                    "batch_key": existing.batch_key,
                    "provider": existing.provider,
                    "dataset": existing.dataset,
                    "requested_at": existing.requested_at,
                    "started_at": existing.started_at,
                    "completed_at": existing.completed_at,
                    "status": existing.status,
                    "request_fingerprint": existing.request_fingerprint,
                    "content_hash": existing.content_hash,
                    "row_count": existing.row_count,
                    "error_message": existing.error_message,
                }
            )
        values = batch.model_dump(mode="python")
        values["status"] = batch.status.value
        self.session.add(IngestionBatchRecord(**values))
        self.session.flush()
        return batch

    def upsert_price_bars(self, bars: Iterable[PriceBar]) -> int:
        inserted = 0
        for bar in bars:
            existing = self.session.scalar(
                select(PriceBarRecord).where(
                    PriceBarRecord.security_id == bar.security_id,
                    PriceBarRecord.frequency == bar.frequency.value,
                    PriceBarRecord.source == bar.source,
                    PriceBarRecord.effective_at == bar.effective_at,
                    PriceBarRecord.available_at == bar.available_at,
                )
            )
            if existing:
                # Same vintage must be byte-for-byte stable. A correction needs
                # a later available_at and therefore becomes a new vintage.
                comparable = (
                    existing.open,
                    existing.high,
                    existing.low,
                    existing.close,
                    existing.adjusted_close,
                    existing.volume,
                )
                incoming = (
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.adjusted_close,
                    bar.volume,
                )
                if comparable != incoming:
                    raise RepositoryConflictError(
                        "price bar vintage contains different numerical values"
                    )
                continue
            values = bar.model_dump(mode="python")
            values["frequency"] = bar.frequency.value
            values["quality_flags"] = [flag.value for flag in bar.quality_flags]
            self.session.add(PriceBarRecord(**values))
            inserted += 1
        self.session.flush()
        return inserted

    def price_history_as_of(
        self,
        security_ids: Sequence[UUID],
        *,
        start: datetime,
        end: datetime,
        knowledge_time: datetime,
        source: str | None = None,
    ) -> Sequence[PriceBar]:
        start_at, end_at, known_at = map(ensure_utc, (start, end, knowledge_time))
        if end_at < start_at:
            raise DomainValidationError("end cannot precede start")
        if not security_ids:
            return ()
        statement = (
            select(PriceBarRecord)
            .where(
                PriceBarRecord.security_id.in_(security_ids),
                PriceBarRecord.effective_at >= start_at,
                PriceBarRecord.effective_at <= end_at,
                PriceBarRecord.available_at <= known_at,
            )
            .order_by(
                PriceBarRecord.security_id,
                PriceBarRecord.source,
                PriceBarRecord.effective_at,
                PriceBarRecord.available_at.desc(),
            )
        )
        if source is not None:
            statement = statement.where(PriceBarRecord.source == source)

        latest: dict[tuple[UUID, str, str, datetime], PriceBarRecord] = {}
        for row in self.session.scalars(statement):
            key = (row.security_id, row.frequency, row.source, row.effective_at)
            latest.setdefault(key, row)
        return tuple(_price_bar_from_record(row) for row in latest.values())


def _price_bar_from_record(row: PriceBarRecord) -> PriceBar:
    return PriceBar.model_validate(
        {
            "price_bar_id": row.price_bar_id,
            "security_id": row.security_id,
            "session_date": row.session_date,
            "frequency": row.frequency,
            "effective_at": row.effective_at,
            "available_at": row.available_at,
            "ingested_at": row.ingested_at,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "adjusted_close": row.adjusted_close,
            "volume": row.volume,
            "currency": row.currency,
            "adjustment_factor": row.adjustment_factor,
            "total_return_factor": row.total_return_factor,
            "source": row.source,
            "source_record_id": row.source_record_id,
            "provider_identifier": row.provider_identifier,
            "ingestion_batch_id": row.ingestion_batch_id,
            "quality_flags": row.quality_flags,
        }
    )


class SqlAlchemyEventRepository:
    """Persist event vintages without assuming effective time is in the past."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_company_events(self, events: Iterable[CompanyEvent]) -> int:
        inserted = 0
        for event in events:
            existing = self.session.scalar(
                select(CompanyEventRecord).where(
                    CompanyEventRecord.source == event.source,
                    CompanyEventRecord.source_record_id == event.source_record_id,
                    CompanyEventRecord.available_at == event.available_at,
                )
            )
            if existing:
                if existing.payload != event.payload:
                    raise RepositoryConflictError(
                        "company event vintage contains a different payload"
                    )
                continue
            self.session.add(
                CompanyEventRecord(
                    event_id=event.event_id,
                    security_id=event.security_id,
                    event_type=event.event_type.value,
                    title=event.title,
                    effective_at=event.effective_at,
                    available_at=event.available_at,
                    ingested_at=event.ingested_at,
                    source=event.source,
                    source_record_id=event.source_record_id,
                    ingestion_batch_id=event.ingestion_batch_id,
                    payload=event.model_dump(mode="json")["payload"],
                    quality_flags=[flag.value for flag in event.quality_flags],
                )
            )
            inserted += 1
        self.session.flush()
        return inserted

    def upsert_corporate_actions(self, actions: Iterable[CorporateAction]) -> int:
        inserted = 0
        for action in actions:
            existing = self.session.scalar(
                select(CorporateActionRecord).where(
                    CorporateActionRecord.source == action.source,
                    CorporateActionRecord.source_record_id == action.source_record_id,
                    CorporateActionRecord.available_at == action.available_at,
                )
            )
            if existing:
                if (existing.ratio, existing.cash_amount) != (
                    action.ratio,
                    action.cash_amount,
                ):
                    raise RepositoryConflictError(
                        "corporate action vintage contains different values"
                    )
                continue
            self.session.add(
                CorporateActionRecord(
                    corporate_action_id=action.corporate_action_id,
                    security_id=action.security_id,
                    action_type=action.action_type.value,
                    effective_at=action.effective_at,
                    available_at=action.available_at,
                    ingested_at=action.ingested_at,
                    ratio=action.ratio,
                    cash_amount=action.cash_amount,
                    currency=action.currency,
                    source=action.source,
                    source_record_id=action.source_record_id,
                    ingestion_batch_id=action.ingestion_batch_id,
                    metadata_json=action.model_dump(mode="json")["metadata"],
                )
            )
            inserted += 1
        self.session.flush()
        return inserted

    def events_as_of(
        self,
        *,
        effective_start: datetime,
        effective_end: datetime,
        knowledge_time: datetime,
        security_id: UUID | None = None,
    ) -> Sequence[CompanyEvent]:
        start, end, known = map(ensure_utc, (effective_start, effective_end, knowledge_time))
        if end < start:
            raise DomainValidationError("effective_end cannot precede effective_start")
        statement = (
            select(CompanyEventRecord)
            .where(
                CompanyEventRecord.effective_at >= start,
                CompanyEventRecord.effective_at <= end,
                CompanyEventRecord.available_at <= known,
            )
            .order_by(
                CompanyEventRecord.source,
                CompanyEventRecord.source_record_id,
                CompanyEventRecord.available_at.desc(),
            )
        )
        if security_id is not None:
            statement = statement.where(CompanyEventRecord.security_id == security_id)
        latest: dict[tuple[str, str], CompanyEventRecord] = {}
        for row in self.session.scalars(statement):
            latest.setdefault((row.source, row.source_record_id), row)
        return tuple(_event_from_record(row) for row in latest.values())


def _event_from_record(row: CompanyEventRecord) -> CompanyEvent:
    return CompanyEvent.model_validate(
        {
            "event_id": row.event_id,
            "security_id": row.security_id,
            "event_type": row.event_type,
            "title": row.title,
            "effective_at": row.effective_at,
            "available_at": row.available_at,
            "ingested_at": row.ingested_at,
            "source": row.source,
            "source_record_id": row.source_record_id,
            "ingestion_batch_id": row.ingestion_batch_id,
            "payload": row.payload,
            "quality_flags": row.quality_flags,
        }
    )


class SqlAlchemyFeatureRepository:
    """Versioned feature storage with knowledge-time retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, snapshots: Iterable[FeatureSnapshot]) -> int:
        inserted = 0
        for snapshot in snapshots:
            existing = self.session.scalar(
                select(FeatureSnapshotRecord).where(
                    FeatureSnapshotRecord.security_id == snapshot.security_id,
                    FeatureSnapshotRecord.feature_name == snapshot.feature_name,
                    FeatureSnapshotRecord.feature_version == snapshot.feature_version,
                    FeatureSnapshotRecord.effective_at == snapshot.effective_at,
                    FeatureSnapshotRecord.available_at == snapshot.available_at,
                    FeatureSnapshotRecord.code_version == snapshot.code_version,
                    FeatureSnapshotRecord.config_version == snapshot.config_version,
                )
            )
            if existing:
                if existing.value != snapshot.value:
                    raise RepositoryConflictError(
                        "feature snapshot natural key contains a different value"
                    )
                continue
            self.session.add(
                FeatureSnapshotRecord(
                    feature_snapshot_id=snapshot.feature_snapshot_id,
                    security_id=snapshot.security_id,
                    feature_name=snapshot.feature_name,
                    feature_version=snapshot.feature_version,
                    effective_at=snapshot.effective_at,
                    available_at=snapshot.available_at,
                    calculated_at=snapshot.calculated_at,
                    value=snapshot.model_dump(mode="json")["value"],
                    unit=snapshot.unit,
                    window=snapshot.window,
                    quality_flags=[flag.value for flag in snapshot.quality_flags],
                    input_evidence_ids=_uuid_strings(snapshot.input_evidence_ids),
                    research_run_id=snapshot.research_run_id,
                    code_version=snapshot.code_version,
                    config_version=snapshot.config_version,
                    metadata_json=snapshot.model_dump(mode="json")["metadata"],
                )
            )
            inserted += 1
        self.session.flush()
        return inserted

    def latest_as_of(
        self,
        security_id: UUID,
        feature_names: Sequence[str],
        *,
        effective_at: datetime,
        knowledge_time: datetime,
    ) -> Sequence[FeatureSnapshot]:
        effective, known = map(ensure_utc, (effective_at, knowledge_time))
        if not feature_names:
            return ()
        statement = (
            select(FeatureSnapshotRecord)
            .where(
                FeatureSnapshotRecord.security_id == security_id,
                FeatureSnapshotRecord.feature_name.in_(feature_names),
                FeatureSnapshotRecord.effective_at <= effective,
                FeatureSnapshotRecord.available_at <= known,
            )
            .order_by(
                FeatureSnapshotRecord.feature_name,
                FeatureSnapshotRecord.effective_at.desc(),
                FeatureSnapshotRecord.available_at.desc(),
                FeatureSnapshotRecord.calculated_at.desc(),
            )
        )
        latest: dict[str, FeatureSnapshotRecord] = {}
        for row in self.session.scalars(statement):
            latest.setdefault(row.feature_name, row)
        return tuple(_feature_from_record(row) for row in latest.values())

    def panel_as_of(
        self,
        security_ids: Sequence[UUID],
        feature_versions: Mapping[str, str],
        *,
        config_version: str,
        as_of: datetime,
    ) -> Sequence[FeatureSnapshot]:
        cutoff = ensure_utc(as_of)
        if not config_version.strip():
            raise ValueError("config_version cannot be empty")
        if any(
            not name.strip() or not version.strip() for name, version in feature_versions.items()
        ):
            raise ValueError("feature names and versions cannot be empty")
        requested_ids = tuple(sorted(set(security_ids), key=str))
        requested_features = tuple(sorted(feature_versions.items()))
        if not requested_ids or not requested_features:
            return ()

        requested_pairs = tuple(
            and_(
                FeatureSnapshotRecord.feature_name == name,
                FeatureSnapshotRecord.feature_version == version,
            )
            for name, version in requested_features
        )
        vintage_rank = func.dense_rank().over(
            partition_by=(
                FeatureSnapshotRecord.security_id,
                FeatureSnapshotRecord.feature_name,
            ),
            order_by=(
                FeatureSnapshotRecord.effective_at.desc(),
                FeatureSnapshotRecord.available_at.desc(),
                FeatureSnapshotRecord.calculated_at.desc(),
            ),
        )
        ranked = (
            select(
                FeatureSnapshotRecord.feature_snapshot_id.label("feature_snapshot_id"),
                vintage_rank.label("vintage_rank"),
            )
            .where(
                FeatureSnapshotRecord.security_id.in_(requested_ids),
                or_(*requested_pairs),
                FeatureSnapshotRecord.config_version == config_version,
                FeatureSnapshotRecord.effective_at <= cutoff,
                FeatureSnapshotRecord.available_at <= cutoff,
            )
            .subquery()
        )
        statement = (
            select(FeatureSnapshotRecord)
            .join(
                ranked,
                FeatureSnapshotRecord.feature_snapshot_id == ranked.c.feature_snapshot_id,
            )
            .where(ranked.c.vintage_rank == 1)
            .order_by(
                FeatureSnapshotRecord.security_id,
                FeatureSnapshotRecord.feature_name,
                FeatureSnapshotRecord.feature_snapshot_id,
            )
        )
        latest: dict[tuple[UUID, str], FeatureSnapshotRecord] = {}
        for row in self.session.scalars(statement):
            key = (row.security_id, row.feature_name)
            selected = latest.get(key)
            if selected is None:
                latest[key] = row
                continue
            precedence = (row.effective_at, row.available_at, row.calculated_at)
            selected_precedence = (
                selected.effective_at,
                selected.available_at,
                selected.calculated_at,
            )
            if precedence == selected_precedence:
                raise RepositoryConflictError(
                    f"ambiguous latest feature vintage for security {row.security_id} "
                    f"feature {row.feature_name!r}"
                )
        return tuple(
            _feature_from_record(latest[key])
            for key in sorted(latest, key=lambda item: (str(item[0]), item[1]))
        )


def _feature_from_record(row: FeatureSnapshotRecord) -> FeatureSnapshot:
    return FeatureSnapshot.model_validate(
        {
            "feature_snapshot_id": row.feature_snapshot_id,
            "security_id": row.security_id,
            "feature_name": row.feature_name,
            "feature_version": row.feature_version,
            "effective_at": row.effective_at,
            "available_at": row.available_at,
            "calculated_at": row.calculated_at,
            "value": row.value,
            "unit": row.unit,
            "window": row.window,
            "quality_flags": row.quality_flags,
            "input_evidence_ids": row.input_evidence_ids,
            "research_run_id": row.research_run_id,
            "code_version": row.code_version,
            "config_version": row.config_version,
            "metadata": row.metadata_json,
        }
    )


class SqlAlchemyResearchRepository:
    """Research persistence with referential evidence links."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_run(self, run: ResearchRun) -> ResearchRun:
        existing = self.session.scalar(
            select(ResearchRunRecord).where(ResearchRunRecord.run_key == run.run_key)
        )
        if existing:
            return _run_from_record(existing)
        self.session.add(
            ResearchRunRecord(
                research_run_id=run.research_run_id,
                run_key=run.run_key,
                run_type=run.run_type,
                as_of=run.as_of,
                data_cutoff_at=run.data_cutoff_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                status=run.status.value,
                code_version=run.code_version,
                config_version=run.config_version,
                ingestion_batch_ids=_uuid_strings(run.ingestion_batch_ids),
                error_message=run.error_message,
            )
        )
        self.session.flush()
        return run

    def add_evidence(self, evidence: EvidenceReference) -> EvidenceReference:
        existing = self.session.scalar(
            select(EvidenceReferenceRecord).where(
                EvidenceReferenceRecord.source_type == evidence.source_type.value,
                EvidenceReferenceRecord.provider == evidence.provider,
                EvidenceReferenceRecord.source_record_id == evidence.source_record_id,
                EvidenceReferenceRecord.available_at == evidence.available_at,
            )
        )
        if existing:
            return _evidence_from_record(existing)
        self.session.add(
            EvidenceReferenceRecord(
                evidence_id=evidence.evidence_id,
                source_type=evidence.source_type.value,
                provider=evidence.provider,
                source_record_id=evidence.source_record_id,
                effective_at=evidence.effective_at,
                available_at=evidence.available_at,
                ingested_at=evidence.ingested_at,
                uri=evidence.uri,
                label=evidence.label,
                content_hash=evidence.content_hash,
                metadata_json=evidence.model_dump(mode="json")["metadata"],
            )
        )
        self.session.flush()
        return evidence

    def add_finding(self, finding: ResearchFinding) -> ResearchFinding:
        existing = self.session.scalar(
            select(ResearchFindingRecord).where(
                ResearchFindingRecord.finding_key == finding.finding_key
            )
        )
        if existing:
            return _finding_from_record(existing)
        payload = finding.model_dump(mode="json")
        self.session.add(
            ResearchFindingRecord(
                finding_id=finding.finding_id,
                finding_key=finding.finding_key,
                research_run_id=finding.research_run_id,
                security_id=finding.security_id,
                category=finding.category.value,
                title=finding.title,
                change=finding.change,
                direction=finding.direction,
                effective_at=finding.effective_at,
                available_at=finding.available_at,
                created_at=finding.created_at,
                metrics=payload["metrics"],
                feature_snapshot_ids=_uuid_strings(finding.feature_snapshot_ids),
                evidence_ids=_uuid_strings(finding.evidence_ids),
                score=payload["score"],
                materiality_tier=finding.materiality_tier.value,
                confidence=finding.confidence.value,
                portfolio_weight=finding.portfolio_weight,
                metadata_json=payload["metadata"],
            )
        )
        self.session.flush()
        for evidence_id in finding.evidence_ids:
            self.session.execute(
                insert(research_finding_evidence).values(
                    finding_id=finding.finding_id, evidence_id=evidence_id
                )
            )
        return finding

    def add_card(self, card: ResearchCard) -> ResearchCard:
        existing = self.session.scalar(
            select(ResearchCardRecord).where(ResearchCardRecord.card_key == card.card_key)
        )
        if existing:
            return _card_from_record(existing)
        payload = card.model_dump(mode="json")
        self.session.add(
            ResearchCardRecord(
                card_id=card.card_id,
                card_key=card.card_key,
                research_run_id=card.research_run_id,
                security_id=card.security_id,
                as_of=card.as_of,
                created_at=card.created_at,
                materiality_tier=card.materiality_tier.value,
                change=card.change,
                quant_evidence=payload["quant_evidence"],
                context=payload["context"],
                thesis_impact=card.thesis_impact.value,
                thesis_node_id=card.thesis_node_id,
                key_risk_or_opportunity=card.key_risk_or_opportunity,
                confidence=card.confidence.value,
                next_research_question=card.next_research_question,
                finding_ids=_uuid_strings(card.finding_ids),
                evidence_ids=_uuid_strings(card.evidence_ids),
                renderer_version=card.renderer_version,
                model_version=card.model_version,
                data_cutoff_at=card.data_cutoff_at,
                metadata_json=payload["metadata"],
            )
        )
        self.session.flush()
        for finding_id in card.finding_ids:
            self.session.execute(
                insert(research_card_finding).values(card_id=card.card_id, finding_id=finding_id)
            )
        for evidence_id in card.evidence_ids:
            self.session.execute(
                insert(research_card_evidence).values(card_id=card.card_id, evidence_id=evidence_id)
            )
        return card

    def add_feedback(self, feedback: MaterialityFeedback) -> MaterialityFeedback:
        existing = self.session.get(MaterialityFeedbackRecord, feedback.feedback_id)
        if existing:
            return MaterialityFeedback.model_validate(
                {
                    "feedback_id": existing.feedback_id,
                    "card_id": existing.card_id,
                    "feedback": existing.feedback,
                    "user_id": existing.user_id,
                    "comment": existing.comment,
                    "created_at": existing.created_at,
                }
            )
        values = feedback.model_dump(mode="python")
        values["feedback"] = feedback.feedback.value
        self.session.add(MaterialityFeedbackRecord(**values))
        self.session.flush()
        return feedback

    def cards_as_of(
        self,
        *,
        knowledge_time: datetime,
        security_id: UUID | None = None,
    ) -> Sequence[ResearchCard]:
        known = ensure_utc(knowledge_time)
        statement = (
            select(ResearchCardRecord)
            .where(
                ResearchCardRecord.data_cutoff_at <= known,
                ResearchCardRecord.created_at <= known,
            )
            .order_by(
                ResearchCardRecord.as_of.desc(),
                ResearchCardRecord.created_at.desc(),
                ResearchCardRecord.security_id,
                ResearchCardRecord.card_id,
            )
        )
        if security_id is not None:
            statement = statement.where(ResearchCardRecord.security_id == security_id)
        return tuple(_card_from_record(row) for row in self.session.scalars(statement))


def _run_from_record(row: ResearchRunRecord) -> ResearchRun:
    return ResearchRun.model_validate(
        {
            "research_run_id": row.research_run_id,
            "run_key": row.run_key,
            "run_type": row.run_type,
            "as_of": row.as_of,
            "data_cutoff_at": row.data_cutoff_at,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "status": row.status,
            "code_version": row.code_version,
            "config_version": row.config_version,
            "ingestion_batch_ids": row.ingestion_batch_ids,
            "error_message": row.error_message,
        }
    )


def _evidence_from_record(row: EvidenceReferenceRecord) -> EvidenceReference:
    return EvidenceReference.model_validate(
        {
            "evidence_id": row.evidence_id,
            "source_type": row.source_type,
            "provider": row.provider,
            "source_record_id": row.source_record_id,
            "effective_at": row.effective_at,
            "available_at": row.available_at,
            "ingested_at": row.ingested_at,
            "uri": row.uri,
            "label": row.label,
            "content_hash": row.content_hash,
            "metadata": row.metadata_json,
        }
    )


def _finding_from_record(row: ResearchFindingRecord) -> ResearchFinding:
    return ResearchFinding.model_validate(
        {
            "finding_id": row.finding_id,
            "finding_key": row.finding_key,
            "research_run_id": row.research_run_id,
            "security_id": row.security_id,
            "category": row.category,
            "title": row.title,
            "change": row.change,
            "direction": row.direction,
            "effective_at": row.effective_at,
            "available_at": row.available_at,
            "created_at": row.created_at,
            "metrics": row.metrics,
            "feature_snapshot_ids": row.feature_snapshot_ids,
            "evidence_ids": row.evidence_ids,
            "score": row.score,
            "materiality_tier": row.materiality_tier,
            "confidence": row.confidence,
            "portfolio_weight": row.portfolio_weight,
            "metadata": row.metadata_json,
        }
    )


def _card_from_record(row: ResearchCardRecord) -> ResearchCard:
    return ResearchCard.model_validate(
        {
            "card_id": row.card_id,
            "card_key": row.card_key,
            "research_run_id": row.research_run_id,
            "security_id": row.security_id,
            "as_of": row.as_of,
            "created_at": row.created_at,
            "materiality_tier": row.materiality_tier,
            "change": row.change,
            "quant_evidence": row.quant_evidence,
            "context": row.context,
            "thesis_impact": row.thesis_impact,
            "thesis_node_id": row.thesis_node_id,
            "key_risk_or_opportunity": row.key_risk_or_opportunity,
            "confidence": row.confidence,
            "next_research_question": row.next_research_question,
            "finding_ids": row.finding_ids,
            "evidence_ids": row.evidence_ids,
            "renderer_version": row.renderer_version,
            "model_version": row.model_version,
            "data_cutoff_at": row.data_cutoff_at,
            "metadata": row.metadata_json,
        }
    )
