import re

_LINK_WITH_LABEL = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_LINK_BARE = re.compile(r"<(https?://[^|>]+)>")
_BOLD = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC = re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])")
_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`[^`]+`")


def slack_mrkdwn_to_discord(text: str) -> str:
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    protected = _CODE_BLOCK.sub(stash, text)
    protected = _INLINE_CODE.sub(stash, protected)
    protected = _LINK_WITH_LABEL.sub(r"[\2](\1)", protected)
    protected = _LINK_BARE.sub(r"\1", protected)
    protected = _BOLD.sub(r"**\1**", protected)
    protected = _ITALIC.sub(r"*\1*", protected)
    for index, chunk in enumerate(placeholders):
        protected = protected.replace(f"\x00{index}\x00", chunk)
    return protected


def split_discord_sections(body: str, max_len: int = 2000) -> list[str]:
    text = body.strip()
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            parts.append(rest)
            break
        cut = rest.rfind("\n\n", 0, max_len)
        if cut < max_len * 0.4:
            cut = rest.rfind("\n", 0, max_len)
        if cut < max_len * 0.3:
            cut = max_len
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return parts
