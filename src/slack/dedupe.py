TTL_MS = 60 * 60 * 1000
_seen: dict[str, float] = {}


def _prune(now_ms: float) -> None:
    stale = [event_id for event_id, seen_at in _seen.items() if now_ms - seen_at > TTL_MS]
    for event_id in stale:
        del _seen[event_id]


def is_duplicate_slack_event(event_id: str) -> bool:
    now_ms = time_ms()
    _prune(now_ms)
    if event_id in _seen:
        return True
    _seen[event_id] = now_ms
    return False


def time_ms() -> float:
    import time

    return time.time() * 1000
