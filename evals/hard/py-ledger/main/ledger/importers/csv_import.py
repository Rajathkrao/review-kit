"""Import bank CSV exports: date,account,counterparty,amount,memo"""
import csv
import uuid
from dataclasses import dataclass
from typing import Iterable, TextIO

from ..accounts import require
from ..money import parse_amount
from ..storage import Store

SUSPENSE = "suspense"


@dataclass
class ImportResult:
    imported: int
    skipped: list[tuple[int, str]]


def read_rows(fh: TextIO) -> Iterable[dict]:
    reader = csv.DictReader(fh)
    missing = {"date", "account", "counterparty", "amount"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    yield from reader


def import_csv(store: Store, fh: TextIO) -> ImportResult:
    result = ImportResult(0, [])
    for lineno, row in enumerate(read_rows(fh), start=2):
        try:
            account = row["account"].strip()
            require(store, account)
            amount = parse_amount(row["amount"])
        except (KeyError, ValueError) as exc:
            result.skipped.append((lineno, str(exc)))
            continue
        store.post(uuid.uuid4().hex, [(account, amount), (SUSPENSE, -amount)],
                   memo=row.get("memo", "") or row["counterparty"])
        result.imported += 1
    return result
