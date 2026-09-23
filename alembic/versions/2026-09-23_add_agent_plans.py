"""persist bounded plan/execute/verify controller state

Revision ID: 20260923_0010
Revises: 20260923_0009
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0010"
down_revision: str | None = "20260923_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_plans",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'planned'"), nullable=False),
        sa.Column("verification_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_agent_plans"),
    )
    op.create_index(
        "ix_agent_plans_owner_status_updated",
        "agent_plans",
        ["owner_id", "status", "updated_at"],
    )
    op.create_index("ix_agent_plans_trace_id", "agent_plans", ["trace_id"])
    op.add_column("logs", sa.Column("plan_id", sa.Text(), nullable=True))
    op.add_column("logs", sa.Column("plan_status", sa.Text(), nullable=True))
    op.create_index("ix_logs_plan_id", "logs", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_logs_plan_id", table_name="logs")
    op.drop_column("logs", "plan_status")
    op.drop_column("logs", "plan_id")
    op.drop_index("ix_agent_plans_trace_id", table_name="agent_plans")
    op.drop_index("ix_agent_plans_owner_status_updated", table_name="agent_plans")
    op.drop_table("agent_plans")
