"""Account statements."""
from dataclasses import dataclass

from .accounts import require
from .money import format_cents
from .storage import Store


@dataclass
class Statement:
    account_id: str
    rows: list[str]
    total_cents: int


def statement(store: Store, account_id: str, memo_filter: str | None = None) -> Statement:
    require(store, account_id)
    entries = [e for e in store.entries(account_id)
               if memo_filter is None or memo_filter.lower() in e.memo.lower()]
    rows = [f"{e.posted_at[:10]}  {format_cents(e.amount_cents):>14}  {e.memo}" for e in entries]
    total = sum(e.amount_cents for e in entries)
    return Statement(account_id, rows, total)


def render(stmt: Statement) -> str:
    lines = [f"Statement for {stmt.account_id}", *stmt.rows,
             f"{'Total':10}  {format_cents(stmt.total_cents):>14}"]
    return "\n".join(lines)
