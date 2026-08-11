"""SQLAlchemy 2 mappings for the core point-in-time schema.

Domain enums are stored as strings so schema evolution is explicit and remains
portable between SQLite development databases and PostgreSQL production.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from quant_raas.storage.base import Base, UTCDateTime


class SecurityRecord(Base):
    __tablename__ = "security"

    security_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    security_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    primary_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange_mic: Mapped[str | None] = mapped_column(String(4))
    exchange_timezone: Mapped[str | None] = mapped_column(String(80))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    region: Mapped[str | None] = mapped_column(String(120), index=True)
    sector: Mapped[str | None] = mapped_column(String(120), index=True)
    industry: Mapped[str | None] = mapped_column(String(160))
    first_trade_date: Mapped[date | None] = mapped_column(Date)
    last_trade_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class SecurityIdentifierRecord(Base):
    __tablename__ = "security_identifier"
    __table_args__ = (
        UniqueConstraint(
            "scheme",
            "value",
            "provider",
            "exchange_mic",
            "valid_from",
            name="uq_security_identifier_natural",
        ),
        Index(
            "ix_security_identifier_resolution",
            "value",
            "scheme",
            "valid_from",
            "valid_to",
        ),
    )

    identifier_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    # Empty strings avoid the inconsistent NULL behavior of composite unique
    # constraints across SQLite and PostgreSQL.
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    exchange_mic: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    valid_from: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    valid_to: Mapped[Any | None] = mapped_column(UTCDateTime())
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class BenchmarkMappingRecord(Base):
    __tablename__ = "benchmark_mapping"
    __table_args__ = (
        UniqueConstraint("security_id", "kind", "valid_from", name="uq_benchmark_mapping_natural"),
        Index(
            "ix_benchmark_mapping_as_of",
            "security_id",
            "kind",
            "valid_from",
            "valid_to",
        ),
    )

    mapping_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    benchmark_security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_from: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    valid_to: Mapped[Any | None] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    config_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class CoverageListRecord(Base):
    __tablename__ = "coverage_list"

    coverage_list_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class CoverageMemberRecord(Base):
    __tablename__ = "coverage_member"
    __table_args__ = (
        UniqueConstraint(
            "coverage_list_id",
            "security_id",
            "added_at",
            name="uq_coverage_member_natural",
        ),
        Index(
            "ix_coverage_member_as_of",
            "coverage_list_id",
            "added_at",
            "removed_at",
        ),
    )

    membership_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    coverage_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("coverage_list.coverage_list_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    removed_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    thesis_id: Mapped[str | None] = mapped_column(String(128))
    benchmark_security_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security.security_id", ondelete="SET NULL")
    )
    peer_group: Mapped[str | None] = mapped_column(String(160), index=True)
    source_identifier: Mapped[str] = mapped_column(String(128), nullable=False)


class PortfolioSnapshotRecord(Base):
    __tablename__ = "portfolio_snapshot"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "as_of", name="uq_portfolio_snapshot_name_as_of"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    portfolio_name: Mapped[str] = mapped_column(String(160), nullable=False)
    as_of: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False, index=True)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(260))
    source_hash: Mapped[str | None] = mapped_column(String(128))


class PortfolioPositionRecord(Base):
    __tablename__ = "portfolio_position"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "security_id", name="uq_portfolio_position_natural"),
    )

    position_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshot.snapshot_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="RESTRICT"), nullable=False
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    thesis_id: Mapped[str | None] = mapped_column(String(128))
    benchmark_security_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security.security_id", ondelete="SET NULL")
    )
    source_identifier: Mapped[str] = mapped_column(String(128), nullable=False)


class IngestionBatchRecord(Base):
    __tablename__ = "ingestion_batch"

    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    dataset: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class PriceBarRecord(Base):
    __tablename__ = "price_bar"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "frequency",
            "source",
            "effective_at",
            "available_at",
            name="uq_price_bar_vintage",
        ),
        Index(
            "ix_price_bar_pit",
            "security_id",
            "frequency",
            "effective_at",
            "available_at",
        ),
    )

    price_bar_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    ingested_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    adjustment_factor: Mapped[float | None] = mapped_column(Float)
    total_return_factor: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    provider_identifier: Mapped[str | None] = mapped_column(String(128))
    ingestion_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_batch.batch_id", ondelete="RESTRICT"), nullable=False
    )
    quality_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class CorporateActionRecord(Base):
    __tablename__ = "corporate_action"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_record_id",
            "available_at",
            name="uq_corporate_action_vintage",
        ),
    )

    corporate_action_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    ingested_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    ratio: Mapped[float | None] = mapped_column(Float)
    cash_amount: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    ingestion_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_batch.batch_id", ondelete="RESTRICT"), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class CompanyEventRecord(Base):
    __tablename__ = "company_event"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_record_id",
            "available_at",
            name="uq_company_event_vintage",
        ),
        Index("ix_company_event_pit", "security_id", "effective_at", "available_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    ingested_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    ingestion_batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_batch.batch_id", ondelete="RESTRICT"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ResearchRunRecord(Base):
    __tablename__ = "research_run"

    research_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False)
    as_of: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False, index=True)
    data_cutoff_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[Any | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), nullable=False)
    config_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ingestion_batch_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)


class EvidenceReferenceRecord(Base):
    __tablename__ = "evidence_reference"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "provider",
            "source_record_id",
            "available_at",
            name="uq_evidence_reference_natural",
        ),
        Index("ix_evidence_reference_pit", "effective_at", "available_at"),
    )

    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(256), nullable=False)
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    ingested_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    uri: Mapped[str | None] = mapped_column(String(2000))
    label: Mapped[str | None] = mapped_column(String(300))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class FeatureSnapshotRecord(Base):
    __tablename__ = "feature_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "feature_name",
            "feature_version",
            "effective_at",
            "available_at",
            "code_version",
            "config_version",
            name="uq_feature_snapshot_vintage",
        ),
        Index(
            "ix_feature_snapshot_pit",
            "security_id",
            "feature_name",
            "effective_at",
            "available_at",
        ),
    )

    feature_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    feature_name: Mapped[str] = mapped_column(String(160), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(80), nullable=False)
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    calculated_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40))
    window: Mapped[str | None] = mapped_column(String(80))
    quality_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    input_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    research_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_run.research_run_id", ondelete="CASCADE"), nullable=False
    )
    code_version: Mapped[str] = mapped_column(String(80), nullable=False)
    config_version: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class ResearchFindingRecord(Base):
    __tablename__ = "research_finding"

    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    finding_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    research_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_run.research_run_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    change: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(40))
    effective_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    available_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    metrics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    feature_snapshot_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    materiality_tier: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)
    portfolio_weight: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class ResearchCardRecord(Base):
    __tablename__ = "research_card"
    __table_args__ = (Index("ix_research_card_inbox", "as_of", "materiality_tier", "security_id"),)

    card_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    card_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    research_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_run.research_run_id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False
    )
    as_of: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    materiality_tier: Mapped[str] = mapped_column(String(40), nullable=False)
    change: Mapped[str] = mapped_column(Text, nullable=False)
    quant_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    thesis_impact: Mapped[str] = mapped_column(String(40), nullable=False)
    thesis_node_id: Mapped[str | None] = mapped_column(String(128))
    key_risk_or_opportunity: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)
    next_research_question: Mapped[str | None] = mapped_column(Text)
    finding_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    renderer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(160))
    data_cutoff_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


# Association tables make referential lineage queryable even though UUID lists
# are also retained in the JSON domain representation for convenient rendering.
research_card_finding = Table(
    "research_card_finding",
    Base.metadata,
    Column(
        "card_id",
        Uuid(as_uuid=True),
        ForeignKey("research_card.card_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "finding_id",
        Uuid(as_uuid=True),
        ForeignKey("research_finding.finding_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


research_finding_evidence = Table(
    "research_finding_evidence",
    Base.metadata,
    Column(
        "finding_id",
        Uuid(as_uuid=True),
        ForeignKey("research_finding.finding_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "evidence_id",
        Uuid(as_uuid=True),
        ForeignKey("evidence_reference.evidence_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


research_card_evidence = Table(
    "research_card_evidence",
    Base.metadata,
    Column(
        "card_id",
        Uuid(as_uuid=True),
        ForeignKey("research_card.card_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "evidence_id",
        Uuid(as_uuid=True),
        ForeignKey("evidence_reference.evidence_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class ThesisRecord(Base):
    __tablename__ = "thesis"

    thesis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    security_id: Mapped[UUID] = mapped_column(
        ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class ThesisVersionRecord(Base):
    __tablename__ = "thesis_version"
    __table_args__ = (UniqueConstraint("thesis_id", "version", name="uq_thesis_version_number"),)

    thesis_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    thesis_id: Mapped[UUID] = mapped_column(
        ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    valid_to: Mapped[Any | None] = mapped_column(UTCDateTime())
    nodes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    approved_by: Mapped[str] = mapped_column(String(160), nullable=False)
    approved_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)


class MaterialityFeedbackRecord(Base):
    __tablename__ = "materiality_feedback"

    feedback_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    card_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_card.card_id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(160))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=False)
