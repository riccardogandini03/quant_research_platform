"""Reversible migration coverage for feature-value JSON encoding."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from quant_raas.config import get_settings
from quant_raas.domain.market import FeatureSnapshot
from quant_raas.storage.models import FeatureSnapshotRecord
from quant_raas.storage.repositories import SqlAlchemyFeatureRepository

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
ENCODING_REVISION = "20260821_0004"
PRE_ENCODING_REVISION = "20260821_0003"
PRE_LINEAGE_REVISION = "20260820_0002"
RESERVED_KEY = "__quant_raas_feature_value_v1__"
SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
RUN_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
NOW = datetime(2024, 1, 10, 22, 0, tzinfo=UTC)

PLAIN_FEATURE = sa.table(
    "feature_snapshot",
    sa.column("feature_snapshot_id"),
    sa.column("feature_name", sa.String()),
    sa.column("value", sa.JSON()),
)

LEGACY_VALUES: dict[str, Any] = {
    "bool_value": True,
    "int_value": 7,
    "float_value": 1.25,
    "string_value": "signal",
    "list_value": [True, 7, 1.0, -0.0, 1.25, "signal", None],
    "dict_value": {
        "nested": {
            "bool": True,
            "int": 7,
            "integral_float": 1.0,
            "negative_zero": -0.0,
            "float": 1.25,
        }
    },
    "null_value": None,
    "reserved_value": {RESERVED_KEY: "payload"},
    "reserved_null": {RESERVED_KEY: None},
    # SQLite's legacy JSON numeric affinity irreversibly normalizes this
    # pre-migration scalar to int 1 before revision 0004 can see it.
    "legacy_integral_float": 1.0,
}
LEGACY_VALUES_AFTER_SQLITE_AFFINITY = {
    **LEGACY_VALUES,
    "legacy_integral_float": 1,
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


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _assert_json_values_exact(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    assert actual.keys() == expected.keys()
    assert {key: _json_text(value) for key, value in actual.items()} == {
        key: _json_text(value) for key, value in expected.items()
    }


def _plain_values(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(PLAIN_FEATURE.c.feature_name, PLAIN_FEATURE.c.value).order_by(
                PLAIN_FEATURE.c.feature_name
            )
        ).all()
    return {row.feature_name: row.value for row in rows}


def _plain_ids(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(
                PLAIN_FEATURE.c.feature_name,
                PLAIN_FEATURE.c.feature_snapshot_id,
            ).order_by(PLAIN_FEATURE.c.feature_name)
        ).all()
    return {row.feature_name: row.feature_snapshot_id for row in rows}


def _current_values(engine: Engine) -> dict[str, Any]:
    with Session(engine) as session:
        rows = session.scalars(
            select(FeatureSnapshotRecord).order_by(FeatureSnapshotRecord.feature_name)
        ).all()
        return {row.feature_name: row.value for row in rows}


def _insert_supporting_records(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security "
                "(security_id,name,security_type,status,primary_currency,created_at,updated_at) "
                "VALUES (:id,'Example','common_stock','active','USD',:now,:now)"
            ),
            {"id": SECURITY_ID.hex, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO research_run "
                "(research_run_id,run_key,run_type,as_of,data_cutoff_at,started_at,"
                "completed_at,status,code_version,config_version,ingestion_batch_ids) "
                "VALUES (:id,'daily:encoding','daily',:now,:now,:now,:now,'succeeded',"
                "'code-v1','bundle-v1',:batch_ids)"
            ),
            {"id": RUN_ID.hex, "now": NOW, "batch_ids": json.dumps([])},
        )


def _insert_plain_features(
    engine: Engine,
    values: dict[str, Any],
    *,
    id_start: int = 1000,
    hyphenated_offsets: frozenset[int] = frozenset(),
    encoded: bool = False,
) -> None:
    with engine.begin() as connection:
        for offset, (feature_name, value) in enumerate(values.items()):
            connection.execute(
                text(
                    "INSERT INTO feature_snapshot "
                    "(feature_snapshot_id,security_id,feature_name,feature_version,"
                    "effective_at,available_at,calculated_at,value,quality_flags,"
                    "input_evidence_ids,research_run_id,code_version,config_version,metadata) "
                    "VALUES (:id,:security,:name,'v1',:now,:now,:now,:value,:flags,:inputs,"
                    ":run,'code-v1','panel-v1',:metadata)"
                ),
                {
                    "id": (
                        str(UUID(int=id_start + offset))
                        if offset in hyphenated_offsets
                        else UUID(int=id_start + offset).hex
                    ),
                    "security": SECURITY_ID.hex,
                    "name": feature_name,
                    "now": NOW,
                    "value": _json_text({RESERVED_KEY: value} if encoded else value),
                    "flags": json.dumps([]),
                    "inputs": json.dumps([]),
                    "run": RUN_ID.hex,
                    "metadata": json.dumps({}),
                },
            )


def _snapshots(values: dict[str, Any]) -> tuple[FeatureSnapshot, ...]:
    return tuple(
        FeatureSnapshot(
            feature_snapshot_id=UUID(int=2000 + offset),
            security_id=SECURITY_ID,
            feature_name=feature_name,
            feature_version="v1",
            effective_at=NOW,
            available_at=NOW,
            calculated_at=NOW,
            value=value,
            research_run_id=RUN_ID,
            code_version="code-v1",
            config_version="panel-v1",
        )
        for offset, (feature_name, value) in enumerate(values.items())
    )


def _enveloped(values: dict[str, Any]) -> dict[str, Any]:
    return {name: {RESERVED_KEY: value} for name, value in values.items()}


def test_upgrade_encodes_every_legacy_json_kind_without_reserved_key_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'feature-value-upgrade.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PRE_ENCODING_REVISION)
    engine = create_engine(url)
    try:
        _insert_supporting_records(engine)
        _insert_plain_features(
            engine,
            LEGACY_VALUES,
            hyphenated_offsets=frozenset({0}),
        )
        _assert_json_values_exact(_plain_values(engine), LEGACY_VALUES_AFTER_SQLITE_AFFINITY)
        assert _plain_ids(engine)["bool_value"] == str(UUID(int=1000))
        assert _plain_ids(engine)["int_value"] == UUID(int=1001).hex

        command.upgrade(config, ENCODING_REVISION)

        _assert_json_values_exact(_current_values(engine), LEGACY_VALUES_AFTER_SQLITE_AFFINITY)
        _assert_json_values_exact(
            _plain_values(engine),
            _enveloped(LEGACY_VALUES_AFTER_SQLITE_AFFINITY),
        )
        assert _plain_ids(engine)["bool_value"] == str(UUID(int=1000))
        assert _plain_ids(engine)["int_value"] == UUID(int=1001).hex
        assert _revision(engine) == ENCODING_REVISION
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_encoding_revision_writes_round_trip_and_downgrade_unwraps_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'feature-value-roundtrip.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PRE_LINEAGE_REVISION)
    command.upgrade(config, ENCODING_REVISION)
    engine = create_engine(url)
    encoding_values: dict[str, Any] = {
        **LEGACY_VALUES_AFTER_SQLITE_AFFINITY,
        "integral_float": 1.0,
        "negative_zero": -0.0,
    }
    hyphenated_values = {"hyphenated_head_value": {"driver": "legacy"}}
    all_encoding_values = {**encoding_values, **hyphenated_values}
    try:
        _insert_supporting_records(engine)
        snapshots = _snapshots(encoding_values)
        with Session(engine) as session:
            assert SqlAlchemyFeatureRepository(session).upsert_many(snapshots) == len(snapshots)
            session.commit()
        _insert_plain_features(
            engine,
            hyphenated_values,
            id_start=4000,
            hyphenated_offsets=frozenset({0}),
            encoded=True,
        )

        _assert_json_values_exact(_current_values(engine), all_encoding_values)
        raw_before = _enveloped(all_encoding_values)
        _assert_json_values_exact(_plain_values(engine), raw_before)
        assert _plain_ids(engine)["hyphenated_head_value"] == str(UUID(int=4000))
        assert _plain_ids(engine)["bool_value"] == UUID(int=2000).hex
        assert _revision(engine) == ENCODING_REVISION

        with pytest.raises(
            RuntimeError,
            match=r"losslessly.*SQLite.*top-level integral float",
        ):
            command.downgrade(config, PRE_ENCODING_REVISION)

        assert _revision(engine) == ENCODING_REVISION
        _assert_json_values_exact(_plain_values(engine), raw_before)

        remediated_values = {
            **all_encoding_values,
            "integral_float": 1.5,
            "negative_zero": -0.5,
        }
        with engine.begin() as connection:
            for feature_name in ("integral_float", "negative_zero"):
                result = connection.execute(
                    PLAIN_FEATURE.update()
                    .where(PLAIN_FEATURE.c.feature_name == feature_name)
                    .values(value={RESERVED_KEY: remediated_values[feature_name]})
                )
                assert result.rowcount == 1

        command.downgrade(config, PRE_ENCODING_REVISION)

        _assert_json_values_exact(_plain_values(engine), remediated_values)
        assert _plain_ids(engine)["hyphenated_head_value"] == str(UUID(int=4000))
        assert _plain_ids(engine)["bool_value"] == UUID(int=2000).hex
        assert _revision(engine) == PRE_ENCODING_REVISION

        command.downgrade(config, PRE_LINEAGE_REVISION)

        _assert_json_values_exact(_plain_values(engine), remediated_values)
        assert _revision(engine) == PRE_LINEAGE_REVISION

        command.upgrade(config, ENCODING_REVISION)

        _assert_json_values_exact(_current_values(engine), remediated_values)
        _assert_json_values_exact(_plain_values(engine), _enveloped(remediated_values))
        assert _plain_ids(engine)["hyphenated_head_value"] == str(UUID(int=4000))
        assert _plain_ids(engine)["bool_value"] == UUID(int=2000).hex
        assert _revision(engine) == ENCODING_REVISION
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_strict_decoder_and_downgrade_preflight_reject_unencoded_head_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'feature-value-strict.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, ENCODING_REVISION)
    engine = create_engine(url)
    valid_values = {"valid_value": {"nested": [True, 7, 1.25, None]}}
    invalid_values = {"unencoded_value": {"legacy": "raw"}}
    try:
        _insert_supporting_records(engine)
        with Session(engine) as session:
            assert SqlAlchemyFeatureRepository(session).upsert_many(
                _snapshots(valid_values)
            ) == len(valid_values)
            session.commit()
        _insert_plain_features(engine, invalid_values, id_start=3000)

        invalid_id = UUID(int=3000)
        with (
            Session(engine) as session,
            pytest.raises(ValueError, match=r"20260821_0004.*missing or incompatible"),
        ):
            session.get(FeatureSnapshotRecord, invalid_id)

        raw_before = {
            **_enveloped(valid_values),
            **invalid_values,
        }
        _assert_json_values_exact(_plain_values(engine), raw_before)
        with pytest.raises(RuntimeError, match="exact 20260821_0004 feature-value envelope"):
            command.downgrade(config, PRE_ENCODING_REVISION)

        assert _revision(engine) == ENCODING_REVISION
        _assert_json_values_exact(_plain_values(engine), raw_before)

        with engine.begin() as connection:
            connection.execute(
                PLAIN_FEATURE.update()
                .where(PLAIN_FEATURE.c.feature_snapshot_id == invalid_id.hex)
                .values(value={RESERVED_KEY: invalid_values["unencoded_value"]})
            )

        command.downgrade(config, PRE_ENCODING_REVISION)

        _assert_json_values_exact(
            _plain_values(engine),
            {**valid_values, **invalid_values},
        )
        assert _revision(engine) == PRE_ENCODING_REVISION
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_upgrade_requires_every_buffered_row_update_to_match_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'feature-value-rowcount.db').as_posix()}"
    config = _config(monkeypatch, url)
    command.upgrade(config, PRE_ENCODING_REVISION)
    engine = create_engine(url)
    values = {
        "first_value": {"updated": True},
        "ignored_value": {"updated": False},
    }
    try:
        _insert_supporting_records(engine)
        _insert_plain_features(engine, values, id_start=5000)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TRIGGER ignore_feature_value_update "
                    "BEFORE UPDATE OF value ON feature_snapshot "
                    "FOR EACH ROW WHEN OLD.feature_name = 'ignored_value' "
                    "BEGIN SELECT RAISE(IGNORE); END"
                )
            )

        with pytest.raises(
            RuntimeError,
            match=(
                r"20260821_0004 upgrade.*expected to update exactly one row; "
                r"updated 0"
            ),
        ):
            command.upgrade(config, ENCODING_REVISION)

        assert _revision(engine) == PRE_ENCODING_REVISION
        _assert_json_values_exact(_plain_values(engine), values)

        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER ignore_feature_value_update"))

        command.upgrade(config, ENCODING_REVISION)

        _assert_json_values_exact(_current_values(engine), values)
        _assert_json_values_exact(_plain_values(engine), _enveloped(values))
        assert _revision(engine) == ENCODING_REVISION
    finally:
        engine.dispose()
        get_settings.cache_clear()
