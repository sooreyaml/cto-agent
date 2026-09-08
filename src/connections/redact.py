import re

_TOKEN_RE = re.compile(
    r"""(?ix)
    (?:
        ghp_[A-Za-z0-9]{20,}
        | gho_[A-Za-z0-9]{20,}
        | ghu_[A-Za-z0-9]{20,}
        | github_pat_[A-Za-z0-9_]{20,}
        | grn_[A-Za-z0-9]{16,}
        | glpat-[A-Za-z0-9_\-]{20,}
        | lin_api_[A-Za-z0-9]{20,}
        | ntn_[A-Za-z0-9]{20,}
        | xox[baprs]-[A-Za-z0-9-]{20,}
        | sk-(?:live|test)?[_-]?[A-Za-z0-9]{20,}
        | tvly-[A-Za-z0-9_\-]{16,}
        | sntrys_[A-Za-z0-9_\-]{16,}
        | (?:Bearer|token)\s+[A-Za-z0-9_\-\.=]{16,}
    )
    """
)


def redact_secrets(text: str | None) -> str:
    if not text:
        return ""
    return _TOKEN_RE.sub("[redacted]", text)


def redact_obj(value: object) -> object:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, dict):
        out: dict[object, object] = {}
        for key, item in value.items():
            if str(key).lower() in {"token", "secret", "api_key", "pat", "refresh_token"}:
                out[key] = "[redacted]"
            else:
                out[key] = redact_obj(item)
        return out
    return value
