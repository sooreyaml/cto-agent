import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    channel_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slack_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[Any | None] = mapped_column(JSONB)
    tool_call_id: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(Text)
    sort_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trace_id: Mapped[str | None] = mapped_column(Text)
    channel_id: Mapped[str | None] = mapped_column(Text)
    slack_user_id: Mapped[str | None] = mapped_column(Text)
    user_message: Mapped[str | None] = mapped_column(Text)
    agent_output: Mapped[str | None] = mapped_column(Text)
    tools_called: Mapped[Any | None] = mapped_column(JSONB)
    iterations: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    context_chars: Mapped[int | None] = mapped_column(Integer)
    available_tools: Mapped[int | None] = mapped_column(Integer)
    memory_hits: Mapped[int | None] = mapped_column(Integer)
    memory_chars: Mapped[int | None] = mapped_column(Integer)
    plan_id: Mapped[str | None] = mapped_column(Text)
    plan_status: Mapped[str | None] = mapped_column(Text)
    tool_outcomes: Mapped[Any | None] = mapped_column(JSONB)
    cost_usd: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class AgentPlan(Base):
    """Owner-scoped execution contract and metadata-only evidence ledger."""

    __tablename__ = "agent_plans"
    __table_args__ = (
        Index("ix_agent_plans_owner_status_updated", "owner_id", "status", "updated_at"),
        Index("ix_agent_plans_trace_id", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    acceptance_criteria: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    steps: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'planned'"))
    verification_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class MemoryItem(Base):
    """Owner-scoped durable narrative memory kept separate from operational work state."""

    __tablename__ = "memory_items"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "kind",
            "key",
            name="uq_memory_items_owner_kind_key",
        ),
        Index(
            "ix_memory_items_owner_status_updated",
            "owner_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_memory_items_owner_kind_key",
            "owner_id",
            "kind",
            "key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    source_trace_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    confidence: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    last_recalled_at: Mapped[datetime | None] = mapped_column(DateTime)
