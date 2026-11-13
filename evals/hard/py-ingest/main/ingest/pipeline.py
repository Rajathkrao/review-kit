"""Turn raw partner rows into events. Bad rows go to the dead-letter list with a reason."""
from dataclasses import dataclass, field

from .models import Event
from .timeparse import parse_ts


@dataclass
class Result:
    events: list[Event] = field(default_factory=list)
    dead: list[tuple[dict, str]] = field(default_factory=list)


def process(rows) -> Result:
    res = Result()
    for row in rows:
        try:
            ts = parse_ts(row["ts"])
            ev = Event(tenant=str(row["tenant"]), ts=ts, kind=str(row["kind"]),
                       body=str(row.get("body", "")), event_id=str(row.get("id", "")))
        except (KeyError, ValueError, TypeError) as exc:
            res.dead.append((row, f"{type(exc).__name__}: {exc}"))
            continue
        res.events.append(ev)
    # Events are stored in time order per tenant; partners send files out of order.
    res.events.sort(key=lambda e: e.ts)
    return res
