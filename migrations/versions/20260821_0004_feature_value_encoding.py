"""Encode feature values for type-exact portable JSON storage.

Revision ID: 20260821_0004
Revises: 20260821_0003
Create Date: 2026-08-21
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "20260821_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUE_KEY = "__quant_raas_feature_value_v1__"
_FEATURE_SNAPSHOT = sa.table(
    "feature_snapshot",
    # Preserve the exact representation returned by the database. In particular,
    # legacy SQLite rows can contain either hyphenated or compact UUID text.
    sa.column("feature_snapshot_id"),
    sa.column("value", sa.JSON()),
)


def _validate_json(value: Any, *, feature_snapshot_id: object) -> None:
    try:
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            "cannot migrate feature-value encoding: feature snapshot "
            f"{feature_snapshot_id} contains unsupported JSON"
        ) from error


def _update_value(
    bind: Connection,
    *,
    direction: str,
    feature_snapshot_id: object,
    value: Any,
) -> None:
    result = bind.execute(
        _FEATURE_SNAPSHOT.update()
        .where(_FEATURE_SNAPSHOT.c.feature_snapshot_id == feature_snapshot_id)
        .values(value=value)
    )
    if result.rowcount != 1:
        raise RuntimeError(
            f"20260821_0004 {direction} for feature snapshot "
            f"{feature_snapshot_id!r} expected to update exactly one row; "
            f"updated {result.rowcount}"
        )


def upgrade() -> None:
    """Wrap every legacy value in one unambiguous storage envelope."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _FEATURE_SNAPSHOT.c.feature_snapshot_id,
            _FEATURE_SNAPSHOT.c.value,
        ).order_by(_FEATURE_SNAPSHOT.c.feature_snapshot_id)
    ).mappings()
    encoded: list[tuple[object, dict[str, Any]]] = []
    for row in rows:
        feature_snapshot_id = row["feature_snapshot_id"]
        value = row["value"]
        _validate_json(value, feature_snapshot_id=feature_snapshot_id)
        encoded.append((feature_snapshot_id, {_VALUE_KEY: value}))

    for feature_snapshot_id, value in encoded:
        _update_value(
            bind,
            direction="upgrade",
            feature_snapshot_id=feature_snapshot_id,
            value=value,
        )


def downgrade() -> None:
    """Remove exactly the encoding layer established by this revision."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(
            _FEATURE_SNAPSHOT.c.feature_snapshot_id,
            _FEATURE_SNAPSHOT.c.value,
        ).order_by(_FEATURE_SNAPSHOT.c.feature_snapshot_id)
    ).mappings()
    decoded: list[tuple[object, Any]] = []
    for row in rows:
        feature_snapshot_id = row["feature_snapshot_id"]
        envelope = row["value"]
        if not isinstance(envelope, dict) or set(envelope) != {_VALUE_KEY}:
            raise RuntimeError(
                "cannot downgrade feature-value encoding: feature snapshot "
                f"{feature_snapshot_id} does not contain the exact 20260821_0004 "
                "feature-value envelope; repair the row before retrying"
            )
        value = envelope[_VALUE_KEY]
        _validate_json(value, feature_snapshot_id=feature_snapshot_id)
        if bind.dialect.name == "sqlite" and isinstance(value, float) and value.is_integer():
            raise RuntimeError(
                "cannot downgrade feature-value encoding losslessly on SQLite: "
                f"feature snapshot {feature_snapshot_id!r} contains a top-level "
                f"integral float ({value!r}); replace or delete that value before "
                "retrying the downgrade"
            )
        decoded.append((feature_snapshot_id, value))

    for feature_snapshot_id, value in decoded:
        _update_value(
            bind,
            direction="downgrade",
            feature_snapshot_id=feature_snapshot_id,
            value=value,
        )
