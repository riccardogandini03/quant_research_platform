"""Research findings, cards, thesis, and reproducibility contracts."""

from __future__ import annotations

from math import isfinite
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from quant_raas.common.clock import UtcDatetime, utc_now
from quant_raas.domain.base import DomainModel
from quant_raas.domain.enums import (
    BatchStatus,
    ConfidenceLevel,
    FeedbackKind,
    FindingCategory,
    MaterialityTier,
    SourceType,
    ThesisImpact,
    ThesisStatus,
)


class ResearchRun(DomainModel):
    """One pinned execution of the daily research pipeline."""

    research_run_id: UUID = Field(default_factory=uuid4)
    run_key: str = Field(min_length=8, max_length=160)
    run_type: str = Field(default="daily", min_length=1, max_length=80)
    as_of: UtcDatetime
    data_cutoff_at: UtcDatetime
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: BatchStatus = BatchStatus.PENDING
    code_version: str = Field(min_length=1, max_length=80)
    config_version: str = Field(min_length=1, max_length=80)
    ingestion_batch_ids: tuple[UUID, ...] = ()
    error_message: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_run_timing(self) -> ResearchRun:
        if self.as_of > self.data_cutoff_at:
            raise ValueError("as_of cannot be later than data_cutoff_at")
        if self.data_cutoff_at > self.started_at:
            raise ValueError("data_cutoff_at cannot be later than started_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if (
            self.status in {BatchStatus.SUCCEEDED, BatchStatus.PARTIAL, BatchStatus.FAILED}
            and self.completed_at is None
        ):
            raise ValueError("terminal research runs require completed_at")
        return self


class EvidenceReference(DomainModel):
    """Immutable pointer from research output back to an input record."""

    evidence_id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    provider: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=256)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    ingested_at: UtcDatetime
    uri: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=300)
    content_hash: str | None = Field(default=None, min_length=8, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_timing(self) -> EvidenceReference:
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot be later than ingested_at")
        return self


class QuantMetric(DomainModel):
    """Typed numerical evidence shown on a finding or card."""

    name: str = Field(min_length=1, max_length=160)
    value: float
    unit: str | None = Field(default=None, max_length=40)
    horizon: str | None = Field(default=None, max_length=80)
    as_of: UtcDatetime
    feature_snapshot_id: UUID | None = None

    @field_validator("value")
    @classmethod
    def validate_metric_value(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("metric values must be finite")
        return value


class MaterialityScore(DomainModel):
    """Auditable deterministic score and its portfolio priority modifier."""

    component_scores: dict[str, float] = Field(default_factory=dict)
    component_weights: dict[str, float] = Field(default_factory=dict)
    raw_score: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    priority_modifier: float = Field(default=1, ge=0)
    priority_score: float = Field(ge=0)
    config_version: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_components(self) -> MaterialityScore:
        if set(self.component_scores) - set(self.component_weights):
            raise ValueError("every scored component must have a configured weight")
        if any(not 0 <= value <= 1 for value in self.component_scores.values()):
            raise ValueError("component scores must be between zero and one")
        if any(value < 0 for value in self.component_weights.values()):
            raise ValueError("component weights cannot be negative")
        return self


class ResearchFinding(DomainModel):
    """Typed candidate finding emitted by a quant module."""

    finding_id: UUID = Field(default_factory=uuid4)
    finding_key: str = Field(min_length=8, max_length=200)
    research_run_id: UUID
    security_id: UUID
    category: FindingCategory
    title: str = Field(min_length=1, max_length=300)
    change: str = Field(min_length=1, max_length=2000)
    direction: str | None = Field(default=None, max_length=40)
    effective_at: UtcDatetime
    available_at: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)
    metrics: tuple[QuantMetric, ...] = ()
    feature_snapshot_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    score: MaterialityScore
    materiality_tier: MaterialityTier
    confidence: ConfidenceLevel
    portfolio_weight: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_finding_timing(self) -> ResearchFinding:
        # Upcoming earnings can generate a valid risk finding before event time.
        if self.available_at > self.created_at:
            raise ValueError("available_at cannot be later than created_at")
        return self


class CardContext(DomainModel):
    """Portfolio and benchmark context, never accounting-grade attribution."""

    position_weight: float | None = None
    contribution_bps: float | None = None
    benchmark_return: float | None = None
    sector_return: float | None = None
    peer_return: float | None = None
    macro_event: str | None = Field(default=None, max_length=500)
    notes: tuple[str, ...] = ()


class ResearchCard(DomainModel):
    """Persisted, deterministic Phase-1 rendering of related findings."""

    card_id: UUID = Field(default_factory=uuid4)
    card_key: str = Field(min_length=8, max_length=200)
    research_run_id: UUID
    security_id: UUID
    as_of: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)
    materiality_tier: MaterialityTier
    change: str = Field(min_length=1, max_length=3000)
    quant_evidence: tuple[QuantMetric, ...] = ()
    context: CardContext = Field(default_factory=CardContext)
    thesis_impact: ThesisImpact = ThesisImpact.NONE
    thesis_node_id: str | None = Field(default=None, max_length=128)
    key_risk_or_opportunity: str | None = Field(default=None, max_length=1000)
    confidence: ConfidenceLevel
    next_research_question: str | None = Field(default=None, max_length=1000)
    finding_ids: tuple[UUID, ...] = ()
    evidence_ids: tuple[UUID, ...] = ()
    renderer_version: str = Field(min_length=1, max_length=80)
    model_version: str | None = Field(default=None, max_length=160)
    data_cutoff_at: UtcDatetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_card_timing(self) -> ResearchCard:
        if self.as_of > self.data_cutoff_at or self.data_cutoff_at > self.created_at:
            raise ValueError("card timing must satisfy as_of <= data_cutoff_at <= created_at")
        return self


class Thesis(DomainModel):
    """Stable identity for a PM-owned investment thesis."""

    thesis_id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    title: str = Field(min_length=1, max_length=300)
    status: ThesisStatus = ThesisStatus.ACTIVE
    created_at: UtcDatetime = Field(default_factory=utc_now)


class ThesisVersion(DomainModel):
    """Immutable thesis content; activation requires explicit PM approval."""

    thesis_version_id: UUID = Field(default_factory=uuid4)
    thesis_id: UUID
    version: int = Field(ge=1)
    valid_from: UtcDatetime
    valid_to: UtcDatetime | None = None
    nodes: dict[str, Any] = Field(default_factory=dict)
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: UtcDatetime
    created_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_thesis_version(self) -> ThesisVersion:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.approved_at > self.created_at:
            raise ValueError("approved_at cannot be later than created_at")
        return self


class MaterialityFeedback(DomainModel):
    """PM feedback retained separately from deterministic calculations."""

    feedback_id: UUID = Field(default_factory=uuid4)
    card_id: UUID
    feedback: FeedbackKind
    user_id: str | None = Field(default=None, max_length=160)
    comment: str | None = Field(default=None, max_length=2000)
    created_at: UtcDatetime = Field(default_factory=utc_now)
