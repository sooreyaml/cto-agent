from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    OPENROUTER_API_KEY: str = Field(min_length=1)
    OPENROUTER_MODEL: str = "anthropic/claude-sonnet-4.6"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    SLACK_BOT_TOKEN: str = Field(min_length=1)
    SLACK_SIGNING_SECRET: str = Field(min_length=1)
    SLACK_USER_ID: str = Field(min_length=1)

    NOTION_TOKEN: str = ""
    NOTION_PROJECTS_DB_ID: str = ""
    NOTION_TASKS_DB_ID: str = ""
    NOTION_LOGS_DB_ID: str = ""
    NOTION_STATUS_PROPERTY_KIND: Literal["select", "status"] = "status"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_USER_EMAIL: str = ""

    GITHUB_PAT: str = ""
    GITHUB_USERNAME: str = ""
    GITHUB_BRIEF_REPOS: str = ""

    GRANOLA_API_BASE: str = "https://api.granola.ai"
    GRANOLA_API_KEY: str = ""

    CRON_SECRET: str = ""

    SYSTEM_PROMPT_PATH: str = "prompts/system.md"

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("OPENROUTER_BASE_URL", "GRANOLA_API_BASE")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        return url

    @property
    def docs_enabled(self) -> bool:
        return self.NODE_ENV in {"development", "test"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
