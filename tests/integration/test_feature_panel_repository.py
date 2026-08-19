"""Integration coverage for point-in-time feature-panel retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import ResearchRun
from quant_raas.domain.security import Security
from quant_raas.storage.repositories import (
    SqlAlchemyFeatureRepository,
    SqlAlchemyResearchRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.point_in_time]


def _snapshot(
    identifier: int,
    *,
    security_id: UUID,
    research_run_id: UUID,
    feature_name: str = "signal",
    feature_version: str = "v1",
    config_version: str = "panel-v1",
    effective_at: datetime,
    available_at: datetime,
    calculated_at: datetime | None = None,
    value: float,
    code_version: str = "code-v1",
) -> FeatureSnapshot:
    return FeatureSnapshot(
        feature_snapshot_id=UUID(int=identifier),
        security_id=security_id,
        feature_name=feature_name,
        feature_version=feature_version,
        effective_at=effective_at,
        available_at=available_at,
        calculated_at=calculated_at or available_at + timedelta(minutes=1),
        value=value,
        research_run_id=research_run_id,
        code_version=code_version,
        config_version=config_version,
    )


def test_panel_as_of_returns_latest_requested_vintage_for_each_security(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": UUID(int=2), "name": "Second Corp"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)

    effective_old = datetime(2024, 1, 8, 21, 0, tzinfo=UTC)
    effective_new = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available_old = effective_old + timedelta(minutes=5)
    available_new = effective_new + timedelta(minutes=5)
    cutoff = datetime(2024, 1, 9, 22, 0, tzinfo=UTC)
    future = datetime(2024, 1, 10, 9, 0, tzinfo=UTC)

    repository = SqlAlchemyFeatureRepository(sqlite_session)
    repository.upsert_many(
        [
            _snapshot(
                101,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective_old,
                available_at=available_old,
                value=1.0,
            ),
            _snapshot(
                102,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective_new,
                available_at=available_new,
                value=2.0,
            ),
            _snapshot(
                103,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective_new,
                available_at=future,
                value=99.0,
            ),
            _snapshot(
                104,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                feature_version="v2",
                effective_at=effective_new,
                available_at=available_new,
                value=200.0,
            ),
            _snapshot(
                105,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                config_version="panel-v2",
                effective_at=effective_new,
                available_at=available_new,
                value=300.0,
            ),
            _snapshot(
                106,
                security_id=second_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective_new,
                available_at=available_new,
                value=-1.0,
            ),
        ]
    )

    panel = repository.panel_as_of(
        [second_security.security_id, sample_security.security_id],
        {"signal": "v1"},
        config_version="panel-v1",
        as_of=cutoff,
    )

    assert [(item.security_id, item.feature_name, item.value) for item in panel] == [
        (second_security.security_id, "signal", -1.0),
        (sample_security.security_id, "signal", 2.0),
    ]


def test_panel_as_of_validates_cutoff_and_version_pins(
    sqlite_session: Session,
) -> None:
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    with pytest.raises(ValueError, match="explicit timezone"):
        repository.panel_as_of(
            [],
            {},
            config_version="panel-v1",
            as_of=datetime(2024, 1, 9),
        )
    with pytest.raises(ValueError, match="config_version cannot be empty"):
        repository.panel_as_of(
            [],
            {},
            config_version=" ",
            as_of=datetime(2024, 1, 9, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="feature names and versions cannot be empty"):
        repository.panel_as_of(
            [],
            {"signal": " "},
            config_version="panel-v1",
            as_of=datetime(2024, 1, 9, tzinfo=UTC),
        )
    assert (
        repository.panel_as_of(
            [],
            {"signal": "v1"},
            config_version="panel-v1",
            as_of=datetime(2024, 1, 9, tzinfo=UTC),
        )
        == ()
    )


def test_panel_as_of_rejects_ambiguous_top_vintage(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    calculated = available + timedelta(minutes=1)
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    repository.upsert_many(
        [
            _snapshot(
                201,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective,
                available_at=available,
                calculated_at=calculated,
                value=1.0,
                code_version="code-a",
            ),
            _snapshot(
                202,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=effective,
                available_at=available,
                calculated_at=calculated,
                value=2.0,
                code_version="code-b",
            ),
        ]
    )
    with pytest.raises(RepositoryConflictError, match="ambiguous latest feature vintage"):
        repository.panel_as_of(
            [sample_security.security_id],
            {"signal": "v1"},
            config_version="panel-v1",
            as_of=calculated,
        )
