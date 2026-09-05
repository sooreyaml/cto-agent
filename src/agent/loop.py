import json
import logging
import time
from typing import Any

from src.agent.llm import MODEL, llm
from src.agent.prompt import build_system_prompt
from src.agent.registry import tool_registry, tool_specs
from src.memory.repository import load_history, persist_turn

logger = logging.getLogger(__name__)
MAX_ITERATIONS = 10


async def run_agent(
    *,
    channel_id: str,
    slack_user_id: str,
    user_message: str,
    image_data_urls: list[str] | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    tools_used: list[str] = []
    input_tokens = 0
    output_tokens = 0

    history = await load_history(channel_id, 24)
    history_len = len(history)

    text_part = user_message.strip() or "(User sent an image with no caption.)"
    if image_data_urls:
        user_msg: dict[str, Any] = {
            "role": "user",
            "content": [
                {"type": "text", "text": text_part},
                *[{"type": "image_url", "image_url": {"url": url}} for url in image_data_urls],
            ],
        }
    else:
        user_msg = {"role": "user", "content": user_message}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt()},
        *history,
        user_msg,
    ]

    final_text = ""
    iterations = 0

    for _ in range(MAX_ITERATIONS):
        iterations += 1
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        if tool_specs:
            kwargs["tools"] = tool_specs
            kwargs["tool_choice"] = "auto"
        response = await llm.chat.completions.create(**kwargs)

        if response.usage:
            input_tokens += response.usage.prompt_tokens or 0
            output_tokens += response.usage.completion_tokens or 0

        msg = response.choices[0].message if response.choices else None
        if not msg:
            break

        dumped = msg.model_dump(exclude_none=True)
        messages.append(dumped)

        if not msg.tool_calls:
            final_text = msg.content or ""
            break

        tool_results = []
        for tc in msg.tool_calls:
            if getattr(tc, "type", None) != "function":
                tool_results.append(
                    {"tool_call_id": tc.id, "error": f"Unsupported tool call type: {tc.type}"}
                )
                continue
            handler = tool_registry.get(tc.function.name)
            if not handler:
                tool_results.append(
                    {"tool_call_id": tc.id, "error": f"Unknown tool: {tc.function.name}"}
                )
                continue
            tools_used.append(tc.function.name)
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = await handler(args)
                tool_results.append({"tool_call_id": tc.id, "result": result})
            except Exception as err:
                logger.exception("tool failed tool=%s", tc.function.name)
                tool_results.append({"tool_call_id": tc.id, "error": str(err)})

        for result in tool_results:
            content = (
                json.dumps({"error": result["error"]})
                if "error" in result
                else json.dumps(result.get("result"), default=str)
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": content,
                }
            )

    if not final_text:
        final_text = "I hit the max tool-call limit without finishing. Try rephrasing."

    if image_data_urls:
        log_user_summary = (
            f"{user_message.strip() or '[no text]'} [{len(image_data_urls)} image(s)]"
        )
    else:
        log_user_summary = user_message

    try:
        await persist_turn(
            channel_id=channel_id,
            slack_user_id=slack_user_id,
            user_message=log_user_summary,
            final_text=final_text,
            messages=messages,
            history_len=history_len,
            tools_used=tools_used,
            iterations=iterations,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except Exception:
        logger.exception("persistTurn failed")

    return {"text": final_text, "toolsUsed": tools_used, "iterations": iterations}
