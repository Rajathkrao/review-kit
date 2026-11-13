from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    tenant: str
    ts: datetime
    kind: str
    body: str = ""
    event_id: str = ""
