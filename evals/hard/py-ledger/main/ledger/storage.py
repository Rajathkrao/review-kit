"""SQLite storage for accounts and entries."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('asset', 'liability', 'income', 'expense'))
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    amount_cents INTEGER NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_account ON entries(account_id);
"""


@dataclass(frozen=True)
class Entry:
    id: int
    txn_id: str
    account_id: str
    amount_cents: int
    memo: str
    posted_at: str


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def add_account(self, account_id: str, name: str, kind: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO accounts (id, name, kind) VALUES (?, ?, ?)",
                            (account_id, name, kind))

    def account_exists(self, account_id: str) -> bool:
        row = self.db.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return row is not None

    def post(self, txn_id: str, lines: list[tuple[str, int]], memo: str = "") -> None:
        """Post a balanced transaction: lines of (account_id, amount_cents) summing to zero."""
        if sum(amount for _, amount in lines) != 0:
            raise ValueError("transaction does not balance")
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.executemany(
                "INSERT INTO entries (txn_id, account_id, amount_cents, memo, posted_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [(txn_id, account, amount, memo, now) for account, amount in lines])

    def entries(self, account_id: str) -> list[Entry]:
        rows = self.db.execute(
            "SELECT id, txn_id, account_id, amount_cents, memo, posted_at FROM entries"
            " WHERE account_id = ? ORDER BY id", (account_id,)).fetchall()
        return [Entry(*r) for r in rows]

    def balance_cents(self, account_id: str) -> int:
        row = self.db.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM entries WHERE account_id = ?",
                              (account_id,)).fetchone()
        return row[0]
