import json
import logging
import time
from typing import Any

from src.agent.context import (
    MAX_HISTORY_MESSAGES,
    MAX_TOOL_RESULT_CHARS,
    MAX_WORK_CONTEXT_CHARS,
    bound_history,
    bound_text,
    serialize_tool_result,
)
from src.agent.llm import current_model, llm
from src.agent.planning import (
    PlanDraft,
    build_plan_draft,
    format_plan_context,
    is_complex_request,
    steps_for_status,
)
from src.agent.plans import append_agent_plan_evidence, create_agent_plan, update_agent_plan
from src.agent.policy import has_explicit_confirmation, requires_explicit_confirmation
from src.agent.prompt import PROMPT_VERSION, build_system_prompt
from src.agent.registry import all_tools, tool_registry
from src.agent.routing import matched_groups, tool_names_for_message
from src.agent.trace import AgentTrace, TraceSink
from src.agent.validation import parse_tool_arguments
from src.config import get_settings
from src.memory.context import (
    MemoryContext,
    load_memory_context,
    memory_execution_context,
    memory_query,
    memory_write_is_explicit,
)
from src.memory.repository import load_history, persist_turn
from src.work.snapshot import load_work_snapshot

logger = logging.getLogger(__name__)
MAX_ITERATIONS = 10


