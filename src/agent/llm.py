from __future__ import annotations

import logging
from typing import Any

import openai
from openai import AsyncOpenAI

from src.agent.codex_oauth import load_credential
from src.agent.codex_responses import CodexLLM
from src.config import get_settings

logger = logging.getLogger(__name__)


def current_model() -> str:
    current = get_settings()
    if current.LLM_PROVIDER == "openai-codex":
        return current.CODEX_MODEL
    return current.OPENROUTER_MODEL


def should_fallback_to_codex(err: BaseException) -> bool:
    if isinstance(err, (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)):
        return True
    status = getattr(err, "status_code", None)
    return status in {401, 402, 403, 408, 429, 500, 502, 503, 504}


class _Completions:
    def __init__(self, owner: _LLM) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> Any:
        current = get_settings()
        if current.LLM_PROVIDER == "openai-codex":
            return await self._owner._codex.chat.completions.create(**kwargs)

        try:
            return await self._owner._router().chat.completions.create(**kwargs)
        except Exception as err:
            if not should_fallback_to_codex(err):
                raise
            if await load_credential() is None:
                raise
            logger.warning("openrouter failed; falling back to openai-codex: %s", err)
            fallback = {**kwargs, "model": current.CODEX_MODEL}
            return await self._owner._codex.chat.completions.create(**fallback)


class _Chat:
    def __init__(self, owner: _LLM) -> None:
        self.completions = _Completions(owner)


class _LLM:
    def __init__(self) -> None:
        self._openrouter: AsyncOpenAI | None = None
        self._codex = CodexLLM()
        self.chat = _Chat(self)

    def _router(self) -> AsyncOpenAI:
        if self._openrouter is None:
            current = get_settings()
            self._openrouter = AsyncOpenAI(
                base_url=current.OPENROUTER_BASE_URL,
                api_key=current.OPENROUTER_API_KEY,
                default_headers={
                    "HTTP-Referer": current.APP_PUBLIC_URL,
                    "X-Title": "CTO Agent",
                },
            )
        return self._openrouter


llm = _LLM()
