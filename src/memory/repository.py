import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.connections.redact import redact_obj, redact_secrets
from src.database import async_session_factory
from src.memory.models import Conversation, Log, MemoryItem, Message

MEMORY_KINDS = frozenset({"fact", "preference", "principle", "goal", "context"})
MEMORY_ACTIVE = "active"
MEMORY_ARCHIVED = "archived"
MAX_MEMORY_CONTENT_CHARS = 2_000
MAX_MEMORY_KEY_CHARS = 120
MAX_MEMORY_SOURCE_CHARS = 80
MAX_MEMORY_RESULTS = 8
_MEMORY_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "and",
        "did",
        "do",
        "does",
        "for",
        "how",
        "i",
        "me",
        "my",
        "of",
        "on",
        "our",
        "previously",
        "remember",
        "the",
        "think",
        "time",
        "what",
        "we",
        "were",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _memory_owner(owner_id: object) -> str:
    owner = str(owner_id or "").strip()
    if not owner:
        raise ValueError("owner_id is required")
    return owner


def _memory_kind(raw: object) -> str:
    kind = str(raw or "").strip().lower()
    if kind not in MEMORY_KINDS:
        allowed = ", ".join(sorted(MEMORY_KINDS))
        raise ValueError(f"kind must be one of: {allowed}")
    return kind


def _memory_key(raw: object) -> str:
    key = " ".join(str(raw or "").strip().lower().split())
    key = key.strip(" .,:;-")
    if not key:
        raise ValueError("key is required")
    return key[:MAX_MEMORY_KEY_CHARS]


def _memory_content(raw: object) -> str:
    content = redact_secrets(str(raw or "").strip())
    if not content:
        raise ValueError("content is required")
    if len(content) <= MAX_MEMORY_CONTENT_CHARS:
        return content
    marker = "\n[truncated]"
    return content[: MAX_MEMORY_CONTENT_CHARS - len(marker)].rstrip() + marker


def _memory_source(raw: object) -> str | None:
    if raw is None:
        return None
    source = redact_secrets(str(raw).strip())
    return source[:MAX_MEMORY_SOURCE_CHARS] or None


def _memory_confidence(raw: object) -> int:
    if raw is None or raw == "":
        return 100
    try:
        confidence = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be an integer from 0 to 100") from exc
    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be an integer from 0 to 100")
    return confidence


def _memory_terms(query: object) -> list[str]:
    text = str(query or "").lower()[:500]
    words = re.findall(r"[a-z0-9][a-z0-9_./-]*", text)
    return [word for word in words if len(word) > 1 and word not in _MEMORY_STOPWORDS][:12]


def memory_to_dict(row: MemoryItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "key": row.key,
        "content": row.content[:MAX_MEMORY_CONTENT_CHARS],
        "source": row.source,
        "source_trace_id": row.source_trace_id,
        "status": row.status,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_recalled_at": (row.last_recalled_at.isoformat() if row.last_recalled_at else None),
    }


