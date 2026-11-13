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

    def events_page(self, tenant_id: str, limit: int, offset: int) -> list[dict]:
        cur = self.db.execute(
            "SELECT ts, kind, body, event_id FROM events WHERE tenant_id = ? ORDER BY ts, id LIMIT ? OFFSET ?",
            (tenant_id, limit, offset))
        return [dict(zip(("ts", "kind", "body", "event_id"), r)) for r in cur]

    def billable_tenants(self) -> list[str]:
        """Leaf tenants: the ones no other tenant names as its parent (docs/ingest-v2.md #8)."""
        rows = self.db.execute(
            "SELECT id FROM tenants WHERE id NOT IN (SELECT parent_id FROM tenants) ORDER BY id").fetchall()
        return [r[0] for r in rows]

    def usage(self) -> dict[str, int]:
        """Events per billable tenant."""
        counts = dict(self.db.execute("SELECT tenant_id, COUNT(*) FROM events GROUP BY tenant_id").fetchall())
        return {t: counts.get(t, 0) for t in self.billable_tenants()}

    def count_events(self, tenant_id=None) -> int:
        if tenant_id is None:
            return self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return self.db.execute("SELECT COUNT(*) FROM events WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
