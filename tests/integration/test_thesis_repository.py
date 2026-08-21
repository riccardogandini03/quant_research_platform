"""Integration coverage for immutable, versioned thesis persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_raas.common.errors import RepositoryConflictError
from quant_raas.config import Settings
from quant_raas.domain.enums import ThesisSelectionStatus, ThesisStatus
from quant_raas.domain.research import Thesis, ThesisContent, ThesisVersion
from quant_raas.domain.security import Security
from quant_raas.storage.models import ThesisVersionRecord
from quant_raas.storage.repositories import (
    SqlAlchemySecurityRepository,
    SqlAlchemyThesisRepository,
)
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine

SECOND_THESIS_ID = UUID("73737373-7373-4737-8737-737373737373")
SECOND_VERSION_ID = UUID("74747474-7474-4747-8747-747474747474")
ARCHIVED_AT = datetime(2024, 1, 12, tzinfo=UTC)


def _persist_security(session: Session, security: Security) -> None:
    SqlAlchemySecurityRepository(session).add_security(security)


def _second_version(
    thesis: Thesis,
    content: ThesisContent,
    *,
    version: int = 2,
    valid_from: datetime = datetime(2024, 1, 6, tzinfo=UTC),
    approved_at: datetime = datetime(2024, 1, 6, tzinfo=UTC),
) -> ThesisVersion:
    return ThesisVersion(
        thesis_version_id=SECOND_VERSION_ID,
        thesis_id=thesis.thesis_id,
        version=version,
        valid_from=valid_from,
        content=content,
        authored_by="analyst@example.com",
        approved_by="pm@example.com",
        created_at=approved_at,
        approved_at=approved_at,
    )


def test_repository_round_trips_identity_content_and_point_in_time_selection(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)

    assert repository.add_thesis(thesis) == thesis
    assert repository.add_version(thesis_version, expected_version=0) == thesis_version

    by_id = repository.get_by_id(thesis.thesis_id)
    by_key = repository.get_by_key("example_core")
    assert by_id == by_key == thesis
    assert repository.list_for_security(sample_security.security_id) == (thesis,)
    assert repository.list_versions(thesis.thesis_id) == (thesis_version,)
    stored = sqlite_session.get(ThesisVersionRecord, thesis_version.thesis_version_id)
    assert stored is not None
    assert stored.nodes == thesis_version.content.model_dump(mode="json")

    selection = repository.version_as_of(
        thesis,
        effective_at=thesis_version.valid_from,
        knowledge_time=thesis_version.approved_at,
    )
    assert selection.version == thesis_version


def test_duplicate_public_key_raises_the_exact_repository_conflict(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    duplicate = thesis.model_copy(update={"thesis_id": SECOND_THESIS_ID})

    with pytest.raises(
        RepositoryConflictError,
        match=r"thesis key 'example_core' already exists",
    ):
        repository.add_thesis(duplicate)


def test_identity_listing_is_stable_and_excludes_archived_by_default(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    later_key = thesis.model_copy(update={"thesis_id": SECOND_THESIS_ID, "thesis_key": "zeta_case"})
    repository.add_thesis(later_key)
    repository.add_thesis(thesis)
    archived = repository.archive(
        thesis.thesis_id,
        archived_at=ARCHIVED_AT,
        archived_by="archive@example.com",
    )

    assert repository.list_for_security(sample_security.security_id) == (later_key,)
    assert repository.list_for_security(
        sample_security.security_id,
        include_archived=True,
    ) == (archived, later_key)


def test_append_requires_current_expected_version_and_exact_next_number(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    thesis_content: ThesisContent,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)

    with pytest.raises(RepositoryConflictError, match=r"expected version 0.*latest version is 1"):
        repository.add_version(_second_version(thesis, thesis_content), expected_version=0)
    with pytest.raises(RepositoryConflictError, match="next thesis version must be 2"):
        repository.add_version(
            _second_version(thesis, thesis_content, version=3),
            expected_version=1,
        )


def test_append_requires_monotonic_activation_time(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    thesis_content: ThesisContent,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)
    earlier = _second_version(
        thesis,
        thesis_content,
        valid_from=thesis_version.valid_from - timedelta(seconds=1),
    )

    with pytest.raises(RepositoryConflictError, match="valid_from cannot precede"):
        repository.add_version(earlier, expected_version=1)


def test_version_history_is_stably_ordered_by_version_then_approval(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    thesis_content: ThesisContent,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)
    second = _second_version(
        thesis,
        thesis_content,
        approved_at=thesis_version.approved_at - timedelta(days=1),
    )
    repository.add_version(second, expected_version=1)

    assert repository.list_versions(thesis.thesis_id) == (thesis_version, second)


def test_archive_is_idempotent_and_point_in_time_aware(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)

    first = repository.archive(
        thesis.thesis_id,
        archived_at=ARCHIVED_AT,
        archived_by="first@example.com",
    )
    repeated = repository.archive(
        thesis.thesis_id,
        archived_at=ARCHIVED_AT + timedelta(days=1),
        archived_by="second@example.com",
    )

    assert repeated == first
    assert repeated.status is ThesisStatus.ARCHIVED
    assert repeated.archived_at == ARCHIVED_AT
    assert repeated.archived_by == "first@example.com"
    before = repository.version_as_of(
        repeated,
        effective_at=thesis_version.valid_from,
        knowledge_time=ARCHIVED_AT - timedelta(microseconds=1),
    )
    at_archive = repository.version_as_of(
        repeated,
        effective_at=thesis_version.valid_from,
        knowledge_time=ARCHIVED_AT,
    )
    assert before.version == thesis_version
    assert at_archive.status is ThesisSelectionStatus.ARCHIVED_AT_CUTOFF
    assert at_archive.version is None


def test_archived_identity_rejects_new_versions(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    thesis_content: ThesisContent,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)
    repository.archive(
        thesis.thesis_id,
        archived_at=ARCHIVED_AT,
        archived_by="archive@example.com",
    )

    with pytest.raises(RepositoryConflictError, match="archived thesis"):
        repository.add_version(_second_version(thesis, thesis_content), expected_version=1)


def test_malformed_legacy_content_fails_closed_without_rewriting_json(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    malformed_nodes: dict[str, object] = {}
    sqlite_session.add(
        ThesisVersionRecord(
            thesis_version_id=thesis_version.thesis_version_id,
            thesis_id=thesis.thesis_id,
            version=1,
            valid_from=thesis_version.valid_from,
            valid_to=None,
            nodes=malformed_nodes,
            authored_by=thesis_version.authored_by,
            approved_by=thesis_version.approved_by,
            approved_at=thesis_version.approved_at,
            created_at=thesis_version.created_at,
        )
    )
    sqlite_session.commit()

    with pytest.raises(ValidationError):
        repository.list_versions(thesis.thesis_id)

    stored = sqlite_session.get(ThesisVersionRecord, thesis_version.thesis_version_id)
    assert stored is not None
    assert stored.nodes == malformed_nodes


def test_repository_mutations_leave_commit_and_rollback_to_the_caller(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    _persist_security(sqlite_session, sample_security)
    sqlite_session.commit()
    repository = SqlAlchemyThesisRepository(sqlite_session)

    repository.add_thesis(thesis)
    repository.add_version(thesis_version, expected_version=0)
    sqlite_session.rollback()

    assert repository.get_by_id(thesis.thesis_id) is None


def test_archive_leaves_rollback_to_the_caller(
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    repository.add_thesis(thesis)
    sqlite_session.commit()

    repository.archive(
        thesis.thesis_id,
        archived_at=ARCHIVED_AT,
        archived_by="archive@example.com",
    )
    sqlite_session.rollback()
    sqlite_session.expire_all()

    assert repository.get_by_id(thesis.thesis_id) == thesis


@pytest.mark.parametrize("operation", ["identity", "version"])
def test_unique_flush_races_are_translated_with_integrity_error_as_cause(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_session: Session,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    operation: str,
) -> None:
    _persist_security(sqlite_session, sample_security)
    repository = SqlAlchemyThesisRepository(sqlite_session)
    if operation == "version":
        repository.add_thesis(thesis)
    simulated_race = IntegrityError("INSERT", {}, Exception("unique constraint"))
    original_flush: Callable[..., None] = sqlite_session.flush

    def fail_pending_unique_flush(*args: object, **kwargs: object) -> None:
        if sqlite_session.new:
            raise simulated_race
        original_flush(*args, **kwargs)

    monkeypatch.setattr(sqlite_session, "flush", fail_pending_unique_flush)

    with pytest.raises(RepositoryConflictError) as raised:
        if operation == "identity":
            repository.add_thesis(thesis)
        else:
            repository.add_version(thesis_version, expected_version=0)

    assert raised.value.__cause__ is simulated_race


def test_locked_refresh_rejects_stale_append_after_concurrent_archive(
    tmp_path: Path,
    sample_security: Security,
    thesis: Thesis,
    thesis_version: ThesisVersion,
    thesis_content: ThesisContent,
) -> None:
    database_path = tmp_path / "thesis-concurrency.sqlite3"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        database_echo=False,
    )
    engine = create_sql_engine(settings)
    create_schema(engine)
    factory = create_session_factory(engine)
    session_a = factory()
    session_b = factory()
    try:
        _persist_security(session_a, sample_security)
        repository_a = SqlAlchemyThesisRepository(session_a)
        repository_a.add_thesis(thesis)
        repository_a.add_version(thesis_version, expected_version=0)
        session_a.commit()
        assert repository_a.get_by_id(thesis.thesis_id) == thesis

        repository_b = SqlAlchemyThesisRepository(session_b)
        archived = repository_b.archive(
            thesis.thesis_id,
            archived_at=ARCHIVED_AT,
            archived_by="first@example.com",
        )
        session_b.commit()
        repeated = repository_b.archive(
            thesis.thesis_id,
            archived_at=ARCHIVED_AT + timedelta(days=1),
            archived_by="second@example.com",
        )
        session_b.commit()
        assert repeated == archived

        with pytest.raises(RepositoryConflictError, match="archived thesis"):
            repository_a.add_version(
                _second_version(thesis, thesis_content),
                expected_version=1,
            )
    finally:
        session_a.close()
        session_b.close()
        engine.dispose()
