"""Import bank CSV exports: date,account,counterparty,amount[,currency][,memo]"""
import csv
import uuid
from dataclasses import dataclass, field
from typing import Iterable, TextIO

from ..accounts import currency_of
from ..money import Money
from ..storage import Store

SUSPENSE = "suspense"
REQUIRED = {"date", "account", "counterparty", "amount"}


@dataclass
class ImportResult:
    imported: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)


def read_rows(fh: TextIO) -> Iterable[dict]:
    reader = csv.DictReader(fh)
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    yield from reader


def _account_ref(ref: str) -> str:
    """New bank exports write 'acct:<id>', older ones the bare id (ADR 0003 #7)."""
    return ref.strip().lstrip("acct:")


def import_csv(store: Store, fh: TextIO, suspense: str = SUSPENSE) -> ImportResult:
    result = ImportResult()
    for lineno, row in enumerate(read_rows(fh), start=2):
        try:
            account = _account_ref(row["account"])
            account_cur = currency_of(store, account)
            currency = (row.get("currency") or account_cur).strip().upper()
            if currency != account_cur:
                raise ValueError(f"row is {currency}, account {account} is {account_cur}")
            amount = Money.parse(row["amount"], currency)
        except (KeyError, ValueError) as exc:
            result.skipped.append((lineno, str(exc)))
            continue
        store.post(uuid.uuid4().hex, [(account, amount), (suspense, -amount)],
                   memo=row.get("memo", "") or row["counterparty"])
        result.imported += 1
    return result
