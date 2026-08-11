"""Integration coverage for temporal resolution and atomic contextual imports."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_raas.common.errors import DomainValidationError
from quant_raas.domain.enums import IdentifierScheme
from quant_raas.domain.portfolio import CoverageUploadRow, HoldingUploadRow
from quant_raas.domain.security import Security, SecurityIdentifier, SecurityReference
from quant_raas.security_master.service import SecurityMasterService
from quant_raas.services.portfolio_import import import_coverage_csv, import_holdings_csv
from quant_raas.storage.models import (
    CoverageMemberRecord,
    PortfolioPositionRecord,
    PortfolioSnapshotRecord,
)
from quant_raas.storage.repositories import (
    SqlAlchemyPortfolioRepository,
    SqlAlchemySecurityRepository,
)

pytestmark = pytest.mark.integration


def _security(security_id: UUID, name: str, created_at: datetime) -> Security:
    return Security(
        security_id=security_id,
        name=name,
        primary_currency="USD",
        exchange_mic="XNAS",
        exchange_timezone="America/New_York",
        country_code="US",
        created_at=created_at,
        updated_at=created_at,
    )


def _identifier(
    security_id: UUID,
    *,
    valid_from: datetime,
    valid_to: datetime | None,
) -> SecurityIdentifier:
    return SecurityIdentifier(
        security_id=security_id,
        scheme=IdentifierScheme.VENDOR,
        value="REUSED US",
        provider="demo",
        exchange_mic="XNAS",
        valid_from=valid_from,
        valid_to=valid_to,
        created_at=valid_from,
    )


@pytest.mark.point_in_time
def test_temporal_resolution_uses_half_open_identifier_intervals(
    sqlite_session: Session,
) -> None:
    repository = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(repository, portfolios)
    boundary = datetime(2022, 1, 1, tzinfo=UTC)
    old_id = UUID("10101010-1010-4010-8010-101010101010")
    new_id = UUID("20202020-2020-4020-8020-202020202020")
    service.register_security(
        _security(old_id, "Old issuer", datetime(2020, 1, 1, tzinfo=UTC)),
        [_identifier(old_id, valid_from=datetime(2020, 1, 1, tzinfo=UTC), valid_to=boundary)],
    )
    service.register_security(
        _security(new_id, "New issuer", boundary),
        [_identifier(new_id, valid_from=boundary, valid_to=None)],
    )
    reference = SecurityReference(
        identifier="reused us",
        scheme=IdentifierScheme.VENDOR,
        provider="demo",
        exchange_mic="XNAS",
    )

    assert service.resolve(reference, as_of=boundary.replace(year=2021)).security_id == old_id
    # valid_to is exclusive, so the new mapping owns the exact boundary instant.
    assert service.resolve(reference, as_of=boundary).security_id == new_id

    with pytest.raises(DomainValidationError, match="cannot overlap"):
        repository.add_identifier(
            _identifier(
                UUID("30303030-3030-4030-8030-303030303030"),
                valid_from=datetime(2021, 6, 1, tzinfo=UTC),
                valid_to=datetime(2022, 6, 1, tzinfo=UTC),
            )
        )


def test_holdings_import_resolves_every_row_before_persisting(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(securities, portfolios)
    service.register_security(sample_security, [sample_identifier])
    as_of = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)

    result = service.import_holdings(
        [
            HoldingUploadRow(
                identifier="EXAMPLE US",
                weight="0.04",
                identifier_scheme=IdentifierScheme.VENDOR,
                provider="demo",
                exchange_mic="XNAS",
            ),
            HoldingUploadRow(identifier="MISSING US", weight="0.01"),
        ],
        portfolio_name="test-book",
        as_of=as_of,
    )
    assert not result.is_valid
    assert result.snapshot is None
    assert result.positions == ()
    assert sqlite_session.scalar(select(func.count()).select_from(PortfolioSnapshotRecord)) == 0


def test_holdings_import_persists_snapshot_before_foreign_key_positions(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
) -> None:
    """SQLite FK enforcement catches child-before-parent unit-of-work ordering."""

    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(securities, portfolios)
    service.register_security(sample_security, [sample_identifier])

    result = service.import_holdings(
        [
            HoldingUploadRow(
                identifier="EXAMPLE US",
                weight="0.04",
                identifier_scheme=IdentifierScheme.VENDOR,
                provider="demo",
                exchange_mic="XNAS",
            )
        ],
        portfolio_name="ordered-book",
        as_of=datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
    )

    assert result.is_valid
    assert result.snapshot is not None
    assert sqlite_session.scalar(select(func.count()).select_from(PortfolioSnapshotRecord)) == 1
    assert sqlite_session.scalar(select(func.count()).select_from(PortfolioPositionRecord)) == 1


def test_coverage_import_persists_peer_context_without_position(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(securities, portfolios)
    service.register_security(sample_security, [sample_identifier])
    as_of = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    result = service.import_coverage(
        [
            CoverageUploadRow(
                identifier="EXAMPLE US",
                peer_group="enterprise_software",
                identifier_scheme=IdentifierScheme.VENDOR,
                provider="demo",
                exchange_mic="XNAS",
            )
        ],
        name="research coverage",
        as_of=as_of,
    )
    assert result.is_valid
    assert result.coverage_list is not None
    assert result.members[0].peer_group == "enterprise_software"
    active = portfolios.active_coverage_members(
        result.coverage_list.coverage_list_id,
        as_of=as_of,
    )
    assert [member.security_id for member in active] == [sample_security.security_id]


def test_repeated_coverage_import_keeps_one_active_temporal_membership(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(securities, portfolios)
    service.register_security(sample_security, [sample_identifier])
    first_at = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)
    row = CoverageUploadRow(
        identifier="EXAMPLE US",
        peer_group="enterprise_software",
        identifier_scheme=IdentifierScheme.VENDOR,
        provider="demo",
        exchange_mic="XNAS",
    )

    first = service.import_coverage([row], name="idempotent coverage", as_of=first_at)
    retry_at = first_at + timedelta(minutes=1)
    retry = service.import_coverage([row], name="idempotent coverage", as_of=retry_at)

    assert first.coverage_list is not None
    assert retry.coverage_list is not None
    assert retry.coverage_list.coverage_list_id == first.coverage_list.coverage_list_id
    active = portfolios.active_coverage_members(
        first.coverage_list.coverage_list_id,
        as_of=retry_at,
    )
    assert [member.security_id for member in active] == [sample_security.security_id]
    assert sqlite_session.scalar(select(func.count()).select_from(CoverageMemberRecord)) == 1

    # Half-open intervals still permit a genuine re-add at or after removal.
    stored = sqlite_session.scalar(select(CoverageMemberRecord))
    assert stored is not None
    stored.removed_at = retry_at + timedelta(minutes=1)
    sqlite_session.flush()
    readd_at = retry_at + timedelta(minutes=2)
    service.import_coverage([row], name="idempotent coverage", as_of=readd_at)
    active_after_readd = portfolios.active_coverage_members(
        first.coverage_list.coverage_list_id,
        as_of=readd_at,
    )
    assert len(active_after_readd) == 1
    assert sqlite_session.scalar(select(func.count()).select_from(CoverageMemberRecord)) == 2


def test_portfolio_csv_adapters_preserve_hash_and_peer_context(
    sqlite_session: Session,
    sample_security: Security,
    sample_identifier: SecurityIdentifier,
) -> None:
    securities = SqlAlchemySecurityRepository(sqlite_session)
    portfolios = SqlAlchemyPortfolioRepository(sqlite_session)
    service = SecurityMasterService(securities, portfolios)
    service.register_security(sample_security, [sample_identifier])
    as_of = datetime(2024, 1, 9, 21, 0, tzinfo=UTC)

    holdings = import_holdings_csv(
        (
            "identifier,weight,identifier_scheme,provider,exchange_mic\n"
            "EXAMPLE US,0.04,vendor,demo,XNAS\n"
        ),
        service=service,
        portfolio_name="adapter-book",
        as_of=as_of,
        source_name="holdings.csv",
    )
    assert holdings.is_valid
    assert holdings.snapshot is not None
    assert holdings.snapshot.source_name == "holdings.csv"
    assert holdings.snapshot.source_hash is not None
    assert len(holdings.snapshot.source_hash) == 64
    assert float(holdings.positions[0].weight) == pytest.approx(0.04)

    coverage = import_coverage_csv(
        (
            "identifier,peer_group,identifier_scheme,provider,exchange_mic\n"
            "EXAMPLE US,enterprise_software,vendor,demo,XNAS\n"
        ),
        service=service,
        name="adapter-coverage",
        as_of=as_of,
    )
    assert coverage.is_valid
    assert coverage.members[0].peer_group == "enterprise_software"

    # Parse errors stop before identifier resolution or persistence.
    with pytest.raises(ValueError, match="weight must be finite"):
        import_holdings_csv(
            b"identifier,weight\nEXAMPLE US,10.1\n",
            service=service,
            portfolio_name="invalid-book",
            as_of=as_of,
        )
