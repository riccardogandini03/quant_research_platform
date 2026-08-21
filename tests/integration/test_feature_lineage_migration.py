"""Migration coverage for research-run-scoped feature vintages."""

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

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
OLD_COLUMNS = (
    "security_id",
    "feature_name",
    "feature_version",
    "effective_at",
    "available_at",
    "code_version",
    "config_version",
)
NEW_COLUMNS = (*OLD_COLUMNS, "research_run_id")


def _config(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("QUANT_RAAS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _unique_columns(engine: object) -> tuple[str, ...]:
    constraints = inspect(engine).get_unique_constraints("feature_snapshot")
    constraint = next(item for item in constraints if item["name"] == "uq_feature_snapshot_vintage")
    return tuple(constraint["column_names"])


def test_feature_lineage_migration_preserves_data_and_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'feature-lineage.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, "20260820_0002")
    engine = create_engine(url)
    now = datetime(2024, 1, 10, 22, 0, tzinfo=UTC)
    security_id = UUID("11111111-1111-4111-8111-111111111111")
    run_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    feature_id = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
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
                "INSERT INTO research_run "
                "(research_run_id,run_key,run_type,as_of,data_cutoff_at,started_at,"
                "completed_at,status,code_version,config_version,ingestion_batch_ids) "
                "VALUES (:id,'daily:legacy','daily',:now,:now,:now,:now,'succeeded',"
                "'code-v1','bundle-v1',:batch_ids)"
            ),
            {"id": str(run_id), "now": now, "batch_ids": json.dumps([])},
        )
        connection.execute(
            text(
                "INSERT INTO feature_snapshot "
                "(feature_snapshot_id,security_id,feature_name,feature_version,effective_at,"
                "available_at,calculated_at,value,quality_flags,input_evidence_ids,"
                "research_run_id,code_version,config_version,metadata) "
                "VALUES (:id,:security,'signal','v1',:now,:now,:now,:value,:flags,:inputs,"
                ":run,'code-v1','panel-v1',:metadata)"
            ),
            {
                "id": str(feature_id),
                "security": str(security_id),
                "now": now,
                "value": json.dumps(1.25),
                "flags": json.dumps([]),
                "inputs": json.dumps([]),
                "run": str(run_id),
                "metadata": json.dumps({}),
            },
        )

    assert _unique_columns(engine) == OLD_COLUMNS

    command.upgrade(config, "head")

    assert _unique_columns(engine) == NEW_COLUMNS
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260821_0003"
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM feature_snapshot")) == 1

    command.downgrade(config, "20260820_0002")

    assert _unique_columns(engine) == OLD_COLUMNS
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM feature_snapshot")) == 1

    command.upgrade(config, "head")

    assert _unique_columns(engine) == NEW_COLUMNS
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM feature_snapshot")) == 1
        second_run_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        connection.execute(
            text(
                "INSERT INTO research_run "
                "(research_run_id,run_key,run_type,as_of,data_cutoff_at,started_at,"
                "completed_at,status,code_version,config_version,ingestion_batch_ids) "
                "VALUES (:id,'daily:second','daily',:now,:now,:now,:now,'succeeded',"
                "'code-v1','bundle-v2',:batch_ids)"
            ),
            {"id": str(second_run_id), "now": now, "batch_ids": json.dumps([])},
        )
        connection.execute(
            text(
                "INSERT INTO feature_snapshot "
                "(feature_snapshot_id,security_id,feature_name,feature_version,effective_at,"
                "available_at,calculated_at,value,quality_flags,input_evidence_ids,"
                "research_run_id,code_version,config_version,metadata) "
                "VALUES (:id,:security,'signal','v1',:now,:now,:now,:value,:flags,:inputs,"
                ":run,'code-v1','panel-v1',:metadata)"
            ),
            {
                "id": str(UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")),
                "security": str(security_id),
                "now": now,
                "value": json.dumps(1.25),
                "flags": json.dumps([]),
                "inputs": json.dumps([]),
                "run": str(second_run_id),
                "metadata": json.dumps({}),
            },
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM feature_snapshot")) == 2

    engine.dispose()
    get_settings.cache_clear()
