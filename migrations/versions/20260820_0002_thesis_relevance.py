"""Add thesis relevance identity, authorship, and lineage columns.

Revision ID: 20260820_0002
Revises: 20260811_0001
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add upgrade-safe thesis attribution and research lineage."""
    with op.batch_alter_table("thesis") as batch_op:
        batch_op.add_column(sa.Column("thesis_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("created_by", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("archived_by", sa.String(length=160), nullable=True))

    with op.batch_alter_table("thesis_version") as batch_op:
        batch_op.add_column(sa.Column("authored_by", sa.String(length=160), nullable=True))

    with op.batch_alter_table("research_finding") as batch_op:
        batch_op.add_column(sa.Column("thesis_version_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("thesis_relevance", sa.JSON(), nullable=True))

    with op.batch_alter_table("research_card") as batch_op:
        batch_op.add_column(sa.Column("thesis_version_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "thesis_node_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    bind = op.get_bind()
    for row in bind.execute(
        sa.text(
            "SELECT t.thesis_id, "
            "(SELECT tv.approved_by FROM thesis_version tv "
            " WHERE tv.thesis_id=t.thesis_id ORDER BY tv.version LIMIT 1) AS approver "
            "FROM thesis t"
        )
    ).mappings():
        bind.execute(
            sa.text(
                "UPDATE thesis SET thesis_key=:key, created_by=:author WHERE thesis_id=:thesis_id"
            ),
            {
                "key": f"legacy_{str(row['thesis_id']).replace('-', '').lower()}",
                "author": row["approver"] or "legacy_import",
                "thesis_id": row["thesis_id"],
            },
        )
    bind.execute(sa.text("UPDATE thesis_version SET authored_by=approved_by"))

    with op.batch_alter_table("thesis") as batch_op:
        batch_op.alter_column("thesis_key", existing_type=sa.String(length=128), nullable=False)
        batch_op.alter_column("created_by", existing_type=sa.String(length=160), nullable=False)
        batch_op.create_unique_constraint("uq_thesis_thesis_key", ["thesis_key"])

    with op.batch_alter_table("thesis_version") as batch_op:
        batch_op.alter_column("authored_by", existing_type=sa.String(length=160), nullable=False)

    with op.batch_alter_table("research_finding") as batch_op:
        batch_op.create_foreign_key(
            "fk_research_finding_thesis_version_id_thesis_version",
            "thesis_version",
            ["thesis_version_id"],
            ["thesis_version_id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("research_card") as batch_op:
        batch_op.create_foreign_key(
            "fk_research_card_thesis_version_id_thesis_version",
            "thesis_version",
            ["thesis_version_id"],
            ["thesis_version_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Remove thesis relevance additions in reverse dependency order."""
    with op.batch_alter_table("research_card") as batch_op:
        batch_op.drop_constraint(
            "fk_research_card_thesis_version_id_thesis_version", type_="foreignkey"
        )
        batch_op.drop_column("thesis_node_ids")
        batch_op.drop_column("thesis_version_id")

    with op.batch_alter_table("research_finding") as batch_op:
        batch_op.drop_constraint(
            "fk_research_finding_thesis_version_id_thesis_version", type_="foreignkey"
        )
        batch_op.drop_column("thesis_relevance")
        batch_op.drop_column("thesis_version_id")

    with op.batch_alter_table("thesis_version") as batch_op:
        batch_op.drop_column("authored_by")

    with op.batch_alter_table("thesis") as batch_op:
        batch_op.drop_constraint("uq_thesis_thesis_key", type_="unique")
        batch_op.drop_column("archived_by")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("created_by")
        batch_op.drop_column("thesis_key")
