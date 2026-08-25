"""Persist price source and usage provenance.

Revision ID: 20260825_0005
Revises: 20260821_0004
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0005"
down_revision: str | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INGESTION_BATCH = sa.table(
    "ingestion_batch",
    sa.column("provider", sa.String(80)),
    sa.column("original_source", sa.String(80)),
    sa.column("usage_mode", sa.String(40)),
)
_PRICE_BAR = sa.table(
    "price_bar",
    sa.column("usage_mode", sa.String(40)),
)
_LEGACY_USAGE_MODE = sa.text("'unverified'")
_INVALID_LEGACY_PROVIDER = (
    "cannot backfill ingestion batch original_source: legacy provider must contain "
    "1 to 80 characters"
)


def upgrade() -> None:
    """Backfill conservative provenance before enforcing required columns."""
    bind = op.get_bind()
    invalid_provider = bind.execute(
        sa.select(_INGESTION_BATCH.c.provider)
        .where(
            sa.or_(
                _INGESTION_BATCH.c.provider.is_(None),
                sa.func.trim(_INGESTION_BATCH.c.provider) == "",
                sa.func.length(_INGESTION_BATCH.c.provider) > 80,
            )
        )
        .limit(1)
    ).first()
    if invalid_provider is not None:
        raise RuntimeError(_INVALID_LEGACY_PROVIDER)

    op.add_column(
        "ingestion_batch",
        sa.Column(
            "usage_mode",
            sa.String(40),
            nullable=True,
            server_default=_LEGACY_USAGE_MODE,
        ),
    )
    op.add_column(
        "price_bar",
        sa.Column(
            "usage_mode",
            sa.String(40),
            nullable=True,
            server_default=_LEGACY_USAGE_MODE,
        ),
    )
    op.add_column(
        "ingestion_batch",
        sa.Column("original_source", sa.String(80), nullable=True),
    )

    bind.execute(_INGESTION_BATCH.update().values(usage_mode="unverified"))
    bind.execute(_PRICE_BAR.update().values(usage_mode="unverified"))
    bind.execute(_INGESTION_BATCH.update().values(original_source=_INGESTION_BATCH.c.provider))

    with op.batch_alter_table("ingestion_batch") as batch_op:
        batch_op.alter_column(
            "usage_mode",
            existing_type=sa.String(40),
            nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "original_source",
            existing_type=sa.String(80),
            nullable=False,
        )
    with op.batch_alter_table("price_bar") as batch_op:
        batch_op.alter_column(
            "usage_mode",
            existing_type=sa.String(40),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    """Remove exactly the provenance columns added by this revision."""
    with op.batch_alter_table("price_bar") as batch_op:
        batch_op.drop_column("usage_mode")
    with op.batch_alter_table("ingestion_batch") as batch_op:
        batch_op.drop_column("original_source")
        batch_op.drop_column("usage_mode")