async def upsert_memory(
    owner_id: str,
    *,
    kind: str,
    key: str,
    content: str,
    source: str | None = None,
    source_trace_id: str | None = None,
    confidence: int | None = None,
) -> dict[str, Any]:
    owner = _memory_owner(owner_id)
    normalized_kind = _memory_kind(kind)
    normalized_key = _memory_key(key)
    normalized_content = _memory_content(content)
    normalized_source = _memory_source(source)
    normalized_confidence = _memory_confidence(confidence)
    trace_id = str(source_trace_id or "").strip()[:120] or None
    now = _utcnow()
    async with async_session_factory() as session:
        row = await session.scalar(
            select(MemoryItem).where(
                MemoryItem.owner_id == owner,
                MemoryItem.kind == normalized_kind,
                MemoryItem.key == normalized_key,
            )
        )
        if row is None:
            row = MemoryItem(
                owner_id=owner,
                kind=normalized_kind,
                key=normalized_key,
                content=normalized_content,
                source=normalized_source,
                source_trace_id=trace_id,
                status=MEMORY_ACTIVE,
                confidence=normalized_confidence,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.content = normalized_content
            row.source = normalized_source or row.source
            row.source_trace_id = trace_id or row.source_trace_id
            row.status = MEMORY_ACTIVE
            row.confidence = normalized_confidence
            row.updated_at = now
        await session.commit()
        await session.refresh(row)
        return memory_to_dict(row)


async def search_memory(
    owner_id: str,
    query: str,
    *,
    limit: int = MAX_MEMORY_RESULTS,
) -> list[dict[str, Any]]:
    owner = _memory_owner(owner_id)
    try:
        requested_limit = max(1, min(int(limit), MAX_MEMORY_RESULTS))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    terms = _memory_terms(query)
    query_key = " ".join(str(query or "").lower().split())[:MAX_MEMORY_KEY_CHARS]
    candidate_limit = min(max(requested_limit * 6, 24), 100)
    async with async_session_factory() as session:
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.owner_id == owner, MemoryItem.status == MEMORY_ACTIVE)
            .order_by(MemoryItem.updated_at.desc())
            .limit(candidate_limit)
        )
        if terms:
            term_filters = [
                or_(
                    MemoryItem.key.ilike(f"%{term}%"),
                    MemoryItem.content.ilike(f"%{term}%"),
                )
                for term in terms
            ]
            stmt = stmt.where(or_(*term_filters))
        rows = list((await session.scalars(stmt)).all())

        def score(row: MemoryItem) -> tuple[int, int, datetime]:
            row_key = row.key.lower()
            key_score = 0
            if query_key and row_key == query_key:
                key_score = 100
            elif query_key and query_key in row_key:
                key_score = 50
            term_score = sum(
                (3 if term in row_key else 0) + (1 if term in row.content.lower() else 0)
                for term in terms
            )
            return key_score, term_score, row.updated_at or datetime.min

        rows.sort(key=score, reverse=True)
        selected = rows[:requested_limit]
        if selected:
            recalled_at = _utcnow()
            for row in selected:
                row.last_recalled_at = recalled_at
            await session.commit()
        return [memory_to_dict(row) for row in selected]


async def archive_memory(owner_id: str, memory_id: str) -> dict[str, Any]:
    owner = _memory_owner(owner_id)
    try:
        parsed_id = UUID(str(memory_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("memory_id must be a valid memory id") from exc
    async with async_session_factory() as session:
        row = await session.scalar(
            select(MemoryItem).where(
                MemoryItem.id == parsed_id,
                MemoryItem.owner_id == owner,
            )
        )
        if row is None:
            raise ValueError("memory item not found")
        row.status = MEMORY_ARCHIVED
        row.updated_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return memory_to_dict(row)


def row_to_param(row: Message) -> dict[str, Any]:
    if row.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": row.tool_call_id or "",
            "content": row.content or "",
        }
    if row.role == "assistant":
        if row.tool_calls:
            return {
                "role": "assistant",
                "content": row.content,
                "tool_calls": row.tool_calls,
            }
        return {"role": "assistant", "content": row.content}
    return {"role": "user", "content": row.content or ""}


def message_to_insert(conversation_id: Any, msg: dict[str, Any], sort_seq: int) -> Message:
    role = msg.get("role")
    if role == "tool":
        content = msg.get("content")
        if not isinstance(content, str):
            content = str(content)
        return Message(
            conversation_id=conversation_id,
            role="tool",
            content=content,
            tool_call_id=msg.get("tool_call_id"),
            sort_seq=sort_seq,
        )
    if role == "assistant":
        raw = msg.get("content")
        text: str | None = None
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, list):
            text = "".join(
                part.get("text", "") if isinstance(part, dict) and "text" in part else str(part)
                for part in raw
            )
        return Message(
            conversation_id=conversation_id,
            role="assistant",
            content=text,
            tool_calls=msg.get("tool_calls"),
            sort_seq=sort_seq,
        )
    if role == "user":
        raw = msg.get("content")
        if isinstance(raw, str):
            content = raw
        elif isinstance(raw, list):
            parts: list[str] = []
            for part in raw:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif part.get("type") == "image_url":
                    parts.append("[image]")
            content = " ".join(p for p in parts if p).strip() or "[image]"
        else:
            content = ""
        return Message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            sort_seq=sort_seq,
        )
    raise ValueError(f"Cannot persist message role: {role}")


