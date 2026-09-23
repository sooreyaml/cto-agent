"""add metadata fields for agent run traces

Revision ID: 20260922_0008
Revises: 20260908_0007
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0008"
down_revision: str | None = "20260908_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("logs", sa.Column("trace_id", sa.Text(), nullable=True))
    op.add_column("logs", sa.Column("prompt_version", sa.Text(), nullable=True))
    op.add_column("logs", sa.Column("provider", sa.Text(), nullable=True))
    op.add_column("logs", sa.Column("model", sa.Text(), nullable=True))
    op.add_column("logs", sa.Column("context_chars", sa.Integer(), nullable=True))
    op.add_column("logs", sa.Column("available_tools", sa.Integer(), nullable=True))
    op.add_column(
        "logs",
        sa.Column("tool_outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_logs_trace_id", "logs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_logs_trace_id", table_name="logs")
    op.drop_column("logs", "tool_outcomes")
    op.drop_column("logs", "available_tools")
    op.drop_column("logs", "context_chars")
    op.drop_column("logs", "model")
    op.drop_column("logs", "provider")
    op.drop_column("logs", "prompt_version")
    op.drop_column("logs", "trace_id")
