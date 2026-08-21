"""Declarative base and portable database scalar types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    """Persist aware UTC instants consistently on PostgreSQL and SQLite.

    SQLite drops timezone metadata from datetime values. The result processor
    restores UTC only because the bind processor has already rejected all naive
    values, so this cannot silently reinterpret arbitrary local timestamps.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("database datetimes must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


_FEATURE_VALUE_KEY = "__quant_raas_feature_value_v1__"


class FeatureValueJSON(TypeDecorator[Any]):
    """Preserve JSON scalar types even under SQLite's numeric affinity."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: object) -> dict[str, Any]:
        return {_FEATURE_VALUE_KEY: value}

    def process_result_value(self, value: Any, dialect: object) -> Any:
        if isinstance(value, dict) and set(value) == {_FEATURE_VALUE_KEY}:
            return value[_FEATURE_VALUE_KEY]
        return value


class Base(DeclarativeBase):
    """Base for all application-owned tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
