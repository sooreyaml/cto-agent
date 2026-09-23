"""persist CI incident and daily brief intelligence metadata

Revision ID: 20260923_0011
Revises: 20260923_0010
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0011"
down_revision: str | None = "20260923_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ci_incidents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("workflow_name", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("run_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("severity", sa.Text(), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("failure_streak", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ci_incidents"),
        sa.UniqueConstraint("owner_id", "external_id", name="uq_ci_incidents_owner_external_id"),
    )
    op.create_index(
        "ix_ci_incidents_owner_status_seen",
        "ci_incidents",
        ["owner_id", "status", "last_seen_at"],
    )
    op.create_index(
        "ix_ci_incidents_owner_repo_status",
        "ci_incidents",
        ["owner_id", "repository", "status"],
    )
    op.create_table(
        "brief_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("run_date", sa.DateTime(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("source_health", sa.JSON(), nullable=False),
        sa.Column("signal_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("action_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("evidence_urls", sa.JSON(), nullable=False),
        sa.Column("render_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("delivery_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_brief_runs"),
    )
    op.create_index("ix_brief_runs_owner_created", "brief_runs", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_brief_runs_owner_created", table_name="brief_runs")
    op.drop_table("brief_runs")
    op.drop_index("ix_ci_incidents_owner_repo_status", table_name="ci_incidents")
    op.drop_index("ix_ci_incidents_owner_status_seen", table_name="ci_incidents")
    op.drop_table("ci_incidents")
