"""Create the core Phase-1 point-in-time schema.

Revision ID: 20260811_0001
Revises: None
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create identity, market-data, feature, and research-lineage tables."""

    op.create_table(
        "security",
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("security_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("primary_currency", sa.String(3), nullable=False),
        sa.Column("exchange_mic", sa.String(4)),
        sa.Column("exchange_timezone", sa.String(80)),
        sa.Column("country_code", sa.String(2)),
        sa.Column("region", sa.String(120)),
        sa.Column("sector", sa.String(120)),
        sa.Column("industry", sa.String(160)),
        sa.Column("first_trade_date", sa.Date()),
        sa.Column("last_trade_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("security_id", name="pk_security"),
    )
    op.create_index("ix_security_status", "security", ["status"])
    op.create_index("ix_security_country_code", "security", ["country_code"])
    op.create_index("ix_security_region", "security", ["region"])
    op.create_index("ix_security_sector", "security", ["sector"])

    op.create_table(
        "coverage_list",
        sa.Column("coverage_list_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("coverage_list_id", name="pk_coverage_list"),
        sa.UniqueConstraint("name", name="uq_coverage_list_name"),
    )

    op.create_table(
        "portfolio_snapshot",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_name", sa.String(160), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_name", sa.String(260)),
        sa.Column("source_hash", sa.String(128)),
        sa.PrimaryKeyConstraint("snapshot_id", name="pk_portfolio_snapshot"),
        sa.UniqueConstraint("portfolio_name", "as_of", name="uq_portfolio_snapshot_name_as_of"),
    )
    op.create_index("ix_portfolio_snapshot_as_of", "portfolio_snapshot", ["as_of"])

    op.create_table(
        "ingestion_batch",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("batch_key", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("dataset", sa.String(80), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("request_fingerprint", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.PrimaryKeyConstraint("batch_id", name="pk_ingestion_batch"),
        sa.UniqueConstraint("batch_key", name="uq_ingestion_batch_batch_key"),
    )
    op.create_index("ix_ingestion_batch_provider", "ingestion_batch", ["provider"])

    op.create_table(
        "research_run",
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("run_key", sa.String(160), nullable=False),
        sa.Column("run_type", sa.String(80), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("code_version", sa.String(80), nullable=False),
        sa.Column("config_version", sa.String(80), nullable=False),
        sa.Column("ingestion_batch_ids", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.PrimaryKeyConstraint("research_run_id", name="pk_research_run"),
        sa.UniqueConstraint("run_key", name="uq_research_run_run_key"),
    )
    op.create_index("ix_research_run_as_of", "research_run", ["as_of"])

    op.create_table(
        "evidence_reference",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(256), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uri", sa.String(2000)),
        sa.Column("label", sa.String(300)),
        sa.Column("content_hash", sa.String(128)),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("evidence_id", name="pk_evidence_reference"),
        sa.UniqueConstraint(
            "source_type",
            "provider",
            "source_record_id",
            "available_at",
            name="uq_evidence_reference_natural",
        ),
    )
    op.create_index(
        "ix_evidence_reference_pit",
        "evidence_reference",
        ["effective_at", "available_at"],
    )

    op.create_table(
        "thesis",
        sa.Column("thesis_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_thesis_security_id_security",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("thesis_id", name="pk_thesis"),
    )
    op.create_index("ix_thesis_security_id", "thesis", ["security_id"])

    op.create_table(
        "security_identifier",
        sa.Column("identifier_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("scheme", sa.String(40), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("exchange_mic", sa.String(4), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_security_identifier_security_id_security",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("identifier_id", name="pk_security_identifier"),
        sa.UniqueConstraint(
            "scheme",
            "value",
            "provider",
            "exchange_mic",
            "valid_from",
            name="uq_security_identifier_natural",
        ),
    )
    op.create_index(
        "ix_security_identifier_resolution",
        "security_identifier",
        ["value", "scheme", "valid_from", "valid_to"],
    )
    op.create_index("ix_security_identifier_security_id", "security_identifier", ["security_id"])

    op.create_table(
        "benchmark_mapping",
        sa.Column("mapping_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("benchmark_security_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("config_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_benchmark_mapping_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_security_id"],
            ["security.security_id"],
            name="fk_benchmark_mapping_benchmark_security_id_security",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("mapping_id", name="pk_benchmark_mapping"),
        sa.UniqueConstraint(
            "security_id", "kind", "valid_from", name="uq_benchmark_mapping_natural"
        ),
    )
    op.create_index(
        "ix_benchmark_mapping_as_of",
        "benchmark_mapping",
        ["security_id", "kind", "valid_from", "valid_to"],
    )

    op.create_table(
        "coverage_member",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("coverage_list_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("thesis_id", sa.String(128)),
        sa.Column("benchmark_security_id", sa.Uuid()),
        sa.Column("peer_group", sa.String(160)),
        sa.Column("source_identifier", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["coverage_list_id"],
            ["coverage_list.coverage_list_id"],
            name="fk_coverage_member_coverage_list_id_coverage_list",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_coverage_member_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_security_id"],
            ["security.security_id"],
            name="fk_coverage_member_benchmark_security_id_security",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("membership_id", name="pk_coverage_member"),
        sa.UniqueConstraint(
            "coverage_list_id",
            "security_id",
            "added_at",
            name="uq_coverage_member_natural",
        ),
    )
    op.create_index(
        "ix_coverage_member_as_of",
        "coverage_member",
        ["coverage_list_id", "added_at", "removed_at"],
    )
    op.create_index("ix_coverage_member_peer_group", "coverage_member", ["peer_group"])

    op.create_table(
        "portfolio_position",
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Numeric(20, 10), nullable=False),
        sa.Column("thesis_id", sa.String(128)),
        sa.Column("benchmark_security_id", sa.Uuid()),
        sa.Column("source_identifier", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["portfolio_snapshot.snapshot_id"],
            name="fk_portfolio_position_snapshot_id_portfolio_snapshot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_portfolio_position_security_id_security",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_security_id"],
            ["security.security_id"],
            name="fk_portfolio_position_benchmark_security_id_security",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("position_id", name="pk_portfolio_position"),
        sa.UniqueConstraint("snapshot_id", "security_id", name="uq_portfolio_position_natural"),
    )

    op.create_table(
        "price_bar",
        sa.Column("price_bar_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("adjusted_close", sa.Float()),
        sa.Column("volume", sa.Float()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("adjustment_factor", sa.Float()),
        sa.Column("total_return_factor", sa.Float()),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(256), nullable=False),
        sa.Column("provider_identifier", sa.String(128)),
        sa.Column("ingestion_batch_id", sa.Uuid(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_price_bar_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"],
            ["ingestion_batch.batch_id"],
            name="fk_price_bar_ingestion_batch_id_ingestion_batch",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("price_bar_id", name="pk_price_bar"),
        sa.UniqueConstraint(
            "security_id",
            "frequency",
            "source",
            "effective_at",
            "available_at",
            name="uq_price_bar_vintage",
        ),
    )
    op.create_index(
        "ix_price_bar_pit",
        "price_bar",
        ["security_id", "frequency", "effective_at", "available_at"],
    )

    op.create_table(
        "corporate_action",
        sa.Column("corporate_action_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ratio", sa.Float()),
        sa.Column("cash_amount", sa.Float()),
        sa.Column("currency", sa.String(3)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(256), nullable=False),
        sa.Column("ingestion_batch_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_corporate_action_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"],
            ["ingestion_batch.batch_id"],
            name="fk_corporate_action_ingestion_batch_id_ingestion_batch",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("corporate_action_id", name="pk_corporate_action"),
        sa.UniqueConstraint(
            "source",
            "source_record_id",
            "available_at",
            name="uq_corporate_action_vintage",
        ),
    )
    op.create_index("ix_corporate_action_security_id", "corporate_action", ["security_id"])

    op.create_table(
        "company_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid()),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(256), nullable=False),
        sa.Column("ingestion_batch_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_company_event_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"],
            ["ingestion_batch.batch_id"],
            name="fk_company_event_ingestion_batch_id_ingestion_batch",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_company_event"),
        sa.UniqueConstraint(
            "source",
            "source_record_id",
            "available_at",
            name="uq_company_event_vintage",
        ),
    )
    op.create_index(
        "ix_company_event_pit",
        "company_event",
        ["security_id", "effective_at", "available_at"],
    )
    op.create_index("ix_company_event_security_id", "company_event", ["security_id"])

    op.create_table(
        "feature_snapshot",
        sa.Column("feature_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("feature_name", sa.String(160), nullable=False),
        sa.Column("feature_version", sa.String(80), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("window", sa.String(80)),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("input_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("code_version", sa.String(80), nullable=False),
        sa.Column("config_version", sa.String(80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_feature_snapshot_security_id_security",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_run.research_run_id"],
            name="fk_feature_snapshot_research_run_id_research_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feature_snapshot_id", name="pk_feature_snapshot"),
        sa.UniqueConstraint(
            "security_id",
            "feature_name",
            "feature_version",
            "effective_at",
            "available_at",
            "code_version",
            "config_version",
            name="uq_feature_snapshot_vintage",
        ),
    )
    op.create_index(
        "ix_feature_snapshot_pit",
        "feature_snapshot",
        ["security_id", "feature_name", "effective_at", "available_at"],
    )

    op.create_table(
        "research_finding",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("finding_key", sa.String(200), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("change", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(40)),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("feature_snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("score", sa.JSON(), nullable=False),
        sa.Column("materiality_tier", sa.String(40), nullable=False),
        sa.Column("confidence", sa.String(40), nullable=False),
        sa.Column("portfolio_weight", sa.Float()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_run.research_run_id"],
            name="fk_research_finding_research_run_id_research_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_research_finding_security_id_security",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("finding_id", name="pk_research_finding"),
        sa.UniqueConstraint("finding_key", name="uq_research_finding_finding_key"),
    )
    op.create_index("ix_research_finding_security_id", "research_finding", ["security_id"])
    op.create_index(
        "ix_research_finding_materiality_tier",
        "research_finding",
        ["materiality_tier"],
    )

    op.create_table(
        "research_card",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("card_key", sa.String(200), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("materiality_tier", sa.String(40), nullable=False),
        sa.Column("change", sa.Text(), nullable=False),
        sa.Column("quant_evidence", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("thesis_impact", sa.String(40), nullable=False),
        sa.Column("thesis_node_id", sa.String(128)),
        sa.Column("key_risk_or_opportunity", sa.Text()),
        sa.Column("confidence", sa.String(40), nullable=False),
        sa.Column("next_research_question", sa.Text()),
        sa.Column("finding_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("renderer_version", sa.String(80), nullable=False),
        sa.Column("model_version", sa.String(160)),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_run.research_run_id"],
            name="fk_research_card_research_run_id_research_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["security_id"],
            ["security.security_id"],
            name="fk_research_card_security_id_security",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("card_id", name="pk_research_card"),
        sa.UniqueConstraint("card_key", name="uq_research_card_card_key"),
    )
    op.create_index(
        "ix_research_card_inbox",
        "research_card",
        ["as_of", "materiality_tier", "security_id"],
    )

    op.create_table(
        "thesis_version",
        sa.Column("thesis_version_id", sa.Uuid(), nullable=False),
        sa.Column("thesis_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("nodes", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(160), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["thesis_id"],
            ["thesis.thesis_id"],
            name="fk_thesis_version_thesis_id_thesis",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("thesis_version_id", name="pk_thesis_version"),
        sa.UniqueConstraint("thesis_id", "version", name="uq_thesis_version_number"),
    )

    op.create_table(
        "materiality_feedback",
        sa.Column("feedback_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("feedback", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(160)),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["research_card.card_id"],
            name="fk_materiality_feedback_card_id_research_card",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("feedback_id", name="pk_materiality_feedback"),
    )
    op.create_index("ix_materiality_feedback_card_id", "materiality_feedback", ["card_id"])

    op.create_table(
        "research_card_finding",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["research_card.card_id"],
            name="fk_research_card_finding_card_id_research_card",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["research_finding.finding_id"],
            name="fk_research_card_finding_finding_id_research_finding",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("card_id", "finding_id", name="pk_research_card_finding"),
    )

    op.create_table(
        "research_finding_evidence",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["research_finding.finding_id"],
            name="fk_research_finding_evidence_finding_id_research_finding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_reference.evidence_id"],
            name="fk_research_finding_evidence_evidence_id_evidence_reference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("finding_id", "evidence_id", name="pk_research_finding_evidence"),
    )

    op.create_table(
        "research_card_evidence",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["research_card.card_id"],
            name="fk_research_card_evidence_card_id_research_card",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_reference.evidence_id"],
            name="fk_research_card_evidence_evidence_id_evidence_reference",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("card_id", "evidence_id", name="pk_research_card_evidence"),
    )


def downgrade() -> None:
    """Drop the initial schema in reverse dependency order."""

    op.drop_table("research_card_evidence")
    op.drop_table("research_finding_evidence")
    op.drop_table("research_card_finding")
    op.drop_index("ix_materiality_feedback_card_id", table_name="materiality_feedback")
    op.drop_table("materiality_feedback")
    op.drop_table("thesis_version")
    op.drop_index("ix_research_card_inbox", table_name="research_card")
    op.drop_table("research_card")
    op.drop_index("ix_research_finding_materiality_tier", table_name="research_finding")
    op.drop_index("ix_research_finding_security_id", table_name="research_finding")
    op.drop_table("research_finding")
    op.drop_index("ix_feature_snapshot_pit", table_name="feature_snapshot")
    op.drop_table("feature_snapshot")
    op.drop_index("ix_company_event_security_id", table_name="company_event")
    op.drop_index("ix_company_event_pit", table_name="company_event")
    op.drop_table("company_event")
    op.drop_index("ix_corporate_action_security_id", table_name="corporate_action")
    op.drop_table("corporate_action")
    op.drop_index("ix_price_bar_pit", table_name="price_bar")
    op.drop_table("price_bar")
    op.drop_table("portfolio_position")
    op.drop_index("ix_coverage_member_peer_group", table_name="coverage_member")
    op.drop_index("ix_coverage_member_as_of", table_name="coverage_member")
    op.drop_table("coverage_member")
    op.drop_index("ix_benchmark_mapping_as_of", table_name="benchmark_mapping")
    op.drop_table("benchmark_mapping")
    op.drop_index("ix_security_identifier_security_id", table_name="security_identifier")
    op.drop_index("ix_security_identifier_resolution", table_name="security_identifier")
    op.drop_table("security_identifier")
    op.drop_index("ix_thesis_security_id", table_name="thesis")
    op.drop_table("thesis")
    op.drop_index("ix_evidence_reference_pit", table_name="evidence_reference")
    op.drop_table("evidence_reference")
    op.drop_index("ix_research_run_as_of", table_name="research_run")
    op.drop_table("research_run")
    op.drop_index("ix_ingestion_batch_provider", table_name="ingestion_batch")
    op.drop_table("ingestion_batch")
    op.drop_index("ix_portfolio_snapshot_as_of", table_name="portfolio_snapshot")
    op.drop_table("portfolio_snapshot")
    op.drop_table("coverage_list")
    op.drop_index("ix_security_sector", table_name="security")
    op.drop_index("ix_security_region", table_name="security")
    op.drop_index("ix_security_country_code", table_name="security")
    op.drop_index("ix_security_status", table_name="security")
    op.drop_table("security")
