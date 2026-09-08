from typing import Literal

Kind = Literal["priority", "task", "decision", "commitment"]

KINDS: frozenset[str] = frozenset({"priority", "task", "decision", "commitment"})

PRIORITY_STATUSES: frozenset[str] = frozenset({"open", "done", "dropped"})
TASK_STATUSES: frozenset[str] = frozenset({"open", "blocked", "done", "cancelled"})
COMMITMENT_STATUSES: frozenset[str] = frozenset({"open", "done", "cancelled"})

MAX_OPEN_PRIORITIES = 5
SNAPSHOT_MAX_LINES = 15
DUE_SOON_DAYS = 7
LIST_DEFAULT_LIMIT = 20
LIST_MAX_LIMIT = 50
