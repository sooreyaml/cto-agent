class WorkError(Exception):
    pass


class UnknownWorkKind(WorkError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Unknown work kind: {kind}")


class WorkNotFound(WorkError):
    def __init__(self, kind: str, item_id: str) -> None:
        super().__init__(f"{kind} not found: {item_id}")


class OpenPriorityLimit(WorkError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"At most {limit} open priorities are allowed")


class InvalidWorkField(WorkError):
    pass
