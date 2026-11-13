"""ledger command line."""
import argparse
import sys

from . import reports, transfers
from .export import export_statement
from .importers.csv_import import import_csv
from .money import parse_amount
from .storage import Store


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ledger")
    p.add_argument("--db", default="ledger.sqlite")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transfer")
    t.add_argument("source"); t.add_argument("target"); t.add_argument("amount")
    t.add_argument("--fee", default=None)
    s = sub.add_parser("statement"); s.add_argument("account"); s.add_argument("--grep")
    s.add_argument("--csv", metavar="PATH", help="write the statement as CSV instead")
    i = sub.add_parser("import"); i.add_argument("csv_path")
    args = p.parse_args(argv)
    store = Store(args.db)
    if args.cmd == "transfer":
        fee = None if args.fee is None else parse_amount(args.fee)
        print(transfers.transfer(store, args.source, args.target, parse_amount(args.amount), fee))
    elif args.cmd == "statement" and args.csv:
        if args.grep:
            p.error("--grep cannot be combined with --csv")
        with open(args.csv, "w", newline="") as fh:
            n = export_statement(store, args.account, fh)
        print(f"wrote {n} rows to {args.csv}")
    elif args.cmd == "statement":
        print(reports.render(reports.statement(store, args.account, args.grep)))
    elif args.cmd == "import":
        with open(args.csv_path, newline="") as fh:
            res = import_csv(store, fh)
        print(f"imported {res.imported}, skipped {len(res.skipped)}")
        for lineno, why in res.skipped:
            print(f"  line {lineno}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
