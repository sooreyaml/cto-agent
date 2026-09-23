"""add owner-scoped durable memory items

Revision ID: 20260923_0009
Revises: 20260922_0008
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0009"
down_revision: str | None = "20260922_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("source_trace_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_recalled_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_memory_items"),
        sa.UniqueConstraint(
            "owner_id",
            "kind",
            "key",
            name="uq_memory_items_owner_kind_key",
        ),
    )
    op.create_index(
        "ix_memory_items_owner_status_updated",
        "memory_items",
        ["owner_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_memory_items_owner_kind_key",
        "memory_items",
        ["owner_id", "kind", "key"],
    )
    op.add_column("logs", sa.Column("memory_hits", sa.Integer(), nullable=True))
    op.add_column("logs", sa.Column("memory_chars", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("logs", "memory_chars")
    op.drop_column("logs", "memory_hits")
    op.drop_index("ix_memory_items_owner_kind_key", table_name="memory_items")
    op.drop_index("ix_memory_items_owner_status_updated", table_name="memory_items")
    op.drop_table("memory_items")
