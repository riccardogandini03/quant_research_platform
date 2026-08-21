"""Integration coverage for point-in-time feature-panel retrieval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.domain.research import ResearchRun
from quant_raas.domain.security import Security
from quant_raas.storage.models import FeatureSnapshotRecord
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
                calculated_at=available_new + timedelta(minutes=2),
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
            _snapshot(
                107,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                feature_name="quality",
                feature_version="v2",
                effective_at=effective_new,
                available_at=available_new,
                value=4.0,
            ),
            _snapshot(
                108,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                feature_name="quality",
                feature_version="v1",
                effective_at=effective_new,
                available_at=available_new,
                calculated_at=available_new + timedelta(minutes=2),
                value=400.0,
            ),
            _snapshot(
                109,
                security_id=sample_security.security_id,
                research_run_id=research_run.research_run_id,
                effective_at=future,
                available_at=available_new,
                calculated_at=future + timedelta(minutes=1),
                value=999.0,
            ),
        ]
    )

    materialized_ids: list[UUID] = []

    def record_load(row: FeatureSnapshotRecord, _context: object) -> None:
        materialized_ids.append(row.feature_snapshot_id)

    sqlite_session.expunge_all()
    event.listen(FeatureSnapshotRecord, "load", record_load)
    try:
        panel = repository.panel_as_of(
            [second_security.security_id, sample_security.security_id],
            {"signal": "v1", "quality": "v2"},
            config_version="panel-v1",
            as_of=cutoff,
        )
    finally:
        event.remove(FeatureSnapshotRecord, "load", record_load)

    assert materialized_ids == [UUID(int=106), UUID(int=107), UUID(int=102)]
    assert [
        (item.security_id, item.feature_name, item.feature_version, item.value) for item in panel
    ] == [
        (second_security.security_id, "signal", "v1", -1.0),
        (sample_security.security_id, "quality", "v2", 4.0),
        (sample_security.security_id, "signal", "v1", 2.0),
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


def test_feature_vintage_uniqueness_is_scoped_to_research_run() -> None:
    constraint = next(
        constraint
        for constraint in FeatureSnapshotRecord.__table__.constraints
        if constraint.name == "uq_feature_snapshot_vintage"
    )

    assert tuple(column.name for column in constraint.columns) == (
        "security_id",
        "feature_name",
        "feature_version",
        "effective_at",
        "available_at",
        "code_version",
        "config_version",
        "research_run_id",
    )


def test_distinct_runs_persist_identical_vintages_and_resolve_deterministically(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_run = research_run.model_copy(
        update={"research_run_id": UUID(int=902), "run_key": "daily:2024-01-09:second"}
    )
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    research = SqlAlchemyResearchRepository(sqlite_session)
    research.add_run(research_run)
    research.add_run(second_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    calculated = available + timedelta(minutes=1)
    first = _snapshot(
        402,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=available,
        calculated_at=calculated,
        value=1.0,
    )
    second = _snapshot(
        401,
        security_id=sample_security.security_id,
        research_run_id=second_run.research_run_id,
        effective_at=effective,
        available_at=available,
        calculated_at=calculated,
        value=1.0,
    )
    repository = SqlAlchemyFeatureRepository(sqlite_session)

    assert repository.upsert_many([first, second]) == 2
    stored = sqlite_session.scalars(
        select(FeatureSnapshotRecord).where(
            FeatureSnapshotRecord.feature_snapshot_id.in_(
                [first.feature_snapshot_id, second.feature_snapshot_id]
            )
        )
    ).all()
    assert {(row.feature_snapshot_id, row.research_run_id) for row in stored} == {
        (first.feature_snapshot_id, research_run.research_run_id),
        (second.feature_snapshot_id, second_run.research_run_id),
    }
    assert repository.latest_as_of(
        sample_security.security_id,
        ["signal"],
        effective_at=calculated,
        knowledge_time=calculated,
    ) == (second,)
    assert repository.panel_as_of(
        [sample_security.security_id],
        {"signal": "v1"},
        config_version="panel-v1",
        as_of=calculated,
    ) == (second,)


def test_same_run_idempotent_upsert_rejects_a_different_snapshot_id(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    first = _snapshot(
        501,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=available,
        value=1.0,
    )
    duplicate_key = first.model_copy(update={"feature_snapshot_id": UUID(int=502)})

    assert repository.upsert_many([first]) == 1
    with pytest.raises(RepositoryConflictError, match="different feature_snapshot_id"):
        repository.upsert_many([duplicate_key])


@pytest.mark.parametrize("method", ["latest_as_of", "panel_as_of"])
def test_equal_precedence_vintages_with_divergent_content_are_rejected(
    method: str,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_run = research_run.model_copy(
        update={"research_run_id": UUID(int=602), "run_key": "daily:2024-01-09:divergent"}
    )
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    research = SqlAlchemyResearchRepository(sqlite_session)
    research.add_run(research_run)
    research.add_run(second_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    calculated = available + timedelta(minutes=1)
    repository = SqlAlchemyFeatureRepository(sqlite_session)

    assert (
        repository.upsert_many(
            [
                _snapshot(
                    601,
                    security_id=sample_security.security_id,
                    research_run_id=research_run.research_run_id,
                    effective_at=effective,
                    available_at=available,
                    calculated_at=calculated,
                    value=1.0,
                ),
                _snapshot(
                    602,
                    security_id=sample_security.security_id,
                    research_run_id=second_run.research_run_id,
                    effective_at=effective,
                    available_at=available,
                    calculated_at=calculated,
                    value=2.0,
                ),
            ]
        )
        == 2
    )
    with pytest.raises(RepositoryConflictError, match="ambiguous latest feature vintage"):
        if method == "latest_as_of":
            repository.latest_as_of(
                sample_security.security_id,
                ["signal"],
                effective_at=calculated,
                knowledge_time=calculated,
            )
        else:
            repository.panel_as_of(
                [sample_security.security_id],
                {"signal": "v1"},
                config_version="panel-v1",
                as_of=calculated,
            )
