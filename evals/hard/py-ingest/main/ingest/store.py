import sqlite3

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES tenants(id),   -- NULL for top-level organisations
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    partition INTEGER NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dead_letters (id INTEGER PRIMARY KEY, row TEXT NOT NULL, reason TEXT NOT NULL);
"""


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def add_tenant(self, tenant_id, name, parent_id=None):
        with self.db:
            self.db.execute("INSERT INTO tenants (id, parent_id, name) VALUES (?, ?, ?)",
                            (tenant_id, parent_id, name))

    def write_events(self, events: list[Event], partition_of) -> int:
        with self.db:
            self.db.executemany(
                "INSERT INTO events (tenant_id, partition, ts, kind, body, event_id) VALUES (?, ?, ?, ?, ?, ?)",
                [(e.tenant, partition_of(e.tenant), e.ts.isoformat(), e.kind, e.body, e.event_id) for e in events])
        return len(events)

    def write_dead(self, dead) -> None:
        import json
        with self.db:
            self.db.executemany("INSERT INTO dead_letters (row, reason) VALUES (?, ?)",
                                [(json.dumps(r, default=str), why) for r, why in dead])

    def count_events(self, tenant_id=None) -> int:
        if tenant_id is None:
            return self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM events WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
