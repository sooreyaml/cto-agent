from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx

from src.agent.codex_oauth import request_headers, resolve_credential
from src.config import get_settings
from src.exceptions import ConfigError

CODEX_BASE_DEFAULT = "https://chatgpt.com/backend-api/codex"


@dataclass
class ToolFunction:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    function: ToolFunction
    type: str = "function"


@dataclass
class ChatMessage:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in self.tool_calls
            ]
        if exclude_none:
            return {key: value for key, value in data.items() if value is not None}
        return data


def _text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(part.get("text") or ""))
                elif "text" in part:
                    parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(content)


def _user_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, list):
        parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = str(part.get("type") or "")
            if ptype in {"text", "input_text"}:
                parts.append({"type": "input_text", "text": str(part.get("text") or "")})
            elif ptype in {"image_url", "input_image"}:
                image = part.get("image_url")
                url = image.get("url") if isinstance(image, dict) else image
                if url:
                    parts.append({"type": "input_image", "image_url": str(url)})
        return parts or _text_from_content(content)
    return _text_from_content(content)


def _responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    converted: list[dict[str, Any]] = []
    for item in tools or []:
        fn = item.get("function") if isinstance(item, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        converted.append(
            {
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "strict": False,
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted or None


def chat_messages_to_responses(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions_parts: list[str] = []
    items: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "system":
            text = _text_from_content(msg.get("content")).strip()
            if text:
                instructions_parts.append(text)
            continue
        if role == "tool":
            call_id = str(msg.get("tool_call_id") or "").strip()
            if call_id:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": _text_from_content(msg.get("content")),
                    }
                )
            continue
        if role == "user":
            items.append({"role": "user", "content": _user_content(msg.get("content"))})
            continue
        if role != "assistant":
            continue
        text = _text_from_content(msg.get("content"))
        tool_calls = msg.get("tool_calls") or []
        if text or not tool_calls:
            items.append({"role": "assistant", "content": text})
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or "").strip()
            if not name:
                continue
            call_id = str(tc.get("id") or tc.get("call_id") or "").strip()
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id or f"fc_{name}",
                    "name": name,
                    "arguments": str(fn.get("arguments") or "{}"),
                }
            )
    return "\n\n".join(instructions_parts), items


def _parse_sse_block(block: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    payload = "\n".join(data_lines).strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _item_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                chunks.append(str(part.get("text") or ""))
        return "".join(chunks)
    return str(item.get("text") or "")


def assemble_from_events(
    events: list[dict[str, Any]],
) -> tuple[ChatMessage, SimpleNamespace | None]:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    usage = None
    for event in events:
        etype = str(event.get("type") or "")
        if etype == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                text_parts.append(delta)
            continue
        if etype in {"response.output_item.done", "response.output_item.added"}:
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "message":
                extracted = _item_text(item)
                if extracted:
                    text_parts = [extracted]
            elif item_type == "function_call":
                name = str(item.get("name") or "").strip()
                call_id = str(item.get("call_id") or item.get("id") or "").strip()
                if name:
                    tool_calls.append(
                        ToolCall(
                            id=call_id or f"call_{name}",
                            function=ToolFunction(
                                name=name,
                                arguments=str(item.get("arguments") or "{}"),
                            ),
                        )
                    )
            continue
        if etype == "response.completed":
            response = event.get("response")
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                if isinstance(raw_usage, dict):
                    usage = SimpleNamespace(
                        prompt_tokens=int(
                            raw_usage.get("input_tokens") or raw_usage.get("prompt_tokens") or 0
                        ),
                        completion_tokens=int(
                            raw_usage.get("output_tokens")
                            or raw_usage.get("completion_tokens")
                            or 0
                        ),
                    )
    message = ChatMessage(
        content="".join(text_parts) or None,
        tool_calls=tool_calls or None,
    )
    return message, usage


class CodexCompletions:
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        messages = kwargs.get("messages")
        if not isinstance(messages, list):
            raise ConfigError("Codex chat completion requires messages")
        instructions, items = chat_messages_to_responses(messages)
        if not items:
            raise ConfigError("Codex chat completion has no user/assistant input")
        settings = get_settings()
        body: dict[str, Any] = {
            "model": str(kwargs.get("model") or settings.CODEX_MODEL),
            "instructions": instructions or "You are CTO Agent.",
            "input": items,
            "store": False,
            "stream": True,
        }
        tools = _responses_tools(kwargs.get("tools"))
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice") or "auto"
        # ChatGPT Codex OAuth rejects max_output_tokens / max_tokens.

        cred = await resolve_credential()
        base = settings.CODEX_BASE_URL.rstrip("/")
        url = f"{base}/responses"
        events = await _stream_events(url, request_headers(cred), body)
        message, usage = assemble_from_events(events)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class CodexChat:
    def __init__(self) -> None:
        self.completions = CodexCompletions()


class CodexLLM:
    def __init__(self) -> None:
        self.chat = CodexChat()


async def _post_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> list[dict[str, Any]] | None:
    async with client.stream("POST", url, headers=headers, json=body) as res:
        if res.status_code == 401:
            await res.aread()
            return None
        if res.status_code >= 400:
            detail = (await res.aread()).decode("utf-8", errors="replace")[:500]
            raise ConfigError(f"Codex Responses failed ({res.status_code}): {detail}")
        return await _read_sse(res)


async def _stream_events(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> list[dict[str, Any]]:
    timeout = httpx.Timeout(120.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        events = await _post_stream(client, url, headers, body)
        if events is not None:
            return events
        cred = await resolve_credential(force_refresh=True)
        events = await _post_stream(client, url, request_headers(cred), body)
        if events is None:
            raise ConfigError(
                "Codex Responses unauthorized after token refresh. Say connect openai."
            )
        return events


async def _read_sse(res: httpx.Response) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    buffer = ""
    async for chunk in res.aiter_text():
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            event = _parse_sse_block(block)
            if event:
                events.append(event)
    if buffer.strip():
        event = _parse_sse_block(buffer)
        if event:
            events.append(event)
    return events
