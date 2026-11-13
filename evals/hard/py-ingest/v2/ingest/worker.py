"""Process one partner file end to end."""
import logging
from dataclasses import replace

from .config import Settings
from .dedupe import drop_duplicates
from .pipeline import process
from .reader import read_ndjson
from .redact import redact
from .sharding import partition_for
from .store import Store

log = logging.getLogger(__name__)


def run_file(path: str, store: Store, settings: Settings) -> dict:
    res = process(read_ndjson(path))
    events = drop_duplicates(res.events)
    if settings.redact:
        events = [replace(e, body=redact(e.body)) for e in events]
    if settings.dry_run:
        log.info("dry run: %s would write %d events", path, len(events))
        written = 0
    else:
        written = store.write_events(events, lambda t: partition_for(t, settings.partitions))
    store.write_dead(res.dead)
    return {"file": path, "events": written, "dead": len(res.dead), "dry_run": settings.dry_run}
