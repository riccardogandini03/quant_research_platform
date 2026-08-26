"""Enforce price ingestion attempt identity.

Revision ID: 20260825_0006
Revises: 20260825_0005
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0006"
down_revision: str | None = "20260825_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTEMPT_CONSTRAINT = "uq_price_bar_ingestion_batch_source_record"


def upgrade() -> None:
    """Reject ambiguous legacy attempts before enforcing their identity."""
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT ingestion_batch_id, source_record_id "
                "FROM price_bar "
                "GROUP BY ingestion_batch_id, source_record_id "
                "HAVING COUNT(*) > 1 "
                "LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "cannot add price attempt identity: duplicate legacy "
            "(ingestion_batch_id, source_record_id) rows must be remediated first"
        )

    with op.batch_alter_table("price_bar") as batch_op:
        batch_op.create_unique_constraint(
            _ATTEMPT_CONSTRAINT,
            ["ingestion_batch_id", "source_record_id"],
        )


def downgrade() -> None:
    """Remove only the price attempt identity constraint."""
    with op.batch_alter_table("price_bar") as batch_op:
        batch_op.drop_constraint(_ATTEMPT_CONSTRAINT, type_="unique")
