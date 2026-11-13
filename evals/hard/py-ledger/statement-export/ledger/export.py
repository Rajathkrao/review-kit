"""Statement export for the accountants' spreadsheet."""
import csv
from typing import TextIO

from .accounts import require
from .money import format_cents
from .storage import Store

HEADER = ["date", "txn", "amount", "running_balance", "memo"]
# Cells starting with these are evaluated as formulas by Excel/LibreOffice/Sheets (OWASP CSV injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_text(value: str) -> str:
    """Neutralise a free-text cell so a spreadsheet shows it as text."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def export_statement(store: Store, account_id: str, out: TextIO) -> int:
    """Write the account's entries with a running balance. Returns the number of rows written.

    Amounts are written as plain numbers (format_cents without thousands separators) so the
    spreadsheet can sum them; only the memo is free text from bank files and needs neutralising.
    """
    require(store, account_id)
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    running = 0
    count = 0
    for e in store.entries(account_id):
        running += e.amount_cents
        writer.writerow([
            e.posted_at[:10],
            e.txn_id,
            format_cents(e.amount_cents).replace(",", ""),
            format_cents(running).replace(",", ""),
            _safe_text(e.memo),
        ])
        count += 1
    return count
