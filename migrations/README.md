# Database migrations

Run `alembic upgrade head` after configuring `QUANT_RAAS_DATABASE_URL`.
Migrations are intentionally explicit snapshots of the schema; application
startup must not create or mutate production tables implicitly.
