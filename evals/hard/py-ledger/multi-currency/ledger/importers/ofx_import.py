"""Import OFX 1.x (SGML) bank statements.

Only the parts we need: the statement currency (CURDEF), the account id (ACCTID) and the
STMTTRN transactions (TRNTYPE, DTPOSTED, TRNAMT, FITID, NAME, MEMO). FITIDs already imported
for the account are skipped, so re-importing the same file is harmless.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import TextIO

from ..accounts import currency_of
from ..money import Money
from ..storage import Store

SUSPENSE = "suspense"
_TAG = re.compile(r"<(/?)([A-Z0-9.]+)>([^<\r\n]*)")


class OfxError(ValueError):
    pass


@dataclass
class OfxTransaction:
    fitid: str
    posted: date
    amount: str
    kind: str = ""
    name: str = ""
    memo: str = ""


@dataclass
class OfxStatement:
    account_id: str
    currency: str
    transactions: list[OfxTransaction] = field(default_factory=list)


@dataclass
class OfxImportResult:
    imported: int = 0
    duplicates: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _parse_date(text: str) -> date:
    # OFX dates are YYYYMMDD[HHMMSS[.XXX]][TZ]; the date part is enough here.
    digits = text.strip()[:8]
    if len(digits) != 8 or not digits.isdigit():
        raise OfxError(f"bad DTPOSTED {text!r}")
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))


def _split_header(text: str) -> str:
    """Drop the colon-separated OFX 1.x header that precedes <OFX>."""
    start = text.find("<OFX>")
    if start < 0:
        raise OfxError("no <OFX> element")
    return text[start:]


def parse(fh: TextIO) -> OfxStatement:
    body = _split_header(fh.read())
    account = currency = None
    txns: list[OfxTransaction] = []
    current: dict[str, str] | None = None
    for closing, tag, value in _TAG.findall(body):
        value = value.strip()
        if tag == "STMTTRN":
            if closing:
                if current is None:
                    raise OfxError("</STMTTRN> without <STMTTRN>")
                txns.append(_txn(current))
                current = None
            else:
                current = {}
            continue
        if closing:
            continue
        if current is not None:
            current[tag] = value
        elif tag == "CURDEF":
            currency = value.upper()
        elif tag == "ACCTID":
            account = value
    if current is not None:
        raise OfxError("unterminated <STMTTRN>")
    if not account or not currency:
        raise OfxError("statement has no ACCTID or CURDEF")
    return OfxStatement(account, currency, txns)


def _txn(fields: dict[str, str]) -> OfxTransaction:
    try:
        return OfxTransaction(fitid=fields["FITID"], posted=_parse_date(fields["DTPOSTED"]),
                              amount=fields["TRNAMT"], kind=fields.get("TRNTYPE", ""),
                              name=fields.get("NAME", ""), memo=fields.get("MEMO", ""))
    except KeyError as exc:
        raise OfxError(f"STMTTRN missing {exc.args[0]}") from None


def _seen_fitids(store: Store, account_id: str) -> set[str]:
    rows = store.db.execute(
        "SELECT memo FROM entries WHERE account_id = ? AND memo LIKE 'ofx:%'", (account_id,)).fetchall()
    return {r[0].split(" ", 1)[0][4:] for r in rows}


def import_ofx(store: Store, fh: TextIO, account_map: dict[str, str] | None = None,
               suspense: str = SUSPENSE) -> OfxImportResult:
    """Import one OFX statement. account_map maps the bank's ACCTID to our account id."""
    stmt = parse(fh)
    account = (account_map or {}).get(stmt.account_id, stmt.account_id)
    if currency_of(store, account) != stmt.currency:
        raise OfxError(f"statement is {stmt.currency}, account {account} is {currency_of(store, account)}")
    seen = _seen_fitids(store, account)
    result = OfxImportResult()
    for t in stmt.transactions:
        if t.fitid in seen:
            result.duplicates += 1
            continue
        try:
            amount = Money.parse(t.amount, stmt.currency)
        except ValueError as exc:
            result.skipped.append((t.fitid, str(exc)))
            continue
        memo = f"ofx:{t.fitid} {t.name or t.memo}".strip()
        store.post(uuid.uuid4().hex, [(account, amount), (suspense, -amount)], memo=memo)
        seen.add(t.fitid)
        result.imported += 1
    return result
