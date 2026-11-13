"""SQLite storage for accounts and entries."""
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from .money import Money

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('asset', 'liability', 'income', 'expense')),
    currency TEXT NOT NULL DEFAULT 'USD'
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    memo TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_account ON entries(account_id, currency);
"""


class UnbalancedTransaction(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    id: int
    txn_id: str
    account_id: str
    amount: Money
    memo: str
    posted_at: str


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def migrate(db: sqlite3.Connection) -> None:
    """Upgrade a pre-0003 database in place: every existing row is USD (ADR 0003 #3)."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "entries" not in tables:
        return
    with db:
        cols = _columns(db, "entries")
        if "amount_cents" in cols:
            db.execute("ALTER TABLE entries RENAME COLUMN amount_cents TO amount_minor")
        if "currency" not in cols:
            db.execute("ALTER TABLE entries ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
        if "currency" not in _columns(db, "accounts"):
            db.execute("ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
        db.execute("DROP INDEX IF EXISTS entries_account")


def _entry(row) -> Entry:
    id_, txn, account, amount, currency, memo, posted = row
    return Entry(id_, txn, account, Money(amount, currency), memo, posted)


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        migrate(self.db)
        self.db.executescript(SCHEMA)

    def add_account(self, account_id: str, name: str, kind: str, currency: str = "USD") -> None:
        with self.db:
            self.db.execute("INSERT INTO accounts (id, name, kind, currency) VALUES (?, ?, ?, ?)",
                            (account_id, name, kind, currency))

    def account_exists(self, account_id: str) -> bool:
        row = self.db.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return row is not None

    def account_currency(self, account_id: str) -> str:
        row = self.db.execute("SELECT currency FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            raise KeyError(account_id)
        return row[0]

    def post(self, txn_id: str, lines: list[tuple[str, Money]], memo: str = "") -> None:
        """Post a transaction: lines of (account_id, Money) that sum to zero in each currency."""
        sums: dict[str, int] = defaultdict(int)
        for _, money in lines:
            sums[money.currency] += money.amount
        unbalanced = {cur: amt for cur, amt in sums.items() if amt}
        if unbalanced:
            raise UnbalancedTransaction(f"transaction does not balance: {unbalanced}")
        now = datetime.now(timezone.utc).isoformat()
        with self.db:
            self.db.executemany(
                "INSERT INTO entries (txn_id, account_id, amount_minor, currency, memo, posted_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(txn_id, account, m.amount, m.currency, memo, now) for account, m in lines])

    def entries(self, account_id: str) -> list[Entry]:
        return list(self.iter_entries(account_id))

    def iter_entries(self, account_id: str, currency: str | None = None) -> Iterator[Entry]:
        """Stream an account's entries in posting order without loading them all."""
        sql = ("SELECT id, txn_id, account_id, amount_minor, currency, memo, posted_at FROM entries"
               " WHERE account_id = ?")
        params: list = [account_id]
        if currency:
            sql += " AND currency = ?"
            params.append(currency)
        cur = self.db.execute(sql + " ORDER BY id", params)
        for row in cur:
            yield _entry(row)

    def balance(self, account_id: str, currency: str) -> Money:
        row = self.db.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) FROM entries WHERE account_id = ? AND currency = ?",
            (account_id, currency)).fetchone()
        return Money(row[0], currency)

    def currencies_of(self, account_id: str) -> list[str]:
        rows = self.db.execute("SELECT DISTINCT currency FROM entries WHERE account_id = ? ORDER BY 1",
                               (account_id,)).fetchall()
        return [r[0] for r in rows]
