# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

# Keep timestamps/log output deterministic and make container logs visible
# without waiting for Python's stdout buffer to flush.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    QUANT_RAAS_DATA_DIRECTORY=/app/data \
    QUANT_RAAS_DATABASE_URL=sqlite+pysqlite:////app/data/quant_raas.db

WORKDIR /app

RUN addgroup --system quant-raas \
    && adduser --system --ingroup quant-raas --home /app quant-raas

COPY pyproject.toml README.md ./
COPY src ./src

# Default to the API and PostgreSQL driver only. Compose overrides this argument
# for dashboard/worker images; vendor SDKs are never installed implicitly.
ARG INSTALL_EXTRAS="api,postgres"
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir ".[${INSTALL_EXTRAS}]"

COPY --chown=quant-raas:quant-raas configs ./configs
COPY --chown=quant-raas:quant-raas apps ./apps
COPY --chown=quant-raas:quant-raas workflows ./workflows
COPY --chown=quant-raas:quant-raas migrations ./migrations
COPY --chown=quant-raas:quant-raas alembic.ini ./alembic.ini

RUN mkdir -p /app/data && chown quant-raas:quant-raas /app/data

USER quant-raas
EXPOSE 8000

# This is a development/runtime default, not a production server topology.
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
