"""Integration coverage for point-in-time feature-panel retrieval."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.domain.enums import DataQualityFlag
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


class _CodedIntegrityCause(Exception):
    def __init__(self, *, sqlite_errorcode: int | None = None, sqlstate: str | None = None) -> None:
        super().__init__("constraint failure")
        self.sqlite_errorcode = sqlite_errorcode
        self.sqlstate = sqlstate


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
    value: Any,
    code_version: str = "code-v1",
    metadata: dict[str, Any] | None = None,
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
        metadata=metadata or {},
    )


def _assert_record_matches_snapshot(
    record: FeatureSnapshotRecord,
    snapshot: FeatureSnapshot,
) -> None:
    assert record.feature_snapshot_id == snapshot.feature_snapshot_id
    assert record.security_id == snapshot.security_id
    assert record.feature_name == snapshot.feature_name
    assert record.feature_version == snapshot.feature_version
    assert record.effective_at == snapshot.effective_at
    assert record.available_at == snapshot.available_at
    assert record.calculated_at == snapshot.calculated_at
    assert record.value == snapshot.value
    assert record.unit == snapshot.unit
    assert record.window == snapshot.window
    assert record.quality_flags == [flag.value for flag in snapshot.quality_flags]
    assert record.input_evidence_ids == [str(value) for value in snapshot.input_evidence_ids]
    assert record.research_run_id == snapshot.research_run_id
    assert record.code_version == snapshot.code_version
    assert record.config_version == snapshot.config_version
    assert record.metadata_json == snapshot.metadata


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


def test_exact_identical_feature_retry_is_idempotent(
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        551,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    repository = SqlAlchemyFeatureRepository(sqlite_session)

    assert repository.upsert_many([snapshot]) == 1
    assert repository.upsert_many([snapshot]) == 0
    sqlite_session.expire_all()
    stored = sqlite_session.get(FeatureSnapshotRecord, snapshot.feature_snapshot_id)
    assert stored is not None
    _assert_record_matches_snapshot(stored, snapshot)


@pytest.mark.parametrize(
    ("field", "original", "divergent"),
    [
        pytest.param("value", True, 1, id="value-bool-int"),
        pytest.param("value", 1, 1.0, id="value-int-float"),
        pytest.param(
            "metadata",
            {"nested": {"value": True}},
            {"nested": {"value": 1}},
            id="metadata-bool-int",
        ),
        pytest.param(
            "metadata",
            {"nested": {"value": 1}},
            {"nested": {"value": 1.0}},
            id="metadata-int-float",
        ),
    ],
)
def test_exact_identity_retry_uses_json_type_exact_payload_equality(
    field: str,
    original: Any,
    divergent: Any,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        556,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=original if field == "value" else 7.0,
        metadata=original if field == "metadata" else None,
    )
    retry = snapshot.model_copy(update={field: divergent})
    repository = SqlAlchemyFeatureRepository(sqlite_session)

    assert repository.upsert_many([snapshot]) == 1
    with pytest.raises(RepositoryConflictError, match="different persisted payload"):
        repository.upsert_many([retry])

    assert sqlite_session.is_active
    assert sqlite_session.scalar(select(func.count()).select_from(FeatureSnapshotRecord)) == 1
    sqlite_session.expire_all()
    stored = sqlite_session.get(FeatureSnapshotRecord, snapshot.feature_snapshot_id)
    assert stored is not None
    stored_json_value = (
        stored.value if field == "value" else stored.metadata_json["nested"]["value"]
    )
    expected_json_value = original if field == "value" else original["nested"]["value"]
    assert type(stored_json_value) is type(expected_json_value)
    assert stored_json_value == expected_json_value


@pytest.mark.parametrize(
    "field",
    [
        "calculated_at",
        "value",
        "unit",
        "window",
        "quality_flags",
        "input_evidence_ids",
        "metadata",
    ],
)
def test_same_identity_and_natural_key_rejects_any_persisted_payload_divergence(
    field: str,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        561,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    divergent_values: dict[str, object] = {
        "calculated_at": snapshot.calculated_at + timedelta(minutes=1),
        "value": 2.0,
        "unit": "percent",
        "window": "20d",
        "quality_flags": (DataQualityFlag.STALE,),
        "input_evidence_ids": (UUID(int=999),),
        "metadata": {"changed": True},
    }
    divergent = snapshot.model_copy(update={field: divergent_values[field]})
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    assert repository.upsert_many([snapshot]) == 1

    with pytest.raises(RepositoryConflictError, match="different persisted payload"):
        repository.upsert_many([divergent])

    assert sqlite_session.is_active
    sqlite_session.expire_all()
    stored = sqlite_session.get(FeatureSnapshotRecord, snapshot.feature_snapshot_id)
    assert stored is not None
    _assert_record_matches_snapshot(stored, snapshot)


@pytest.mark.parametrize(
    "field",
    [
        "security_id",
        "feature_name",
        "feature_version",
        "effective_at",
        "available_at",
        "code_version",
        "config_version",
        "research_run_id",
    ],
)
def test_same_primary_id_on_a_different_natural_key_fails_closed(
    field: str,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": UUID(int=572), "name": "Second Corp"}
    )
    second_run = research_run.model_copy(
        update={"research_run_id": UUID(int=573), "run_key": "daily:feature-primary-conflict"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    research = SqlAlchemyResearchRepository(sqlite_session)
    research.add_run(research_run)
    research.add_run(second_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        571,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    divergent_values: dict[str, object] = {
        "security_id": second_security.security_id,
        "feature_name": "other_signal",
        "feature_version": "v2",
        "effective_at": snapshot.effective_at - timedelta(minutes=1),
        "available_at": snapshot.available_at - timedelta(minutes=1),
        "code_version": "code-v2",
        "config_version": "panel-v2",
        "research_run_id": second_run.research_run_id,
    }
    divergent = snapshot.model_copy(update={field: divergent_values[field]})
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    assert repository.upsert_many([snapshot]) == 1

    with pytest.raises(RepositoryConflictError, match="different persisted payload"):
        repository.upsert_many([divergent])

    assert sqlite_session.is_active
    sqlite_session.expire_all()
    stored = sqlite_session.get(FeatureSnapshotRecord, snapshot.feature_snapshot_id)
    assert stored is not None
    _assert_record_matches_snapshot(stored, snapshot)


@pytest.mark.parametrize(
    "cause",
    [
        pytest.param(
            _CodedIntegrityCause(sqlite_errorcode=sqlite3.SQLITE_CONSTRAINT_UNIQUE),
            id="sqlite-unique",
        ),
        pytest.param(_CodedIntegrityCause(sqlstate="23505"), id="postgres-unique"),
    ],
)
def test_simulated_unique_race_is_translated_inside_savepoint(
    cause: Exception,
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        581,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    simulated_race = IntegrityError("INSERT", {}, cause)
    original_flush: Callable[..., None] = sqlite_session.flush

    def fail_pending_unique_flush(*args: object, **kwargs: object) -> None:
        if sqlite_session.new:
            raise simulated_race
        original_flush(*args, **kwargs)

    monkeypatch.setattr(sqlite_session, "flush", fail_pending_unique_flush)

    with pytest.raises(RepositoryConflictError) as raised:
        SqlAlchemyFeatureRepository(sqlite_session).upsert_many([snapshot])

    assert raised.value.__cause__ is simulated_race
    assert sqlite_session.is_active
    assert sqlite_session.scalar(select(func.count()).select_from(FeatureSnapshotRecord)) == 0


def test_real_unique_race_is_translated_and_rolls_back_only_savepoint(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        591,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    original_flush: Callable[..., None] = sqlite_session.flush
    injected = False

    def inject_competing_row(*args: object, **kwargs: object) -> None:
        nonlocal injected
        if sqlite_session.new and not injected:
            injected = True
            sqlite_session.connection().execute(
                FeatureSnapshotRecord.__table__.insert(),
                {
                    "feature_snapshot_id": UUID(int=592),
                    "security_id": snapshot.security_id,
                    "feature_name": snapshot.feature_name,
                    "feature_version": snapshot.feature_version,
                    "effective_at": snapshot.effective_at,
                    "available_at": snapshot.available_at,
                    "calculated_at": snapshot.calculated_at,
                    "value": snapshot.value,
                    "unit": snapshot.unit,
                    "window": snapshot.window,
                    "quality_flags": [],
                    "input_evidence_ids": [],
                    "research_run_id": snapshot.research_run_id,
                    "code_version": snapshot.code_version,
                    "config_version": snapshot.config_version,
                    "metadata": {},
                },
            )
        original_flush(*args, **kwargs)

    monkeypatch.setattr(sqlite_session, "flush", inject_competing_row)

    with pytest.raises(RepositoryConflictError) as raised:
        SqlAlchemyFeatureRepository(sqlite_session).upsert_many([snapshot])

    assert isinstance(raised.value.__cause__, IntegrityError)
    assert sqlite_session.is_active
    assert sqlite_session.scalar(select(func.count()).select_from(FeatureSnapshotRecord)) == 0


def test_non_unique_flush_failure_is_re_raised_without_poisoning_outer_session(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    SqlAlchemyResearchRepository(sqlite_session).add_run(research_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    snapshot = _snapshot(
        596,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=effective + timedelta(minutes=5),
        value=1.0,
    )
    cause = _CodedIntegrityCause(sqlite_errorcode=sqlite3.SQLITE_CONSTRAINT_NOTNULL)
    simulated_failure = IntegrityError("INSERT", {}, cause)
    original_flush: Callable[..., None] = sqlite_session.flush

    def fail_pending_non_unique_flush(*args: object, **kwargs: object) -> None:
        if sqlite_session.new:
            raise simulated_failure
        original_flush(*args, **kwargs)

    monkeypatch.setattr(sqlite_session, "flush", fail_pending_non_unique_flush)

    with pytest.raises(IntegrityError) as raised:
        SqlAlchemyFeatureRepository(sqlite_session).upsert_many([snapshot])

    assert raised.value is simulated_failure
    assert sqlite_session.is_active
    assert sqlite_session.scalar(select(func.count()).select_from(FeatureSnapshotRecord)) == 0


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


@pytest.mark.parametrize("method", ["latest_as_of", "panel_as_of"])
@pytest.mark.parametrize(
    ("field", "left", "right"),
    [
        pytest.param("value", True, 1, id="value-bool-int"),
        pytest.param("value", 1, 1.0, id="value-int-float"),
        pytest.param(
            "metadata",
            {"nested": {"value": True}},
            {"nested": {"value": 1}},
            id="metadata-bool-int",
        ),
        pytest.param(
            "metadata",
            {"nested": {"value": 1}},
            {"nested": {"value": 1.0}},
            id="metadata-int-float",
        ),
    ],
)
def test_equal_precedence_vintages_use_json_type_exact_semantic_equality(
    method: str,
    field: str,
    left: Any,
    right: Any,
    sqlite_session: Session,
    sample_security: Security,
    research_run: ResearchRun,
) -> None:
    second_run = research_run.model_copy(
        update={"research_run_id": UUID(int=612), "run_key": "daily:json-type-divergent"}
    )
    SqlAlchemySecurityRepository(sqlite_session).add_security(sample_security)
    research = SqlAlchemyResearchRepository(sqlite_session)
    research.add_run(research_run)
    research.add_run(second_run)
    effective = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    available = effective + timedelta(minutes=5)
    calculated = available + timedelta(minutes=1)
    repository = SqlAlchemyFeatureRepository(sqlite_session)
    first = _snapshot(
        611,
        security_id=sample_security.security_id,
        research_run_id=research_run.research_run_id,
        effective_at=effective,
        available_at=available,
        calculated_at=calculated,
        value=left if field == "value" else 7.0,
        metadata=left if field == "metadata" else None,
    )
    second = _snapshot(
        612,
        security_id=sample_security.security_id,
        research_run_id=second_run.research_run_id,
        effective_at=effective,
        available_at=available,
        calculated_at=calculated,
        value=right if field == "value" else 7.0,
        metadata=right if field == "metadata" else None,
    )

    assert repository.upsert_many([first, second]) == 2
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
