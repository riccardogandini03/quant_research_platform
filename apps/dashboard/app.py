"""Minimal research inbox, company diagnostics, uploads, and data quality UI."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, time
from uuid import UUID

import streamlit as st
from sqlalchemy import desc, select

from quant_raas.config import get_settings
from quant_raas.domain.enums import FeedbackKind
from quant_raas.domain.research import MaterialityFeedback
from quant_raas.research.cards import render_card_markdown
from quant_raas.runtime import repositories_for
from quant_raas.security_master.importer import parse_coverage_csv, parse_holdings_csv
from quant_raas.security_master.service import SecurityMasterService
from quant_raas.storage.models import IngestionBatchRecord, ResearchRunRecord
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine

st.set_page_config(page_title="Quant RaaS", page_icon="📊", layout="wide")


@st.cache_resource
def _session_factory():
    settings = get_settings()
    engine = create_sql_engine(settings)
    if settings.environment in {"development", "test"}:
        create_schema(engine)
    return create_session_factory(engine)


def _utc_start(selected_date) -> datetime:
    return datetime.combine(selected_date, time.min, tzinfo=UTC)


def _security_labels(session) -> dict[UUID, str]:
    return {
        security.security_id: security.name
        for security in repositories_for(session).securities.list_securities(active_only=False)
    }


st.title("Quant Research Inbox")
st.caption(
    "Evidence-backed research diagnostics. Holdings add relevance context; this is not an OMS "
    "or accounting-grade attribution system."
)

inbox_tab, company_tab, upload_tab, quality_tab = st.tabs(
    ["Research Inbox", "Company", "Coverage & Holdings", "Data Quality"]
)

with inbox_tab:
    minimum_tier = st.selectbox(
        "Minimum materiality",
        ["routine", "watch", "material", "critical"],
        index=1,
    )
    tier_rank = {"routine": 0, "watch": 1, "material": 2, "critical": 3}
    with _session_factory()() as session:
        repos = repositories_for(session)
        cards = repos.research.cards_as_of(knowledge_time=datetime.now(UTC))
        labels = _security_labels(session)
    visible = [
        card for card in cards if tier_rank[card.materiality_tier.value] >= tier_rank[minimum_tier]
    ]
    # Rank material tiers first and show the newest snapshot first within a tier.
    visible.sort(
        key=lambda card: (tier_rank[card.materiality_tier.value], card.as_of), reverse=True
    )
    if not visible:
        st.info("No cards meet this threshold. Run the daily research workflow or select Routine.")
    for card in visible:
        label = labels.get(card.security_id, str(card.security_id))
        with st.expander(f"{label} — {card.materiality_tier.value.upper()}"):
            st.markdown(render_card_markdown(card, security_label=label))
            st.caption(f"Data cutoff: {card.data_cutoff_at.isoformat()} · Card ID: {card.card_id}")
            cols = st.columns(5)
            for column, feedback in zip(
                cols,
                ("Useful", "Noise", "Already known", "Wrong", "Investigate"),
                strict=True,
            ):
                # Feedback persistence is connected through the API/repository;
                if column.button(feedback, key=f"{card.card_id}-{feedback}"):
                    feedback_kind = {
                        "Useful": FeedbackKind.USEFUL,
                        "Noise": FeedbackKind.NOISE,
                        "Already known": FeedbackKind.ALREADY_KNOWN,
                        "Wrong": FeedbackKind.WRONG,
                        "Investigate": FeedbackKind.INVESTIGATE,
                    }[feedback]
                    with _session_factory().begin() as feedback_session:
                        repositories_for(feedback_session).research.add_feedback(
                            MaterialityFeedback(card_id=card.card_id, feedback=feedback_kind)
                        )
                    st.session_state[f"feedback-{card.card_id}"] = feedback
            if value := st.session_state.get(f"feedback-{card.card_id}"):
                st.success(f"Feedback selected: {value}")

with company_tab:
    with _session_factory()() as session:
        repos = repositories_for(session)
        securities = repos.securities.list_securities(active_only=False)
        labels = {security.security_id: security.name for security in securities}
    if not securities:
        st.info(
            "No securities are registered. Seed the demo or register the security master first."
        )
    else:
        selected = st.selectbox(
            "Security",
            options=[security.security_id for security in securities],
            format_func=lambda value: labels[value],
        )
        with _session_factory()() as session:
            cards = repositories_for(session).research.cards_as_of(
                knowledge_time=datetime.now(UTC), security_id=selected
            )
        if cards:
            st.markdown(render_card_markdown(cards[0], security_label=labels[selected]))
        else:
            st.info("No daily snapshot is available for this security.")

with upload_tab:
    upload_kind = st.radio("Upload type", ["Coverage", "Holdings"], horizontal=True)
    uploaded = st.file_uploader("CSV file", type=["csv"])
    as_of_date = st.date_input("As-of date")
    list_name = st.text_input(
        "Coverage list name" if upload_kind == "Coverage" else "Portfolio name",
        value="Research Coverage" if upload_kind == "Coverage" else "Research Context",
    )
    if uploaded is not None:
        content = uploaded.getvalue()
        parsed = (
            parse_coverage_csv(content)
            if upload_kind == "Coverage"
            else parse_holdings_csv(content)
        )
        st.metric("Valid rows", len(parsed.rows))
        if parsed.issues:
            st.dataframe([asdict(issue) for issue in parsed.issues], use_container_width=True)
        else:
            st.success("CSV structure is valid and ready for security-master resolution.")
        if st.button("Resolve and import", disabled=not parsed.is_valid):
            factory = _session_factory()
            with factory.begin() as session:
                repos = repositories_for(session)
                settings = get_settings()
                service = SecurityMasterService(
                    repos.securities,
                    repos.portfolios,
                    default_benchmark_identifier=settings.default_benchmark_identifier,
                    sector_benchmark_identifiers=settings.sector_benchmark_identifiers,
                )
                if upload_kind == "Coverage":
                    result = service.import_coverage(
                        parsed.rows,
                        name=list_name,
                        as_of=_utc_start(as_of_date),
                    )
                else:
                    result = service.import_holdings(
                        parsed.rows,
                        portfolio_name=list_name,
                        as_of=_utc_start(as_of_date),
                        source_name=uploaded.name,
                        source_hash=parsed.source_hash,
                    )
            if result.is_valid:
                st.success("Import completed.")
            else:
                st.error("Some identifiers could not be resolved.")
                st.dataframe([asdict(issue) for issue in result.issues], use_container_width=True)

with quality_tab:
    with _session_factory()() as session:
        latest_batch = session.scalar(
            select(IngestionBatchRecord).order_by(desc(IngestionBatchRecord.started_at)).limit(1)
        )
        latest_run = session.scalar(
            select(ResearchRunRecord).order_by(desc(ResearchRunRecord.started_at)).limit(1)
        )
    left, right = st.columns(2)
    left.subheader("Latest ingestion")
    left.json(
        {
            "status": latest_batch.status if latest_batch else "never run",
            "provider": latest_batch.provider if latest_batch else None,
            "rows": latest_batch.row_count if latest_batch else 0,
            "completed_at": str(latest_batch.completed_at) if latest_batch else None,
            "error": latest_batch.error_message if latest_batch else None,
        }
    )
    right.subheader("Latest research run")
    right.json(
        {
            "status": latest_run.status if latest_run else "never run",
            "as_of": str(latest_run.as_of) if latest_run else None,
            "completed_at": str(latest_run.completed_at) if latest_run else None,
            "error": latest_run.error_message if latest_run else None,
        }
    )

st.sidebar.info(
    "Backtest Lab, filing/news synthesis, estimates, valuation history, and licensed vendor "
    "automation are later-phase capabilities and are not presented as active here."
)
