import json
from types import SimpleNamespace

import pytest
from src.agent import loop as agent_loop
from src.agent.context import bound_history, bound_text, serialize_tool_result
from src.agent.registry import all_tools
from src.agent.routing import tool_names_for_message
from src.agent.trace import AgentTrace
from src.agent.validation import parse_tool_arguments
from src.memory.context import MemoryContext


def _tool_call(call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "work_list", "arguments": "{}"},
    }


def test_router_selects_relevant_capability_and_universal_connection_tools() -> None:
    selected = set(tool_names_for_message("show me the latest GitHub CI failures"))

    assert "github_get_branch_ci_status" in selected
    assert "connections_catalog" in selected
    assert "gmail_search_messages" not in selected
    assert "calendar_list_events" not in selected


def test_router_handles_multiple_capabilities_and_ambiguous_text() -> None:
    selected = set(tool_names_for_message("compare the calendar and email for tomorrow"))
    assert "calendar_list_events" in selected
    assert "gmail_search_messages" in selected

    # Ambiguous turns retain the existing all-tools behavior instead of making
    # a guessed route silently remove a capability.
    assert tool_names_for_message("hello") == list(all_tools)


def test_router_does_not_treat_pr_as_github_inside_priority() -> None:
    selected = set(tool_names_for_message("what are my top priorities?"))
    assert "work_list" in selected
    assert "github_list_repos" not in selected


def test_router_exposes_memory_tools_for_explicit_recall() -> None:
    selected = set(tool_names_for_message("what did we decide about deployment previously?"))

    assert "memory_search" in selected
    assert "memory_save" in selected
    assert "memory_archive" in selected


def test_bound_history_keeps_complete_tool_call_groups() -> None:
    history = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": None, "tool_calls": [_tool_call()]},
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
        {"role": "user", "content": "newer"},
        {"role": "assistant", "content": "done"},
    ]

    bounded = bound_history(history, max_messages=3)

    assert bounded == [
        {"role": "user", "content": "newer"},
        {"role": "assistant", "content": "done"},
    ]


def test_bound_history_drops_partial_tool_groups_from_char_budget() -> None:
    history = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": None, "tool_calls": [_tool_call()]},
        {"role": "tool", "tool_call_id": "call-1", "content": "x" * 200},
        {"role": "user", "content": "newer"},
    ]

    bounded = bound_history(history, max_chars=180)

    assert all(message.get("role") != "tool" for message in bounded)
    assert all(not message.get("tool_calls") for message in bounded)
    assert bounded[-1] == {"role": "user", "content": "newer"}


def test_bound_history_never_keeps_one_message_over_the_char_budget() -> None:
    bounded = bound_history(
        [{"role": "user", "content": "x" * 500}],
        max_chars=100,
    )

    assert bounded == []


def test_context_and_tool_result_budgets_are_explicit() -> None:
    bounded_text = bound_text("x" * 100, max_chars=40)
    assert bounded_text.endswith("[context truncated]")
    assert len(bounded_text) <= 40

    encoded = serialize_tool_result({"items": ["x"] * 100}, max_chars=80)
    parsed = json.loads(encoded)
    assert parsed["truncated"] is True
    assert "narrower result" in parsed["message"]

    bounded = serialize_tool_result({"items": ["x"] * 10000})
    assert len(bounded) <= 12_000


def test_tool_argument_validation_rejects_malformed_or_unknown_fields() -> None:
    spec = {
        "function": {
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        }
    }

    assert parse_tool_arguments(spec, '{"query": "ci"}') == {"query": "ci"}
    with pytest.raises(ValueError, match="missing required"):
        parse_tool_arguments(spec, "{}")
    with pytest.raises(ValueError, match="unknown tool argument"):
        parse_tool_arguments(spec, '{"query": "ci", "extra": true}')
    with pytest.raises(ValueError, match="valid JSON"):
        parse_tool_arguments(spec, "not-json")


def test_trace_emits_metadata_without_payloads() -> None:
    events: list[dict] = []
    trace = AgentTrace(trace_id="trace-test", sink=events.append)
    trace.emit("tool_completed", name="work_list", ok=True, result={"secret": "no"})

    assert events[0]["trace_id"] == "trace-test"
    assert events[0]["name"] == "work_list"
    assert "result" not in events[0]


@pytest.mark.asyncio
async def test_run_agent_traces_and_persists_invalid_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMessage:
        def __init__(self, *, content: str | None = None, tool_calls: list | None = None):
            self.content = content
            self.tool_calls = tool_calls

        def model_dump(self, *, exclude_none: bool = True) -> dict:
            dumped = {"role": "assistant", "content": self.content}
            if self.tool_calls:
                dumped["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": call.type,
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in self.tool_calls
                ]
            return {key: value for key, value in dumped.items() if value is not None}

    malformed_call = SimpleNamespace(
        id="call-invalid",
        type="function",
        function=SimpleNamespace(name="work_list", arguments='{"unexpected": true}'),
    )
    responses = iter(
        [
            SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
                choices=[SimpleNamespace(message=FakeMessage(tool_calls=[malformed_call]))],
            ),
            SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5),
                choices=[
                    SimpleNamespace(message=FakeMessage(content="I need a valid task query."))
                ],
            ),
        ]
    )
    persisted: dict = {}
    llm_calls: list[dict] = []

    async def fake_create(**kwargs: object) -> object:
        llm_calls.append(kwargs)
        return next(responses)

    async def fake_persist(**kwargs: object) -> None:
        persisted.update(kwargs)

    async def fake_memory(*_args: object, **_kwargs: object) -> MemoryContext:
        return MemoryContext(
            text="Relevant durable memory (evidence):\n- [preference] timezone: Europe/London",
            hits=1,
            chars=88,
        )

    monkeypatch.setattr(agent_loop.llm.chat.completions, "create", fake_create)
    monkeypatch.setattr(agent_loop, "load_history", lambda *_args: _empty_history())
    monkeypatch.setattr(agent_loop, "load_work_snapshot", lambda: _empty_snapshot())
    monkeypatch.setattr(agent_loop, "load_memory_context", fake_memory)
    monkeypatch.setattr(agent_loop, "persist_turn", fake_persist)
    monkeypatch.setattr(agent_loop, "current_model", lambda: "test-model")

    events: list[dict] = []
    result = await agent_loop.run_agent(
        channel_id="channel-test",
        slack_user_id="user-test",
        user_message="show my tasks",
        trace_sink=events.append,
    )

    assert result["text"] == "I need a valid task query."
    assert result["traceId"] == persisted["trace_id"]
    assert "Europe/London" in llm_calls[0]["messages"][0]["content"]
    assert {event["event"] for event in events} >= {
        "run_started",
        "llm_requested",
        "tool_started",
        "tool_completed",
        "run_completed",
    }
    assert persisted["available_tools"] < len(all_tools)
    assert persisted["memory_hits"] == 1
    assert persisted["tool_outcomes"][0]["ok"] is False


async def _empty_history() -> list[dict]:
    return []


async def _empty_snapshot() -> str:
    return ""
