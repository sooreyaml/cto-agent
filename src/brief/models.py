import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


class BriefRun(Base):
    """Metadata-only audit record for one daily brief attempt."""

    __tablename__ = "brief_runs"
    __table_args__ = (Index("ix_brief_runs_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    run_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    source_health: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    action_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    evidence_urls: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    render_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    delivery_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    error_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
