"""Engine and transaction helpers shared by delivery adapters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from quant_raas.config import Settings, get_settings
from quant_raas.storage.base import Base


def create_sql_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy engine without connecting eagerly."""

    resolved = settings or get_settings()
    url = make_url(resolved.database_url)
    engine_options: dict[str, Any] = {
        "echo": resolved.database_echo,
        "future": True,
    }
    if url.get_backend_name() == "sqlite":
        # FastAPI/TestClient may create and dispose sessions on different
        # threads. SQLite permits that safe hand-off only when this guard is
        # disabled; SQLAlchemy still serializes pool checkout as usual.
        engine_options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            # Every ordinary SQLite in-memory connection owns a different
            # database. A single shared connection keeps the schema and data
            # visible across request/lifespan threads in local and API tests.
            engine_options["poolclass"] = StaticPool
    engine = create_engine(
        resolved.database_url,
        **engine_options,
    )
    if engine.dialect.name == "sqlite":
        # SQLite does not enforce foreign keys unless each connection enables it.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions that keep loaded values usable after commit."""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create tables for tests/local demos; deployed databases use Alembic."""

    # Import registers all mapped tables with Base.metadata.
    from quant_raas.storage import models as _models  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit one application operation atomically, rolling back on failure."""

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
