from __future__ import annotations

import re

from src.connections.constants import (
    _CONNECT_PREFIXES,
    GITHUB_CONNECT_COMMANDS,
    GRANOLA_CONNECT_COMMANDS,
)
from src.google.service import is_google_connect_command


def _normalize_command(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower().rstrip(".!?")
    for prefix in _CONNECT_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned


def match_connect_command(text: str) -> str | None:
    if is_google_connect_command(text):
        return "google"
    cleaned = _normalize_command(text)
    if cleaned in GITHUB_CONNECT_COMMANDS:
        return "github"
    if cleaned in GRANOLA_CONNECT_COMMANDS:
        return "granola"
    return None
