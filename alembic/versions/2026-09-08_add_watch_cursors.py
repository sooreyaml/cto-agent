"""add watch_cursors for CI failure dedupe

Revision ID: 20260908_0005
Revises: 20260908_0004
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260908_0005"
down_revision: str | None = "20260908_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watch_cursors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("notified_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_watch_cursors"),
        sa.UniqueConstraint("source", "external_id", name="uq_watch_cursors_source_external_id"),
    )


def downgrade() -> None:
    op.drop_table("watch_cursors")
