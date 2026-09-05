from openai import AsyncOpenAI

from src.config import get_settings

settings = get_settings()

llm = AsyncOpenAI(
    base_url=settings.OPENROUTER_BASE_URL,
    api_key=settings.OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": settings.APP_PUBLIC_URL,
        "X-Title": "CTO Agent",
    },
)

MODEL = settings.OPENROUTER_MODEL
