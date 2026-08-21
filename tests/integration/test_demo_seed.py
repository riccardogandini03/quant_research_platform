"""Integration coverage for deterministic explicit demo thesis seeding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from quant_raas.config import Settings
from quant_raas.demo import seed_demo
from quant_raas.domain.enums import ThesisStatus
from quant_raas.runtime import repositories_for
from quant_raas.security_master.importer import parse_coverage_csv, parse_holdings_csv
from quant_raas.storage.models import (
    CoverageMemberRecord,
    PortfolioSnapshotRecord,
    ThesisRecord,
    ThesisVersionRecord,
)
from quant_raas.storage.session import create_session_factory, create_sql_engine

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_seed_demo_creates_resolvable_version_one_theses_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "demo.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        config_directory=REPOSITORY_ROOT / "configs",
    )
    now = datetime(2024, 1, 17, 22, 0, tzinfo=UTC)
    demo_context_at = now - timedelta(days=7)
    retry_now = now + timedelta(seconds=1)
    retry_context_at = retry_now - timedelta(days=7)

    seed_demo(settings, now=now)
    seed_demo(settings, now=retry_now)

    engine = create_sql_engine(settings)
    factory = create_session_factory(engine)
    with factory() as session:
        identities = tuple(session.scalars(select(ThesisRecord).order_by(ThesisRecord.thesis_key)))
        versions = tuple(
            session.scalars(
                select(ThesisVersionRecord).order_by(
                    ThesisVersionRecord.thesis_id,
                    ThesisVersionRecord.version,
                )
            )
        )
        assert [identity.thesis_key for identity in identities] == [
            "aapl_services",
            "asml_core",
            "msft_cloud",
        ]
        assert {identity.status for identity in identities} == {ThesisStatus.ACTIVE.value}
        assert len(versions) == 3
        assert {version.version for version in versions} == {1}
        assert {version.valid_from for version in versions} == {demo_context_at}
        assert {version.created_at for version in versions} == {demo_context_at}
        assert {version.approved_at for version in versions} == {demo_context_at}

        coverage_rows = parse_coverage_csv(REPOSITORY_ROOT / "examples" / "coverage.csv").rows
        holdings_rows = parse_holdings_csv(REPOSITORY_ROOT / "examples" / "holdings.csv").rows
        repos = repositories_for(session)
        for cutoff in (demo_context_at, retry_context_at):
            for row in (*coverage_rows, *holdings_rows):
                if row.thesis_id is None:
                    continue
                security = repos.securities.resolve(row.security_reference(), as_of=cutoff)
                thesis = repos.theses.get_by_key(row.thesis_id)
                assert thesis is not None
                assert thesis.security_id == security.security_id

        coverage_cutoffs = set(session.scalars(select(CoverageMemberRecord.added_at)))
        portfolio_cutoffs = set(session.scalars(select(PortfolioSnapshotRecord.as_of)))
        assert coverage_cutoffs == {demo_context_at}
        assert portfolio_cutoffs == {demo_context_at, retry_context_at}
    engine.dispose()


def test_seed_demo_rejects_finite_interval_in_stored_demo_thesis(tmp_path: Path) -> None:
    database_path = tmp_path / "finite-version.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        config_directory=REPOSITORY_ROOT / "configs",
    )
    now = datetime(2024, 1, 17, 22, 0, tzinfo=UTC)
    demo_context_at = now - timedelta(days=7)
    seed_demo(settings, now=now)

    engine = create_sql_engine(settings)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        version = session.scalar(
            select(ThesisVersionRecord)
            .join(ThesisRecord)
            .where(ThesisRecord.thesis_key == "aapl_services")
        )
        assert version is not None
        version.valid_to = demo_context_at + timedelta(days=30)

    with pytest.raises(
        ValueError,
        match="existing demo thesis 'aapl_services' differs from fixture",
    ):
        seed_demo(settings, now=now + timedelta(seconds=1))

    with factory() as session:
        identities = tuple(session.scalars(select(ThesisRecord)))
        versions = tuple(session.scalars(select(ThesisVersionRecord)))
        assert len(identities) == 3
        assert len(versions) == 3
        changed = next(
            version
            for version in versions
            if version.thesis_id
            == next(
                identity.thesis_id
                for identity in identities
                if identity.thesis_key == "aapl_services"
            )
        )
        assert changed.valid_to == demo_context_at + timedelta(days=30)
    engine.dispose()


def test_seed_demo_rejects_rerun_before_persisted_seed_instant(tmp_path: Path) -> None:
    database_path = tmp_path / "earlier-rerun.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        config_directory=REPOSITORY_ROOT / "configs",
    )
    now = datetime(2024, 1, 17, 22, 0, tzinfo=UTC)
    demo_context_at = now - timedelta(days=7)
    seed_demo(settings, now=now)

    with pytest.raises(
        ValueError,
        match="existing demo thesis 'aapl_services' differs from fixture",
    ):
        seed_demo(settings, now=now - timedelta(seconds=1))

    engine = create_sql_engine(settings)
    factory = create_session_factory(engine)
    with factory() as session:
        identities = tuple(session.scalars(select(ThesisRecord)))
        versions = tuple(session.scalars(select(ThesisVersionRecord)))
        assert len(identities) == 3
        assert len(versions) == 3
        assert {identity.created_at for identity in identities} == {demo_context_at}
        assert {version.created_at for version in versions} == {demo_context_at}
        assert {version.valid_from for version in versions} == {demo_context_at}
        assert {version.approved_at for version in versions} == {demo_context_at}
    engine.dispose()
