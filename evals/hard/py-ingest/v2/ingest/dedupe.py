"""Drop partner resends (docs/ingest-v2.md #3)."""
from .models import Event


def drop_duplicates(events: list[Event]) -> list[Event]:
    """Keep the first event for each (tenant, event_id); events without an id are kept.
    Works in place, because batches are large."""
    seen: set[tuple[str, str]] = set()
    for e in events:
        if not e.event_id:
            continue
        key = (e.tenant, e.event_id)
        if key in seen:
            events.remove(e)
        else:
            seen.add(key)
    return events
