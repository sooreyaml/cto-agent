from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def async_database_url_from(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PORT: int = 8000
    NODE_ENV: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "info"
    TIMEZONE: str = "Europe/London"
    APP_PUBLIC_URL: str = "http://localhost:8000"

    DATABASE_URL: str = Field(min_length=1)

    LLM_PROVIDER: Literal["openrouter", "openai-codex"] = "openrouter"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "anthropic/claude-sonnet-4.6"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    CODEX_MODEL: str = "gpt-5.4"
    CODEX_BASE_URL: str = "https://chatgpt.com/backend-api/codex"

    DISCORD_BOT_TOKEN: str = Field(min_length=1)
    DISCORD_USER_ID: str = Field(min_length=1)

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_USER_EMAIL: str = ""

    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_PAT: str = ""
    GITHUB_USERNAME: str = ""

    GRANOLA_API_BASE: str = "https://api.granola.ai"
    GRANOLA_API_KEY: str = ""

    CRON_SECRET: str = ""

    SYSTEM_PROMPT_PATH: str = "prompts/system.md"

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("OPENROUTER_BASE_URL", "GRANOLA_API_BASE", "APP_PUBLIC_URL", "CODEX_BASE_URL")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def require_openrouter_key(self) -> Self:
        if self.LLM_PROVIDER == "openrouter" and not self.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        return self

    @property
    def async_database_url(self) -> str:
        return async_database_url_from(self.DATABASE_URL)

    @property
    def owner_user_id(self) -> str:
        return self.DISCORD_USER_ID

    @property
    def docs_enabled(self) -> bool:
        return self.NODE_ENV in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
