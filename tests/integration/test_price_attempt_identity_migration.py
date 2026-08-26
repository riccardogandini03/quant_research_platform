"""Reversible migration coverage for price ingestion attempt identity."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from quant_raas.config import get_settings
from quant_raas.storage.models import PriceBarRecord

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
ATTEMPT_REVISION = "20260825_0006"
PROVENANCE_REVISION = "20260825_0005"
ATTEMPT_CONSTRAINT = "uq_price_bar_ingestion_batch_source_record"
NOW = datetime(2024, 1, 10, 10, 0, tzinfo=UTC)
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
BATCH_ID = UUID("22222222-2222-4222-8222-222222222222")
BAR_ID = UUID("33333333-3333-4333-8333-333333333333")


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


def _unique_constraint_names(engine: Engine) -> set[str]:
    return {
        str(constraint["name"])
        for constraint in inspect(engine).get_unique_constraints("price_bar")
    }


def _column_names(engine: Engine, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspect(engine).get_columns(table_name)}


def _insert_records(engine: Engine, *, duplicate_attempt: bool) -> None:
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
                "(batch_id,batch_key,provider,original_source,usage_mode,dataset,requested_at,"
                "started_at,completed_at,status,request_fingerprint,content_hash,row_count,"
                "error_message) VALUES (:id,'legacy:price:attempt','legacy','legacy','unverified',"
                "'daily_price_bar',:now,:now,:now,'succeeded','12345678legacy',"
                "'abcdef12legacy',:row_count,NULL)"
            ),
            {
                "id": BATCH_ID.hex,
                "now": NOW.isoformat(),
                "row_count": 2 if duplicate_attempt else 1,
            },
        )
        bars = [(BAR_ID, NOW)]
        if duplicate_attempt:
            bars.append(
                (
                    UUID("44444444-4444-4444-8444-444444444444"),
                    NOW + timedelta(minutes=1),
                )
            )
        for bar_id, available_at in bars:
            connection.execute(
                text(
                    "INSERT INTO price_bar "
                    "(price_bar_id,security_id,session_date,frequency,effective_at,available_at,"
                    "ingested_at,open,high,low,close,adjusted_close,volume,currency,"
                    "adjustment_factor,total_return_factor,source,usage_mode,source_record_id,"
                    "provider_identifier,ingestion_batch_id,quality_flags) VALUES "
                    "(:bar,:security,:session,'1d',:effective,:available,:available,100,102,99,"
                    "101,100.5,1000,'USD',:factor,NULL,'legacy','unverified',"
                    "'EXAMPLE.O:2024-01-09','EXAMPLE.O',:batch,:flags)"
                ),
                {
                    "bar": bar_id.hex,
                    "security": SECURITY_ID.hex,
                    "session": date(2024, 1, 9).isoformat(),
                    "effective": (NOW - timedelta(hours=1)).isoformat(),
                    "available": available_at.isoformat(),
                    "factor": 100.5 / 101.0,
                    "batch": BATCH_ID.hex,
                    "flags": json.dumps([]),
                },
            )


def test_price_attempt_migration_adds_unique_constraint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'price-attempt.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PROVENANCE_REVISION)
    engine = create_engine(url)
    try:
        _insert_records(engine, duplicate_attempt=False)
        batch_columns = _column_names(engine, "ingestion_batch")
        bar_columns = _column_names(engine, "price_bar")

        command.upgrade(config, ATTEMPT_REVISION)

        assert _revision(engine) == ATTEMPT_REVISION
        assert ATTEMPT_CONSTRAINT in _unique_constraint_names(engine)
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO price_bar "
                    "(price_bar_id,security_id,session_date,frequency,effective_at,"
                    "available_at,ingested_at,open,high,low,close,adjusted_close,volume,"
                    "currency,adjustment_factor,total_return_factor,source,usage_mode,"
                    "source_record_id,provider_identifier,ingestion_batch_id,quality_flags) "
                    "SELECT :bar,security_id,session_date,frequency,effective_at,:available,"
                    ":available,open,high,low,close,adjusted_close,volume,currency,"
                    "adjustment_factor,total_return_factor,source,usage_mode,source_record_id,"
                    "provider_identifier,ingestion_batch_id,quality_flags "
                    "FROM price_bar WHERE price_bar_id=:existing"
                ),
                {
                    "bar": UUID("55555555-5555-4555-8555-555555555555").hex,
                    "available": (NOW + timedelta(minutes=2)).isoformat(),
                    "existing": BAR_ID.hex,
                },
            )

        command.downgrade(config, PROVENANCE_REVISION)

        assert _revision(engine) == PROVENANCE_REVISION
        assert ATTEMPT_CONSTRAINT not in _unique_constraint_names(engine)
        assert _column_names(engine, "ingestion_batch") == batch_columns
        assert _column_names(engine, "price_bar") == bar_columns
        assert {"original_source", "usage_mode"} <= batch_columns
        assert "usage_mode" in bar_columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM ingestion_batch")) == 1
            assert connection.scalar(text("SELECT count(*) FROM price_bar")) == 1

        command.upgrade(config, ATTEMPT_REVISION)
        assert ATTEMPT_CONSTRAINT in _unique_constraint_names(engine)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM price_bar")) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_price_attempt_migration_rejects_legacy_duplicate_rows_before_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'duplicate-price-attempt.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PROVENANCE_REVISION)
    engine = create_engine(url)
    try:
        _insert_records(engine, duplicate_attempt=True)
        batch_columns = _column_names(engine, "ingestion_batch")
        bar_columns = _column_names(engine, "price_bar")

        with pytest.raises(
            RuntimeError,
            match=(
                r"^cannot add price attempt identity: duplicate legacy "
                r"\(ingestion_batch_id, source_record_id\) rows must be remediated first$"
            ),
        ):
            command.upgrade(config, ATTEMPT_REVISION)

        assert _revision(engine) == PROVENANCE_REVISION
        assert ATTEMPT_CONSTRAINT not in _unique_constraint_names(engine)
        assert _column_names(engine, "ingestion_batch") == batch_columns
        assert _column_names(engine, "price_bar") == bar_columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM ingestion_batch")) == 1
            assert connection.scalar(text("SELECT count(*) FROM price_bar")) == 2
            provenance = connection.execute(
                text(
                    "SELECT original_source, usage_mode FROM ingestion_batch WHERE batch_id=:batch"
                ),
                {"batch": BATCH_ID.hex},
            ).one()
            bar_usage = (
                connection.execute(text("SELECT usage_mode FROM price_bar ORDER BY price_bar_id"))
                .scalars()
                .all()
            )
        assert provenance.original_source == "legacy"
        assert provenance.usage_mode == "unverified"
        assert bar_usage == ["unverified", "unverified"]
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_price_attempt_metadata_matches_head_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'price-attempt-head.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        reflected = _unique_constraint_names(engine)
        metadata = {
            str(constraint.name)
            for constraint in PriceBarRecord.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert reflected == metadata
        assert ATTEMPT_CONSTRAINT in reflected
    finally:
        engine.dispose()
        get_settings.cache_clear()
