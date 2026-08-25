"""Integration coverage for thesis lifecycle application semantics."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from quant_raas.common.errors import (
    RepositoryConflictError,
    ThesisConflictError,
    ThesisNotFoundError,
    ThesisReferenceError,
)
from quant_raas.config import Settings
from quant_raas.domain.enums import ThesisSelectionStatus, ThesisStatus
from quant_raas.domain.research import ThesisContent
from quant_raas.domain.security import Security
from quant_raas.research.thesis import ThesisRelevanceEvaluator
from quant_raas.runtime import repositories_for, thesis_relevance_evaluator
from quant_raas.services.theses import ThesisService
from quant_raas.storage.repositories import (
    SqlAlchemySecurityRepository,
    SqlAlchemyThesisRepository,
)

OTHER_SECURITY_ID = UUID("22222222-2222-4222-8222-222222222222")


class _SequenceClock:
    def __init__(self, *instants: datetime) -> None:
        self._instants = instants
        self.calls = 0

    def __call__(self) -> datetime:
        instant = self._instants[self.calls]
        self.calls += 1
        return instant


def _service(
    session: Session,
    security: Security,
    clock: Callable[[], datetime],
) -> ThesisService:
    securities = SqlAlchemySecurityRepository(session)
    securities.add_security(security)
    return ThesisService(
        securities,
        SqlAlchemyThesisRepository(session),
        clock=clock,
    )


def _create(
    service: ThesisService,
    security: Security,
    content: ThesisContent,
    *,
    thesis_key: str = "example_core",
    valid_from: datetime | None = None,
):
    return service.create(
        thesis_key=thesis_key,
        security_id=security.security_id,
        title="Example core thesis",
        content=content,
        created_by="analyst@example.com",
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        valid_from=valid_from,
    )


def _stored_nodes_json(session: Session, thesis_version_id: UUID) -> str:
    value = (
        session.connection()
        .exec_driver_sql(
            "SELECT nodes FROM thesis_version WHERE thesis_version_id = ?",
            (thesis_version_id.hex,),
        )
        .scalar_one()
    )
    assert isinstance(value, str)
    return value


def test_create_builds_identity_and_v1_with_one_utc_normalized_clock_read(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    offset_now = fixed_now.astimezone(timezone(timedelta(hours=2)))
    clock = _SequenceClock(offset_now)
    service = _service(sqlite_session, sample_security, clock)

    created = _create(
        service,
        sample_security,
        thesis_content,
        valid_from=fixed_now - timedelta(days=1),
    )

    assert clock.calls == 1
    assert created.thesis.thesis_key == "example_core"
    assert created.thesis.security_id == sample_security.security_id
    assert created.thesis.created_at == fixed_now
    assert created.thesis.status is ThesisStatus.ACTIVE
    assert created.version.thesis_id == created.thesis.thesis_id
    assert created.version.version == 1
    assert created.version.content == thesis_content
    assert created.version.created_at == created.version.approved_at == fixed_now
    assert created.version.valid_from == fixed_now - timedelta(days=1)
    assert isinstance(created.thesis.thesis_id, UUID)
    assert isinstance(created.version.thesis_version_id, UUID)


def test_mutation_signatures_do_not_accept_caller_owned_audit_timestamps() -> None:
    for method in (
        ThesisService.create,
        ThesisService.append_version,
        ThesisService.archive,
    ):
        parameters = inspect.signature(method).parameters
        assert "created_at" not in parameters
        assert "approved_at" not in parameters


def test_creation_identity_and_v1_remain_in_one_caller_owned_transaction(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)
    created = _create(service, sample_security, thesis_content)

    sqlite_session.rollback()

    theses = SqlAlchemyThesisRepository(sqlite_session)
    assert theses.get_by_id(created.thesis.thesis_id) is None
    assert theses.list_versions(created.thesis.thesis_id) == ()


def test_duplicate_key_is_a_typed_conflict_with_repository_cause(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)
    _create(service, sample_security, thesis_content)

    with pytest.raises(ThesisConflictError) as raised:
        _create(service, sample_security, thesis_content)

    assert isinstance(raised.value.__cause__, RepositoryConflictError)


def test_create_rejects_a_missing_security_reference_before_persistence(
    sqlite_session: Session,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    theses = SqlAlchemyThesisRepository(sqlite_session)
    service = ThesisService(
        SqlAlchemySecurityRepository(sqlite_session),
        theses,
        clock=lambda: fixed_now,
    )

    with pytest.raises(ThesisReferenceError, match="security"):
        service.create(
            thesis_key="example_core",
            security_id=OTHER_SECURITY_ID,
            title="Example core thesis",
            content=thesis_content,
            created_by="analyst@example.com",
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
        )

    assert theses.get_by_key("example_core") is None


def test_append_allocates_exact_next_version_and_preserves_old_json_bytes(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    clock = _SequenceClock(fixed_now, fixed_now + timedelta(hours=1))
    service = _service(sqlite_session, sample_security, clock)
    created = _create(
        service,
        sample_security,
        thesis_content,
        valid_from=fixed_now - timedelta(days=1),
    )
    original_json = _stored_nodes_json(sqlite_session, created.version.thesis_version_id)
    updated_content = thesis_content.model_copy(update={"summary": "Updated summary."})

    updated = service.append_version(
        "example_core",
        content=updated_content,
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        expected_version=1,
        valid_from=fixed_now + timedelta(days=1),
    )

    assert clock.calls == 2
    assert updated.version == 2
    assert updated.thesis_id == created.thesis.thesis_id
    assert updated.content == updated_content
    assert updated.created_at == updated.approved_at == fixed_now + timedelta(hours=1)
    assert _stored_nodes_json(sqlite_session, created.version.thesis_version_id) == original_json
    assert service.history("example_core") == (created.version, updated)


def test_stale_expected_version_is_a_typed_conflict_with_repository_cause(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)
    _create(
        service,
        sample_security,
        thesis_content,
        valid_from=fixed_now - timedelta(days=2),
    )
    service.append_version(
        "example_core",
        content=thesis_content.model_copy(update={"summary": "Version two."}),
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        expected_version=1,
        valid_from=fixed_now - timedelta(days=1),
    )

    with pytest.raises(ThesisConflictError) as raised:
        service.append_version(
            "example_core",
            content=thesis_content.model_copy(update={"summary": "Stale edit."}),
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            expected_version=1,
            valid_from=fixed_now,
        )

    assert isinstance(raised.value.__cause__, RepositoryConflictError)


def test_append_rejects_non_monotonic_activation_without_changing_history(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)
    created = _create(service, sample_security, thesis_content, valid_from=fixed_now)

    with pytest.raises(ThesisConflictError, match="valid_from"):
        service.append_version(
            "example_core",
            content=thesis_content.model_copy(update={"summary": "Earlier activation."}),
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            expected_version=1,
            valid_from=fixed_now - timedelta(seconds=1),
        )

    assert service.history("example_core") == (created.version,)


def test_read_list_and_history_use_the_repository_point_in_time_contract(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)
    created = _create(
        service,
        sample_security,
        thesis_content,
        valid_from=fixed_now + timedelta(days=1),
    )

    detail = service.detail(
        "example_core",
        effective_at=fixed_now,
        knowledge_time=fixed_now,
    )

    assert detail.thesis == created.thesis
    assert detail.selection.status is ThesisSelectionStatus.NOT_YET_EFFECTIVE
    assert detail.selection.version is None
    assert service.list_for_security(sample_security.security_id) == (created.thesis,)
    assert service.history("example_core") == (created.version,)


def test_unknown_key_is_not_found_for_lifecycle_lookups(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    service = _service(sqlite_session, sample_security, lambda: fixed_now)

    lookups = (
        lambda: service.detail(
            "missing_core",
            effective_at=fixed_now,
            knowledge_time=fixed_now,
        ),
        lambda: service.history("missing_core"),
        lambda: service.append_version(
            "missing_core",
            content=thesis_content,
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            expected_version=1,
        ),
        lambda: service.archive("missing_core", archived_by="pm@example.com"),
    )
    for lookup in lookups:
        with pytest.raises(ThesisNotFoundError, match="missing_core"):
            lookup()


def test_reference_validation_distinguishes_unknown_wrong_security_and_archived(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    second_security = sample_security.model_copy(
        update={"security_id": OTHER_SECURITY_ID, "name": "Other Corp"}
    )
    securities = SqlAlchemySecurityRepository(sqlite_session)
    securities.add_security(sample_security)
    securities.add_security(second_security)
    service = ThesisService(
        securities,
        SqlAlchemyThesisRepository(sqlite_session),
        clock=lambda: fixed_now,
    )
    created = _create(service, sample_security, thesis_content)

    assert service.require_reference("example_core", sample_security.security_id) == created.thesis
    with pytest.raises(ThesisReferenceError, match="missing_core"):
        service.require_reference("missing_core", sample_security.security_id)
    with pytest.raises(ThesisReferenceError, match="security"):
        service.require_reference("example_core", second_security.security_id)

    archived = service.archive("example_core", archived_by="pm@example.com")

    with pytest.raises(ThesisReferenceError, match="archived"):
        service.require_reference("example_core", sample_security.security_id)
    assert service.list_for_security(sample_security.security_id) == ()
    assert service.list_for_security(
        sample_security.security_id,
        include_archived=True,
    ) == (archived,)


def test_archive_is_idempotent_and_append_after_archive_preserves_conflict_cause(
    sqlite_session: Session,
    sample_security: Security,
    thesis_content: ThesisContent,
    fixed_now: datetime,
) -> None:
    archived_at = fixed_now + timedelta(hours=1)
    clock = _SequenceClock(fixed_now, archived_at, archived_at + timedelta(hours=1), fixed_now)
    service = _service(sqlite_session, sample_security, clock)
    _create(service, sample_security, thesis_content, valid_from=fixed_now)

    first = service.archive("example_core", archived_by="first@example.com")
    repeated = service.archive("example_core", archived_by="second@example.com")

    assert first == repeated
    assert repeated.archived_at == archived_at
    assert repeated.archived_by == "first@example.com"
    with pytest.raises(ThesisConflictError) as raised:
        service.append_version(
            "example_core",
            content=thesis_content.model_copy(update={"summary": "Too late."}),
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            expected_version=1,
            valid_from=fixed_now,
        )
    assert isinstance(raised.value.__cause__, RepositoryConflictError)
    assert clock.calls == 4


def test_runtime_composes_session_bound_theses_and_config_backed_evaluators(
    sqlite_session: Session,
) -> None:
    repositories = repositories_for(sqlite_session)
    settings = Settings(config_directory=Path(__file__).resolve().parents[2] / "configs")

    first = thesis_relevance_evaluator(settings)
    second = thesis_relevance_evaluator(settings)

    assert isinstance(repositories.theses, SqlAlchemyThesisRepository)
    assert repositories.theses.session is sqlite_session
    assert isinstance(first, ThesisRelevanceEvaluator)
    assert first is not second
    assert first.config == second.config
    assert first.config.method_version == "thesis-relevance-v1"
