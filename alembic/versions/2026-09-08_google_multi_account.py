"""allow multiple Google accounts per owner

Revision ID: 20260908_0006
Revises: 20260908_0005
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0006"
down_revision: str | None = "20260908_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_google_accounts_slack_user_id", "google_accounts", type_="unique")
    op.add_column("google_accounts", sa.Column("label", sa.Text(), nullable=True))
    op.add_column(
        "google_accounts",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "ix_google_accounts_email_lower",
        "google_accounts",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.execute(
        sa.text(
            """
            UPDATE google_accounts
            SET is_default = true
            WHERE id = (SELECT id FROM google_accounts ORDER BY created_at ASC LIMIT 1)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_google_accounts_email_lower", table_name="google_accounts")
    op.drop_column("google_accounts", "is_default")
    op.drop_column("google_accounts", "label")
    op.create_unique_constraint(
        "uq_google_accounts_slack_user_id", "google_accounts", ["slack_user_id"]
    )
