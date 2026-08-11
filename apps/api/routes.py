"""HTTP routes for validation, research execution, and readback."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from apps.api.dependencies import database_session
from apps.api.schemas import DailyRunRequest, FeedbackRequest, SecurityRegistration
from quant_raas.common.clock import ensure_utc, utc_now
from quant_raas.config import get_settings
from quant_raas.domain.research import MaterialityFeedback
from quant_raas.domain.security import Security, SecurityIdentifier
from quant_raas.runtime import materiality_scorer, repositories_for
from quant_raas.security_master.importer import parse_coverage_csv, parse_holdings_csv
from quant_raas.security_master.service import SecurityMasterService
from quant_raas.services.daily_research import DailyResearchRequest, DailyResearchService
from quant_raas.storage.models import ResearchCardRecord

router = APIRouter()

SessionDependency = Annotated[Session, Depends(database_session)]
CsvUpload = Annotated[UploadFile, File()]
RequiredFormText = Annotated[str, Form()]
RequiredFormDateTime = Annotated[datetime, Form()]
OptionalFormText = Annotated[str | None, Form()]
OptionalQueryDateTime = Annotated[datetime | None, Query()]


def _master(session: Session) -> SecurityMasterService:
    settings = get_settings()
    repos = repositories_for(session)
    return SecurityMasterService(
        repos.securities,
        repos.portfolios,
        default_benchmark_identifier=settings.default_benchmark_identifier,
        sector_benchmark_identifiers=settings.sector_benchmark_identifiers,
    )


@router.get("/v1/securities")
def list_securities(session: SessionDependency) -> object:
    values = repositories_for(session).securities.list_securities(active_only=False)
    return jsonable_encoder(values)


@router.post("/v1/securities", status_code=status.HTTP_201_CREATED)
def register_security(
    payload: SecurityRegistration,
    session: SessionDependency,
) -> object:
    values = payload.model_dump(exclude={"identifiers"}, exclude_none=True)
    security = Security(**values)
    identifiers = tuple(
        SecurityIdentifier(security_id=security.security_id, **item.model_dump())
        for item in payload.identifiers
    )
    saved = _master(session).register_security(security, identifiers)
    return jsonable_encoder(saved)


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "uploaded CSV is empty")
    if len(content) > 2_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV exceeds 2 MB")
    return content


@router.post("/v1/coverage/validate")
async def validate_coverage(file: CsvUpload) -> object:
    parsed = parse_coverage_csv(await _read_upload(file))
    return {
        "valid": parsed.is_valid,
        "rows": jsonable_encoder(parsed.rows),
        "issues": [asdict(issue) for issue in parsed.issues],
        "source_hash": parsed.source_hash,
    }


@router.post("/v1/holdings/validate")
async def validate_holdings(file: CsvUpload) -> object:
    parsed = parse_holdings_csv(await _read_upload(file))
    return {
        "valid": parsed.is_valid,
        "rows": jsonable_encoder(parsed.rows),
        "issues": [asdict(issue) for issue in parsed.issues],
        "source_hash": parsed.source_hash,
    }


@router.post("/v1/coverage/import", status_code=status.HTTP_201_CREATED)
async def import_coverage(
    file: CsvUpload,
    name: RequiredFormText,
    as_of: RequiredFormDateTime,
    session: SessionDependency,
    description: OptionalFormText = None,
) -> object:
    parsed = parse_coverage_csv(await _read_upload(file))
    if not parsed.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            [asdict(issue) for issue in parsed.issues],
        )
    result = _master(session).import_coverage(
        parsed.rows,
        name=name,
        as_of=ensure_utc(as_of),
        description=description,
    )
    if not result.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            [asdict(issue) for issue in result.issues],
        )
    return jsonable_encoder(result)


@router.post("/v1/holdings/import", status_code=status.HTTP_201_CREATED)
async def import_holdings(
    file: CsvUpload,
    portfolio_name: RequiredFormText,
    as_of: RequiredFormDateTime,
    session: SessionDependency,
) -> object:
    parsed = parse_holdings_csv(await _read_upload(file))
    if not parsed.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            [asdict(issue) for issue in parsed.issues],
        )
    result = _master(session).import_holdings(
        parsed.rows,
        portfolio_name=portfolio_name,
        as_of=ensure_utc(as_of),
        source_name=file.filename,
        source_hash=parsed.source_hash,
    )
    if not result.is_valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            [asdict(issue) for issue in result.issues],
        )
    return jsonable_encoder(result)


@router.post("/v1/research/runs", status_code=status.HTTP_201_CREATED)
def run_daily_research(
    payload: DailyRunRequest,
    session: SessionDependency,
) -> object:
    settings = get_settings()
    repos = repositories_for(session)
    service = DailyResearchService(
        securities=repos.securities,
        portfolios=repos.portfolios,
        market_data=repos.market_data,
        features=repos.features,
        research=repos.research,
        materiality=materiality_scorer(settings),
    )
    result = service.run(
        DailyResearchRequest(
            coverage_list_id=payload.coverage_list_id,
            as_of=payload.as_of,
            data_cutoff_at=payload.data_cutoff_at,
            lookback_calendar_days=payload.lookback_calendar_days,
            source=payload.source,
        ),
        position_weights=payload.position_weights,
    )
    return jsonable_encoder(result)


@router.get("/v1/research/cards")
def list_cards(
    session: SessionDependency,
    knowledge_time: OptionalQueryDateTime = None,
    security_id: UUID | None = None,
) -> object:
    cards = repositories_for(session).research.cards_as_of(
        knowledge_time=ensure_utc(knowledge_time or utc_now()),
        security_id=security_id,
    )
    return jsonable_encoder(cards)


@router.post("/v1/research/cards/{card_id}/feedback", status_code=status.HTTP_201_CREATED)
def add_card_feedback(
    card_id: UUID,
    payload: FeedbackRequest,
    session: SessionDependency,
) -> object:
    if session.get(ResearchCardRecord, card_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "research card not found")
    feedback = MaterialityFeedback(
        card_id=card_id,
        feedback=payload.feedback,
        user_id=payload.user_id,
        comment=payload.comment,
    )
    saved = repositories_for(session).research.add_feedback(feedback)
    return jsonable_encoder(saved)
