import base64
import json

import httpx
import openai
import pytest
from src.agent.codex_oauth import CodexCredential, account_id_from_jwt
from src.agent.codex_responses import assemble_from_events, chat_messages_to_responses
from src.agent.llm import llm, should_fallback_to_codex


def _jwt(account_id: str = "acc_test") -> str:
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    return f"header.{payload}.sig"


def test_account_id_from_jwt() -> None:
    assert account_id_from_jwt(_jwt("acc-xyz")) == "acc-xyz"


def test_chat_messages_to_responses_tools() -> None:
    instructions, items = chat_messages_to_responses(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "work_list", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
        ]
    )
    assert instructions == "Be brief."
    assert items[0] == {"role": "user", "content": "hi"}
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"
    assert items[2]["type"] == "function_call_output"
    assert items[2]["call_id"] == "call_1"


def test_assemble_from_events_text_and_tools() -> None:
    message, usage = assemble_from_events(
        [
            {"type": "response.output_text.delta", "delta": "Hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Hello"}],
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_9",
                    "name": "work_list",
                    "arguments": "{}",
                },
            },
            {
                "type": "response.completed",
                "response": {"usage": {"input_tokens": 3, "output_tokens": 2}},
            },
        ]
    )
    assert message.content == "Hello"
    assert message.tool_calls is not None
    assert message.tool_calls[0].function.name == "work_list"
    assert usage is not None
    assert usage.prompt_tokens == 3
    assert usage.completion_tokens == 2


def test_should_fallback_on_rate_limit() -> None:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, request=request)
    err = openai.RateLimitError("slow", response=response, body=None)
    assert should_fallback_to_codex(err) is True
    assert should_fallback_to_codex(ValueError("bad schema")) is False


@pytest.mark.asyncio
async def test_falls_back_to_codex_when_openrouter_rate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(**kwargs: object) -> object:
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(429, request=request)
        raise openai.RateLimitError("slow", response=response, body=None)

    async def ok(**kwargs: object) -> dict[str, object]:
        assert kwargs["model"] == "gpt-5.4"
        return {"ok": True, "via": "codex"}

    async def cred() -> CodexCredential:
        return CodexCredential("access-token-value", "refresh-token-value", 9e12, "acc")

    monkeypatch.setattr(llm.chat.completions._owner._router().chat.completions, "create", fail)
    monkeypatch.setattr(llm._codex.chat.completions, "create", ok)
    monkeypatch.setattr("src.agent.llm.load_credential", cred)
    result = await llm.chat.completions.create(
        model="anthropic/claude-sonnet-4.6",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result == {"ok": True, "via": "codex"}


@pytest.mark.asyncio
async def test_does_not_fallback_without_codex_login(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(**kwargs: object) -> object:
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(429, request=request)
        raise openai.RateLimitError("slow", response=response, body=None)

    async def missing() -> None:
        return None

    monkeypatch.setattr(llm.chat.completions._owner._router().chat.completions, "create", fail)
    monkeypatch.setattr("src.agent.llm.load_credential", missing)
    with pytest.raises(openai.RateLimitError):
        await llm.chat.completions.create(
            model="anthropic/claude-sonnet-4.6",
            messages=[{"role": "user", "content": "hi"}],
        )