def sanitize_tool_history(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop orphaned tool messages and incomplete assistant tool-call groups."""

    out: list[dict[str, Any]] = []
    expected_tool_ids: set[str] | None = None
    pending_start: int | None = None

    def discard_pending() -> None:
        nonlocal pending_start, expected_tool_ids
        if pending_start is not None:
            del out[pending_start:]
        pending_start = None
        expected_tool_ids = None

    for msg in msgs:
        role = msg.get("role")
        if role == "user":
            discard_pending()
            out.append(msg)
            continue
        if role == "assistant":
            discard_pending()
            pending_start = len(out)
            out.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                expected_tool_ids = {
                    tc["id"]
                    for tc in tool_calls
                    if isinstance(tc, dict) and tc.get("type") == "function" and tc.get("id")
                }
                if not expected_tool_ids:
                    discard_pending()
            else:
                expected_tool_ids = None
                pending_start = None
            continue
        if role == "tool":
            tool_id = msg.get("tool_call_id") or ""
            if tool_id and expected_tool_ids and tool_id in expected_tool_ids:
                out.append(msg)
                expected_tool_ids.discard(tool_id)
                if not expected_tool_ids:
                    pending_start = None
                    expected_tool_ids = None

    discard_pending()
    return out


async def _ensure_conversation(
    session: AsyncSession, channel_id: str, slack_user_id: str
) -> Conversation:
    result = await session.execute(
        select(Conversation).where(Conversation.channel_id == channel_id).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.last_active_at = _utcnow()
        existing.slack_user_id = slack_user_id
        await session.flush()
        return existing
    created = Conversation(channel_id=channel_id, slack_user_id=slack_user_id)
    session.add(created)
    await session.flush()
    return created


async def load_history(channel_id: str, limit: int) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.channel_id == channel_id).limit(1)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return []
        rows = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.sort_seq.desc(), Message.created_at.desc(), Message.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        raw = [row_to_param(row) for row in reversed(rows)]
        return sanitize_tool_history(raw)


async def persist_turn(
    *,
    channel_id: str,
    slack_user_id: str,
    user_message: str,
    final_text: str,
    messages: list[dict[str, Any]],
    history_len: int,
    tools_used: list[str],
    iterations: int,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    success: bool = True,
    error_message: str | None = None,
    trace_id: str | None = None,
    prompt_version: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    context_chars: int | None = None,
    available_tools: int | None = None,
    tool_outcomes: list[dict[str, Any]] | None = None,
    memory_hits: int | None = None,
    memory_chars: int | None = None,
    plan_id: str | None = None,
    plan_status: str | None = None,
) -> None:
    user_message = redact_secrets(user_message)
    final_text = redact_secrets(final_text)
    if error_message:
        error_message = redact_secrets(error_message)
    safe_tool_outcomes = redact_obj(tool_outcomes or [])
    async with async_session_factory() as session:
        conv = await _ensure_conversation(session, channel_id, slack_user_id)
        tail = messages[1 + history_len :]
        max_seq = await session.scalar(
            select(func.max(Message.sort_seq)).where(Message.conversation_id == conv.id)
        )
        seq = (max_seq if max_seq is not None else -1) + 1
        for msg in tail:
            if msg.get("role") == "system":
                continue
            redacted = redact_obj(msg)
            payload = redacted if isinstance(redacted, dict) else msg
            session.add(message_to_insert(conv.id, payload, seq))
            seq += 1
        session.add(
            Log(
                trace_id=trace_id,
                channel_id=channel_id,
                slack_user_id=slack_user_id,
                user_message=user_message,
                agent_output=final_text,
                tools_called=tools_used,
                iterations=iterations,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                prompt_version=prompt_version,
                provider=provider,
                model=model,
                context_chars=context_chars,
                available_tools=available_tools,
                memory_hits=memory_hits,
                memory_chars=memory_chars,
                plan_id=plan_id,
                plan_status=plan_status,
                tool_outcomes=safe_tool_outcomes,
                success=success,
                error_message=error_message,
            )
        )
        await session.commit()
