from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 5
    run_at: datetime | None = None      # aware UTC; None = as soon as possible
    timeout: float = 60.0
    last_error: str = ""