async def run_agent(
    *,
    channel_id: str,
    slack_user_id: str,
    user_message: str,
    image_data_urls: list[str] | None = None,
    surface: str = "discord",
    trace_sink: TraceSink | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    trace = AgentTrace(sink=trace_sink)
    tools_used: list[str] = []
    tool_outcomes: list[dict[str, Any]] = []
    input_tokens = 0
    output_tokens = 0
    settings = get_settings()
    provider = settings.LLM_PROVIDER
    tool_names = tool_names_for_message(user_message)
    selected_tool_specs = [all_tools[name]["spec"] for name in tool_names]
    groups = matched_groups(user_message)
    plan_draft: PlanDraft | None = (
        build_plan_draft(user_message) if is_complex_request(user_message) else None
    )
    plan_id: str | None = None
    plan_status: str | None = None

    try:
        raw_history = await load_history(channel_id, MAX_HISTORY_MESSAGES)
        history = bound_history(raw_history)
    except Exception:
        logger.exception("load_history failed; continuing without memory")
        history = []
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

    try:
        work_context = bound_text(
            await load_work_snapshot(),
            max_chars=MAX_WORK_CONTEXT_CHARS,
        )
    except Exception:
        logger.exception("load_work_snapshot failed")
        work_context = "Work board unavailable."

    try:
        memory = await load_memory_context(
            slack_user_id,
            memory_query(user_message, history),
        )
    except Exception:
        logger.exception("durable memory context failed; continuing without memory")
        memory = MemoryContext(text="", hits=0, chars=0)

    if plan_draft is not None:
        try:
            plan = await create_agent_plan(
                slack_user_id,
                channel_id=channel_id,
                trace_id=trace.trace_id,
                draft=plan_draft,
            )
            plan_id = str(plan["id"])
            plan_status = str(plan.get("status") or "planned")
        except Exception:
            # Planning is an observability and control layer; a database outage
            # must not make the existing provider-backed reply path unusable.
            logger.exception("create_agent_plan failed trace_id=%s", trace.trace_id)

    async def safe_plan_update(status: str, summary: str | None = None) -> None:
        nonlocal plan_status
        if plan_id is None or plan_draft is None:
            return
        plan_status = status
        try:
            updated = await update_agent_plan(
                plan_id,
                slack_user_id,
                channel_id=channel_id,
                status=status,
                steps=steps_for_status(plan_draft, status),
                verification_summary=summary,
            )
            if updated is not None:
                plan_status = str(updated.get("status") or status)
        except Exception:
            logger.exception(
                "update_agent_plan failed trace_id=%s plan_id=%s status=%s",
                trace.trace_id,
                plan_id,
                status,
            )

    async def record_tool_outcome(outcome: dict[str, Any]) -> None:
        tool_outcomes.append(outcome)
        trace.emit("tool_completed", **outcome)
        if plan_id is None:
            return
        try:
            await append_agent_plan_evidence(
                plan_id,
                slack_user_id,
                outcome,
                channel_id=channel_id,
            )
        except Exception:
            logger.exception(
                "append_agent_plan_evidence failed trace_id=%s plan_id=%s",
                trace.trace_id,
                plan_id,
            )

    if plan_id is not None:
        await safe_plan_update("executing")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                surface=surface,
                work_context=work_context,
                memory_context=memory.text,
                plan_context=format_plan_context(plan_draft),
            ),
        },
        *history,
        user_msg,
    ]

    context_chars = len(json.dumps(messages, default=str, ensure_ascii=False))
    trace.emit(
        "run_started",
        surface=surface,
        history_count=history_len,
        candidate_tools=len(tool_names),
        tool_names=",".join(tool_names),
        tool_groups=",".join(sorted(groups)) or "none",
        context_chars=context_chars,
        memory_hits=memory.hits,
        memory_chars=memory.chars,
        complexity="complex" if plan_draft is not None else "simple",
        plan_id=plan_id,
        plan_status=plan_status,
    )

    final_text = ""
    iterations = 0
    run_error: BaseException | None = None
    completed_with_text = False
    last_model: str | None = None

    for _ in range(MAX_ITERATIONS):
        iterations += 1
        model = current_model()
        last_model = model
        llm_started_at = time.monotonic()
        trace.emit(
            "llm_requested",
            iteration=iterations,
            model=model,
            available_tools=len(selected_tool_specs),
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        if selected_tool_specs:
            kwargs["tools"] = selected_tool_specs
            kwargs["tool_choice"] = "auto"
        try:
            response = await llm.chat.completions.create(**kwargs)
        except Exception as err:
            run_error = err
            trace.emit(
                "llm_failed",
                iteration=iterations,
                model=model,
                duration_ms=int((time.monotonic() - llm_started_at) * 1000),
                error_type=type(err).__name__,
            )
            break

        if response.usage:
            input_tokens += response.usage.prompt_tokens or 0
            output_tokens += response.usage.completion_tokens or 0
        trace.emit(
            "llm_completed",
            iteration=iterations,
            model=model,
            duration_ms=int((time.monotonic() - llm_started_at) * 1000),
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

        msg = response.choices[0].message if response.choices else None
        if not msg:
            run_error = RuntimeError("model returned no message")
            break

        dumped = msg.model_dump(exclude_none=True)
        messages.append(dumped)

        if not msg.tool_calls:
            final_text = msg.content or ""
            completed_with_text = bool(final_text.strip())
            break

        tool_results = []
        for tc in msg.tool_calls:
            tool_started_at = time.monotonic()
            call_id = str(getattr(tc, "id", "") or "")
            call_type = getattr(tc, "type", None)
            tool_name = str(getattr(getattr(tc, "function", None), "name", "") or "")
            trace.emit(
                "tool_started",
                iteration=iterations,
                call_id=call_id,
                name=tool_name,
            )
            if call_type != "function":
                error = f"Unsupported tool call type: {call_type}"
                tool_results.append({"tool_call_id": call_id, "error": error})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name or "unknown",
                    "ok": False,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(json.dumps({"error": error})),
                    "error_type": "UnsupportedToolCall",
                }
                await record_tool_outcome(outcome)
                continue
            handler = tool_registry.get(tool_name)
            if not handler:
                error = f"Unknown tool: {tool_name}"
                tool_results.append({"tool_call_id": call_id, "error": error})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name or "unknown",
                    "ok": False,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(json.dumps({"error": error})),
                    "error_type": "UnknownTool",
                }
                await record_tool_outcome(outcome)
                continue
            tools_used.append(tool_name)
            if tool_name in {"memory_save", "memory_archive"} and not memory_write_is_explicit(
                user_message,
                tool_name,
            ):
                error = (
                    "Durable memory changes require an explicit user request to remember, "
                    "store, forget, remove, or archive a memory."
                )
                tool_results.append({"tool_call_id": call_id, "error": error})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name,
                    "ok": False,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(json.dumps({"error": error})),
                    "error_type": "MemoryWriteNotExplicit",
                }
                await record_tool_outcome(outcome)
                continue
            if requires_explicit_confirmation(tool_name) and not has_explicit_confirmation(
                user_message,
                tool_name,
            ):
                error = (
                    f"{tool_name} requires an explicit confirmation in the current user turn. "
                    "Ask the user to confirm the exact action before retrying."
                )
                tool_results.append({"tool_call_id": call_id, "error": error})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name,
                    "ok": False,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(json.dumps({"error": error})),
                    "error_type": "ExplicitConfirmationRequired",
                }
                await record_tool_outcome(outcome)
                continue
            try:
                spec = all_tools[tool_name]["spec"]
                args = parse_tool_arguments(spec, tc.function.arguments)
                with memory_execution_context(slack_user_id, trace.trace_id):
                    result = await handler(args)
                tool_results.append({"tool_call_id": call_id, "result": result})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name,
                    "ok": True,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(
                        serialize_tool_result(result, max_chars=MAX_TOOL_RESULT_CHARS)
                    ),
                }
            except Exception as err:
                logger.exception("tool failed tool=%s", tool_name)
                tool_results.append({"tool_call_id": call_id, "error": str(err)})
                outcome = {
                    "call_id": call_id,
                    "name": tool_name,
                    "ok": False,
                    "duration_ms": int((time.monotonic() - tool_started_at) * 1000),
                    "result_chars": len(json.dumps({"error": str(err)})),
                    "error_type": type(err).__name__,
                }
            await record_tool_outcome(outcome)

        for result in tool_results:
            content = serialize_tool_result(
                {"error": result["error"]} if "error" in result else result.get("result"),
                max_chars=MAX_TOOL_RESULT_CHARS,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": content,
                }
            )

    if plan_id is not None:
        await safe_plan_update("verifying")

    if run_error is not None:
        trace.emit(
            "run_failed",
            iterations=iterations,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            error_type=type(run_error).__name__,
        )
    elif not completed_with_text:
        final_text = "I hit the max tool-call limit without finishing. Try rephrasing."
        trace.emit(
            "run_failed",
            iterations=iterations,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            error_type="MaxIterations",
        )
    else:
        trace.emit(
            "run_completed",
            iterations=iterations,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    if plan_id is not None:
        failed_tools = sum(1 for outcome in tool_outcomes if not outcome.get("ok"))
        if run_error is not None:
            await safe_plan_update("failed", f"Run failed: {type(run_error).__name__}.")
        elif not completed_with_text:
            await safe_plan_update(
                "blocked", "The run reached its iteration limit before a final response."
            )
        elif failed_tools:
            trace.emit("run_verification_blocked", failed_tools=failed_tools)
            await safe_plan_update(
                "blocked",
                f"Final response produced, but {failed_tools} tool outcome(s) failed; verification is incomplete.",
            )
        else:
            await safe_plan_update(
                "completed",
                "Final response produced and all recorded tool outcomes succeeded.",
            )

    if image_data_urls:
        log_user_summary = (
            f"{user_message.strip() or '[no text]'} [{len(image_data_urls)} image(s)]"
        )
    else:
        log_user_summary = user_message

    async def save_trace(*, success: bool, error_message: str | None = None) -> None:
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
                success=success,
                error_message=error_message,
                trace_id=trace.trace_id,
                prompt_version=PROMPT_VERSION,
                provider=provider,
                model=last_model or current_model(),
                context_chars=context_chars,
                available_tools=len(selected_tool_specs),
                tool_outcomes=tool_outcomes,
                memory_hits=memory.hits,
                memory_chars=memory.chars,
                plan_id=plan_id,
                plan_status=plan_status,
            )
        except Exception:
            logger.exception("persistTurn failed trace_id=%s", trace.trace_id)

    if run_error is not None:
        await save_trace(success=False, error_message=str(run_error))
        raise run_error

    await save_trace(
        success=completed_with_text,
        error_message=None if completed_with_text else "max_iterations",
    )

    result: dict[str, Any] = {
        "text": final_text,
        "toolsUsed": tools_used,
        "iterations": iterations,
        "traceId": trace.trace_id,
    }
    if plan_id is not None:
        result["planId"] = plan_id
        result["planStatus"] = plan_status
    return result
