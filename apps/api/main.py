"""FastAPI application factory and liveness endpoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from apps.api.routes import router
from quant_raas.config import get_settings
from quant_raas.storage.session import create_schema, create_session_factory, create_sql_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = create_sql_engine(settings)
    # Local/test environments may bootstrap an empty database. Production uses
    # reviewed Alembic migrations and must never mutate schema on web startup.
    if settings.environment in {"development", "test"}:
        create_schema(engine)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    yield
    engine.dispose()


app = FastAPI(
    title="Quant Research-as-a-Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    try:
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "unavailable"}
    return {"status": "ok", "database": "available"}
