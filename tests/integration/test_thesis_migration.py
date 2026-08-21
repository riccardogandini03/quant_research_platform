"""Integration coverage for the additive thesis relevance migration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from quant_raas.config import get_settings
from quant_raas.storage import models as _models  # noqa: F401
from quant_raas.storage.base import Base

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _config(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("QUANT_RAAS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def test_thesis_migration_backfills_legacy_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy thesis rows receive deterministic identity and author attribution."""
    url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, "20260811_0001")
    engine = create_engine(url)
    now = datetime(2024, 1, 10, tzinfo=UTC)
    security_id = UUID("11111111-1111-4111-8111-111111111111")
    thesis_id = UUID("71717171-7171-4717-8717-717171717171")
    version_id = UUID("72727272-7272-4727-8727-727272727272")
    later_version_id = UUID("73737373-7373-4737-8737-737373737373")
    unapproved_thesis_id = UUID("74747474-7474-4747-8747-747474747474")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security "
                "(security_id,name,security_type,status,primary_currency,created_at,updated_at) "
                "VALUES (:id,'Example','common_stock','active','USD',:now,:now)"
            ),
            {"id": str(security_id), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO thesis (thesis_id,security_id,title,status,created_at) "
                "VALUES (:id,:security,'Legacy','active',:now)"
            ),
            {"id": str(thesis_id), "security": str(security_id), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO thesis (thesis_id,security_id,title,status,created_at) "
                "VALUES (:id,:security,'No approver','active',:now)"
            ),
            {"id": str(unapproved_thesis_id), "security": str(security_id), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO thesis_version "
                "(thesis_version_id,thesis_id,version,valid_from,nodes,approved_by,approved_at,created_at) "
                "VALUES (:id,:thesis,1,:now,:nodes,'legacy@example.com',:now,:now)"
            ),
            {
                "id": str(version_id),
                "thesis": str(thesis_id),
                "now": now,
                "nodes": json.dumps(
                    {
                        "schema_version": 1,
                        "summary": "Legacy thesis content.",
                        "drivers": [],
                        "risks": [],
                        "invalidation_rules": [],
                    }
                ),
            },
        )
        connection.execute(
            text(
                "INSERT INTO thesis_version "
                "(thesis_version_id,thesis_id,version,valid_from,nodes,approved_by,approved_at,created_at) "
                "VALUES (:id,:thesis,2,:now,:nodes,'later@example.com',:now,:now)"
            ),
            {
                "id": str(later_version_id),
                "thesis": str(thesis_id),
                "now": now,
                "nodes": json.dumps({"schema_version": 1, "summary": "Later content."}),
            },
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT thesis_key, created_by FROM thesis WHERE thesis_id=:id"),
                {"id": str(thesis_id)},
            )
            .mappings()
            .one()
        )
        version = (
            connection.execute(
                text("SELECT authored_by FROM thesis_version WHERE thesis_version_id=:id"),
                {"id": str(version_id)},
            )
            .mappings()
            .one()
        )
        unapproved = (
            connection.execute(
                text("SELECT thesis_key, created_by FROM thesis WHERE thesis_id=:id"),
                {"id": str(unapproved_thesis_id)},
            )
            .mappings()
            .one()
        )
    assert row["thesis_key"] == f"legacy_{thesis_id.hex}"
    assert row["created_by"] == "legacy@example.com"
    assert version["authored_by"] == "legacy@example.com"
    assert unapproved == {
        "thesis_key": f"legacy_{unapproved_thesis_id.hex}",
        "created_by": "legacy_import",
    }
    assert "thesis_version_id" in {
        column["name"] for column in inspect(engine).get_columns("research_card")
    }
    finding_fks = inspect(engine).get_foreign_keys("research_finding")
    card_fks = inspect(engine).get_foreign_keys("research_card")
    assert (
        next(
            fk
            for fk in finding_fks
            if fk["name"] == "fk_research_finding_thesis_version_id_thesis_version"
        )["options"]["ondelete"]
        == "RESTRICT"
    )
    assert (
        next(
            fk
            for fk in card_fks
            if fk["name"] == "fk_research_card_thesis_version_id_thesis_version"
        )["options"]["ondelete"]
        == "RESTRICT"
    )

    command.downgrade(config, "20260811_0001")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        restored = (
            connection.execute(
                text("SELECT thesis_key, created_by FROM thesis WHERE thesis_id=:id"),
                {"id": str(thesis_id)},
            )
            .mappings()
            .one()
        )
    assert restored == row
    engine.dispose()
    get_settings.cache_clear()


def test_thesis_relevance_metadata_enforces_required_lineage_contract() -> None:
    """Mapped tables expose required authorship and optional restrictive lineage."""
    thesis = Base.metadata.tables["thesis"]
    thesis_version = Base.metadata.tables["thesis_version"]
    finding = Base.metadata.tables["research_finding"]
    card = Base.metadata.tables["research_card"]

    assert not thesis.c.thesis_key.nullable
    assert not thesis.c.created_by.nullable
    assert not thesis_version.c.authored_by.nullable
    assert finding.c.thesis_version_id.nullable
    assert card.c.thesis_version_id.nullable
    assert not card.c.thesis_node_ids.nullable
    assert next(iter(finding.c.thesis_version_id.foreign_keys)).ondelete == "RESTRICT"
    assert next(iter(card.c.thesis_version_id.foreign_keys)).ondelete == "RESTRICT"
