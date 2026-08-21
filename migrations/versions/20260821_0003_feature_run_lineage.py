"""Scope feature snapshot vintages to their research run.

Revision ID: 20260821_0003
Revises: 20260820_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

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
    with op.batch_alter_table("feature_snapshot") as batch_op:
        batch_op.drop_constraint("uq_feature_snapshot_vintage", type_="unique")
        batch_op.create_unique_constraint(
            "uq_feature_snapshot_vintage",
            _OLD_VINTAGE_COLUMNS,
        )
