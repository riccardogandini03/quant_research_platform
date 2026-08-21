"""Scope feature snapshot vintages to their research run.

Revision ID: 20260821_0003
Revises: 20260820_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_VINTAGE_COLUMNS = [
    "security_id",
    "feature_name",
    "feature_version",
    "effective_at",
    "available_at",
    "code_version",
    "config_version",
]
_RUN_SCOPED_VINTAGE_COLUMNS = [*_OLD_VINTAGE_COLUMNS, "research_run_id"]


def upgrade() -> None:
    """Allow the same feature vintage to be retained for distinct runs."""
    with op.batch_alter_table("feature_snapshot") as batch_op:
        batch_op.drop_constraint("uq_feature_snapshot_vintage", type_="unique")
        batch_op.create_unique_constraint(
            "uq_feature_snapshot_vintage",
            _RUN_SCOPED_VINTAGE_COLUMNS,
        )


def downgrade() -> None:
    """Restore the pre-lineage natural key for compatible data."""
    feature_snapshot = sa.table(
        "feature_snapshot",
        *(sa.column(name) for name in _OLD_VINTAGE_COLUMNS),
    )
    old_key_columns = tuple(feature_snapshot.c[name] for name in _OLD_VINTAGE_COLUMNS)
    duplicate = (
        op.get_bind()
        .execute(
            sa.select(sa.literal(1))
            .select_from(feature_snapshot)
            .group_by(*old_key_columns)
            .having(sa.func.count() > 1)
            .limit(1)
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade feature lineage: cross-run duplicate feature vintages "
            "must be remediated before restoring uq_feature_snapshot_vintage"
        )

    with op.batch_alter_table("feature_snapshot") as batch_op:
        batch_op.drop_constraint("uq_feature_snapshot_vintage", type_="unique")
        batch_op.create_unique_constraint(
            "uq_feature_snapshot_vintage",
            _OLD_VINTAGE_COLUMNS,
        )
