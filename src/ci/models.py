import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


class CIIncident(Base):
    """Owner-scoped, metadata-only state for a GitHub Actions incident."""

    __tablename__ = "ci_incidents"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "external_id",
            name="uq_ci_incidents_owner_external_id",
        ),
        Index("ix_ci_incidents_owner_status_seen", "owner_id", "status", "last_seen_at"),
        Index("ix_ci_incidents_owner_repo_status", "owner_id", "repository", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    repository: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_name: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str | None] = mapped_column(Text)
    run_number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    url: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
