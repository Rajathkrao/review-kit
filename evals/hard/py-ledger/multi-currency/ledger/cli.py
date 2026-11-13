"""ledger command line."""
import argparse
import sys

from . import reports
from .accounts import currency_of
from .fx import RateTable
from .importers.csv_import import import_csv
from .importers.ofx_import import import_ofx
from .money import Money
from .storage import Store
from .transfers import TransferRequest, transfer


def _rates(path):
    if not path:
        return None
    with open(path, newline="") as fh:
        return RateTable.load_csv(fh)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ledger")
    p.add_argument("--db", default="ledger.sqlite")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transfer")
    t.add_argument("source"); t.add_argument("target"); t.add_argument("amount")
    t.add_argument("--fee", default=None, help="fee in the source currency; 0 for none")
    t.add_argument("--rates", help="CSV of base,quote,rate for cross-currency transfers")
    t.add_argument("--memo", default="")
    s = sub.add_parser("statement"); s.add_argument("account")
    s.add_argument("--grep"); s.add_argument("--currency")
    i = sub.add_parser("import"); i.add_argument("path")
    i.add_argument("--format", choices=("csv", "ofx"), default=None)
    args = p.parse_args(argv)
    store = Store(args.db)
    if args.cmd == "transfer":
        cur = currency_of(store, args.source)
        fee = None if args.fee is None else Money.parse(args.fee, cur)
        req = TransferRequest(args.source, args.target, Money.parse(args.amount, cur), fee, args.memo)
        print(transfer(store, req, _rates(args.rates)))
    elif args.cmd == "statement":
        print(reports.render(reports.statement(store, args.account, args.currency, args.grep)))
    elif args.cmd == "import":
        fmt = args.format or ("ofx" if args.path.lower().endswith((".ofx", ".qfx")) else "csv")
        with open(args.path, newline="") as fh:
            if fmt == "ofx":
                res = import_ofx(store, fh)
                print(f"imported {res.imported}, duplicates {res.duplicates}, skipped {len(res.skipped)}")
                skipped = res.skipped
            else:
                res = import_csv(store, fh)
                print(f"imported {res.imported}, skipped {len(res.skipped)}")
                skipped = res.skipped
        for where, why in skipped:
            print(f"  {where}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
