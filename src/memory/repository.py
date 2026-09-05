from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.memory.models import Conversation, Log, Message


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
    out: list[dict[str, Any]] = []
    expected_tool_ids: set[str] | None = None

    for msg in msgs:
        role = msg.get("role")
        if role == "user":
            expected_tool_ids = None
            out.append(msg)
            continue
        if role == "assistant":
            out.append(msg)
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                expected_tool_ids = {
                    tc["id"]
                    for tc in tool_calls
                    if isinstance(tc, dict) and tc.get("type") == "function" and tc.get("id")
                }
            else:
                expected_tool_ids = None
            continue
        if role == "tool":
            tool_id = msg.get("tool_call_id") or ""
            if tool_id and expected_tool_ids and tool_id in expected_tool_ids:
                out.append(msg)
                expected_tool_ids.discard(tool_id)
                if not expected_tool_ids:
                    expected_tool_ids = None

    while out:
        last = out[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            out.pop()
            continue
        break
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
) -> None:
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
            session.add(message_to_insert(conv.id, msg, seq))
            seq += 1
        session.add(
            Log(
                channel_id=channel_id,
                slack_user_id=slack_user_id,
                user_message=user_message,
                agent_output=final_text,
                tools_called=tools_used,
                iterations=iterations,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=success,
                error_message=error_message,
            )
        )
        await session.commit()
