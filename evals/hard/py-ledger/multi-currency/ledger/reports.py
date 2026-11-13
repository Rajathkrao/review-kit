"""Account statements, one per currency (ADR 0003 #8)."""
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .accounts import require
from .money import Money
from .storage import Entry, Store


@dataclass
class Statement:
    account_id: str
    currency: str
    rows: list[str]
    total: Money


def _matches(entry: Entry, memo_filter: str | None) -> bool:
    return memo_filter is None or memo_filter.lower() in entry.memo.lower()


def _row(entry: Entry) -> str:
    return f"{entry.posted_at[:10]}  {entry.amount.format(with_code=False):>16}  {entry.memo}"


def totals_by_currency(entries: Iterable[Entry]) -> dict[str, Money]:
    totals: dict[str, Money] = {}
    for e in entries:
        cur = e.amount.currency
        totals[cur] = totals.get(cur, Money.zero(cur)) + e.amount
    return totals


def statement(store: Store, account_id: str, currency: str | None = None,
              memo_filter: str | None = None) -> list[Statement]:
    """Statements for an account: every matching entry and the closing total, per currency."""
    require(store, account_id)
    entries = (e for e in store.iter_entries(account_id, currency) if _matches(e, memo_filter))
    totals = totals_by_currency(entries)
    rows: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        rows[e.amount.currency].append(_row(e))
    return [Statement(account_id, cur, rows[cur], totals[cur]) for cur in sorted(totals)]


def render(stmts: list[Statement]) -> str:
    out: list[str] = []
    for st in stmts:
        out += [f"Statement for {st.account_id} ({st.currency})", *st.rows,
                f"{'Total':10}  {st.total.format(with_code=False):>16}", ""]
    return "\n".join(out).rstrip() or "No entries"
