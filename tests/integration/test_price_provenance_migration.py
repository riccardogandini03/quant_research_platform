"""Reversible migration coverage for price usage and source provenance."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text

from quant_raas.config import get_settings
from quant_raas.storage.models import IngestionBatchRecord, PriceBarRecord

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_REVISION = "20260825_0005"
PRE_PROVENANCE_REVISION = "20260821_0004"
NOW = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
BATCH_ID = UUID("22222222-2222-4222-8222-222222222222")
BAR_ID = UUID("33333333-3333-4333-8333-333333333333")
LEGACY_BATCH_COLUMNS = {
    "batch_id",
    "batch_key",
    "provider",
    "dataset",
    "requested_at",
    "started_at",
    "completed_at",
    "status",
    "request_fingerprint",
    "content_hash",
    "row_count",
    "error_message",
}
LEGACY_PRICE_BAR_COLUMNS = {
    "price_bar_id",
    "security_id",
    "session_date",
    "frequency",
    "effective_at",
    "available_at",
    "ingested_at",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "currency",
    "adjustment_factor",
    "total_return_factor",
    "source",
    "source_record_id",
    "provider_identifier",
    "ingestion_batch_id",
    "quality_flags",
}


def _config(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Config:
    monkeypatch.setenv("QUANT_RAAS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert isinstance(revision, str)
    return revision


def _column_names(engine: Engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def _column(engine: Engine, table_name: str, column_name: str) -> dict[str, object]:
    return next(
        column
        for column in inspect(engine).get_columns(table_name)
        if column["name"] == column_name
    )


def _insert_legacy_records(
    engine: Engine,
    *,
    provider: str,
    include_bar: bool,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security "
                "(security_id,name,security_type,status,primary_currency,created_at,updated_at) "
                "VALUES (:id,'Example','common_stock','active','USD',:now,:now)"
            ),
            {"id": SECURITY_ID.hex, "now": NOW.isoformat()},
        )
        connection.execute(
            text(
                "INSERT INTO ingestion_batch "
                "(batch_id,batch_key,provider,dataset,requested_at,started_at,completed_at,"
                "status,request_fingerprint,content_hash,row_count,error_message) "
                "VALUES (:id,'legacy:price:batch',:provider,'daily_price_bar',:now,:now,:now,"
                "'succeeded','12345678legacy','abcdef12legacy',:row_count,NULL)"
            ),
            {
                "id": BATCH_ID.hex,
                "provider": provider,
                "now": NOW.isoformat(),
                "row_count": 1 if include_bar else 0,
            },
        )
        if include_bar:
            connection.execute(
                text(
                    "INSERT INTO price_bar "
                    "(price_bar_id,security_id,session_date,frequency,effective_at,"
                    "available_at,ingested_at,open,high,low,close,adjusted_close,volume,"
                    "currency,adjustment_factor,total_return_factor,source,source_record_id,"
                    "provider_identifier,ingestion_batch_id,quality_flags) "
                    "VALUES (:bar,:security,:session,'1d',:now,:now,:now,100,102,99,101,"
                    "100.5,1000,'USD',:factor,NULL,:source,'EXAMPLE.O:2024-01-09',"
                    "'EXAMPLE.O',:batch,:flags)"
                ),
                {
                    "bar": BAR_ID.hex,
                    "security": SECURITY_ID.hex,
                    "session": date(2024, 1, 9).isoformat(),
                    "now": NOW.isoformat(),
                    "factor": 100.5 / 101.0,
                    "source": provider,
                    "batch": BATCH_ID.hex,
                    "flags": json.dumps([]),
                },
            )


def test_price_provenance_migration_backfills_and_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'price-provenance.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PRE_PROVENANCE_REVISION)
    engine = create_engine(url)
    try:
        _insert_legacy_records(engine, provider="legacy_vendor", include_bar=True)

        command.upgrade(config, PROVENANCE_REVISION)

        assert _revision(engine) == PROVENANCE_REVISION
        with engine.connect() as connection:
            batch = connection.execute(
                text("SELECT original_source, usage_mode FROM ingestion_batch WHERE batch_id=:id"),
                {"id": BATCH_ID.hex},
            ).one()
            bar_usage = connection.scalar(
                text("SELECT usage_mode FROM price_bar WHERE price_bar_id=:id"),
                {"id": BAR_ID.hex},
            )
        assert batch.original_source == "legacy_vendor"
        assert batch.usage_mode == "unverified"
        assert bar_usage == "unverified"
        for table_name, column_name in (
            ("ingestion_batch", "original_source"),
            ("ingestion_batch", "usage_mode"),
            ("price_bar", "usage_mode"),
        ):
            column = _column(engine, table_name, column_name)
            assert column["nullable"] is False
            assert column["default"] is None

        command.downgrade(config, PRE_PROVENANCE_REVISION)

        assert _revision(engine) == PRE_PROVENANCE_REVISION
        assert _column_names(engine, "ingestion_batch") == LEGACY_BATCH_COLUMNS
        assert _column_names(engine, "price_bar") == LEGACY_PRICE_BAR_COLUMNS
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM ingestion_batch")) == 1
            assert connection.scalar(text("SELECT count(*) FROM price_bar")) == 1

        command.upgrade(config, PROVENANCE_REVISION)

        with engine.connect() as connection:
            restored = connection.execute(
                text("SELECT original_source, usage_mode FROM ingestion_batch WHERE batch_id=:id"),
                {"id": BATCH_ID.hex},
            ).one()
            restored_bar_usage = connection.scalar(
                text("SELECT usage_mode FROM price_bar WHERE price_bar_id=:id"),
                {"id": BAR_ID.hex},
            )
        assert restored.original_source == "legacy_vendor"
        assert restored.usage_mode == "unverified"
        assert restored_bar_usage == "unverified"
    finally:
        engine.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize("provider", ("   ", "x" * 81))
def test_price_provenance_migration_rejects_invalid_legacy_provider_before_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / f'invalid-{len(provider)}.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PRE_PROVENANCE_REVISION)
    engine = create_engine(url)
    try:
        _insert_legacy_records(engine, provider=provider, include_bar=False)

        with pytest.raises(
            RuntimeError,
            match=(
                r"^cannot backfill ingestion batch original_source: legacy provider "
                "must contain 1 to 80 characters$"
            ),
        ):
            command.upgrade(config, PROVENANCE_REVISION)

        assert _revision(engine) == PRE_PROVENANCE_REVISION
        assert _column_names(engine, "ingestion_batch") == LEGACY_BATCH_COLUMNS
        assert _column_names(engine, "price_bar") == LEGACY_PRICE_BAR_COLUMNS
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM ingestion_batch")) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_price_provenance_metadata_matches_head_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'price-provenance-head.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        for record in (IngestionBatchRecord, PriceBarRecord):
            table_name = record.__tablename__
            reflected = {
                column["name"]: column for column in inspect(engine).get_columns(table_name)
            }
            assert set(reflected) == set(record.__table__.columns.keys())
            for column_name in (
                {"original_source", "usage_mode"}
                if record is IngestionBatchRecord
                else {"usage_mode"}
            ):
                assert reflected[column_name]["nullable"] is False
                assert reflected[column_name]["default"] is None
                assert (
                    reflected[column_name]["type"].length
                    == record.__table__.c[column_name].type.length
                )
    finally:
        engine.dispose()
        get_settings.cache_clear()
