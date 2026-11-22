#!/usr/bin/env python3
"""Build two sample review packages for previewing the HTML walkthrough without a model run.

    python3 evals/build_walkthrough_demo.py OUT_DIR
    python3 skills/review-kit/scripts/render_html.py OUT_DIR/review-pkg
    python3 skills/review-kit/scripts/render_html.py OUT_DIR/explain-pkg

OUT_DIR/src holds a small Python payouts module; review-pkg has three confirmed findings, one
"worth a look" and one dismissed candidate; explain-pkg is the same change in explain mode.
"""
import json
import sys
from pathlib import Path

SERVICE = '''"""Turn settled balances into scheduled payouts and send the due ones to the bank."""
from datetime import datetime, timedelta, timezone

from payouts.bank import BankClient, TransferError
from payouts.store import PayoutStore


class PayoutService:
    def __init__(self, store: PayoutStore, bank: BankClient, notify):
        self.store = store
        self.bank = bank
        self.notify = notify

    def handle_settled(self, event: dict) -> int:
        """Webhook: balance.settled -> one payout per installment, one week apart."""
        amount = event["amount_cents"]
        parts = int(event.get("installments", 1))
        share = amount // parts
        start = datetime.now(timezone.utc)
        for i in range(parts):
            self.store.insert(
                merchant_id=event["merchant_id"],
                amount_cents=share,
                scheduled_for=start + timedelta(weeks=i),
                key=f"settled:{event['id']}:{i}",
            )
        return parts

    def run_due(self, now=None) -> int:
        """Job: send every pending payout whose time has come."""
        now = now or datetime.now(timezone.utc)
        sent = 0
        for row in self.store.pending_before(now):
            try:
                self.bank.transfer(row.merchant_id, row.amount_cents, ref=row.key)
            except TransferError:
                pass
            self.store.mark(row.id, "paid")
            self.notify(row.merchant_id, f"Payout of {row.amount_cents / 100:.2f} sent")
            sent += 1
        return sent
'''

STORE = '''import sqlite3
from dataclasses import dataclass


@dataclass
class Row:
    id: int
    merchant_id: str
    amount_cents: int
    key: str


class PayoutStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("create table if not exists payouts (id integer primary key, merchant_id text, "
                        "amount_cents int, scheduled_for text, key text, status text default 'pending')")

    def insert(self, merchant_id, amount_cents, scheduled_for, key):
        self.db.execute("insert into payouts (merchant_id, amount_cents, scheduled_for, key) values (?,?,?,?)",
                        (merchant_id, amount_cents, scheduled_for.isoformat(), key))

    def pending_before(self, now):
        cur = self.db.execute("select id, merchant_id, amount_cents, key from payouts "
                              "where status = 'pending' and scheduled_for <= ?", (now.isoformat(),))
        return [Row(*r) for r in cur.fetchall()]

    def mark(self, row_id, status):
        self.db.execute("update payouts set status = ? where id = ?", (status, row_id))
'''

BANK = '''class TransferError(Exception):
    pass


class BankClient:
    def transfer(self, merchant_id, amount_cents, ref):
        raise NotImplementedError
'''

WEBHOOK = '''from payouts.service import PayoutService


def on_event(service: PayoutService, event: dict):
    if event["type"] == "balance.settled":
        return service.handle_settled(event)
'''


def numbered_new_file(path, text):
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(f"{i:6d} +{l}" for i, l in enumerate(lines, 1))
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}\n")


def finding(fid, title, line_start, line_end, severity, rec, body, file="payouts/service.py"):
    return dict(id=fid, title=title, body=body, file=file, line_start=line_start, line_end=line_end,
                severity=severity, confidence=92 if severity != "minor" else 80, recommendation=rec,
                evidence="Read payouts/service.py and payouts/store.py at the reviewed commit.",
                evidence_status="source-verified", lenses=["correctness", "python"])


ARCH = {
    "caption": "A bank webhook creates payout rows; a scheduled job later sends the due ones and notifies the merchant.",
    "nodes": [
        {"id": "hook", "label": "balance.settled webhook", "kind": "request", "file": "payouts/webhook.py", "changed": True},
        {"id": "job", "label": "run_due job (every minute)", "kind": "job", "file": "payouts/service.py", "changed": True},
        {"id": "svc", "label": "PayoutService", "kind": "logic", "file": "payouts/service.py", "changed": True},
        {"id": "db", "label": "payouts table", "kind": "data", "file": "payouts/store.py"},
        {"id": "bank", "label": "Bank transfer API", "kind": "external"},
        {"id": "mail", "label": "Merchant notification", "kind": "external"},
    ],
    "edges": [
        {"from": "hook", "to": "svc", "label": "handle_settled"},
        {"from": "job", "to": "svc", "label": "run_due"},
        {"from": "svc", "to": "db", "label": "insert / mark"},
        {"from": "svc", "to": "bank", "label": "transfer"},
        {"from": "svc", "to": "mail", "label": "notify"},
    ],
}

SEQ = {
    "title": "A transfer fails during run_due",
    "actors": ["run_due", "payouts table", "Bank", "Merchant"],
    "messages": [
        {"from": "run_due", "to": "payouts table", "label": "pending_before(now): payout 7"},
        {"from": "run_due", "to": "Bank", "label": "transfer(m_42, 50000)"},
        {"from": "Bank", "to": "run_due", "label": "TransferError", "kind": "return"},
        {"from": "run_due", "to": "payouts table", "label": "mark(7, 'paid')", "finding_id": "F1"},
        {"from": "run_due", "to": "Merchant", "label": "\"Payout of 500.00 sent\""},
    ],
}

STEPS = [
    {"title": "The webhook hands the event to the service", "kind": "request", "file": "payouts/webhook.py",
     "lines": [4, 6], "explanation": "The bank posts `balance.settled` when funds clear. `on_event` forwards only that type to `PayoutService.handle_settled`, which returns the number of payouts it created."},
    {"title": "Split the amount into weekly installments", "kind": "logic", "file": "payouts/service.py",
     "lines": [14, 26], "explanation": "Each event becomes `installments` rows, one week apart, each worth `amount // parts` cents. The key `settled:<event id>:<i>` is meant to make each row unique per event.",
     "notes": [{"line": 18, "text": "Integer division: the remainder is not assigned to any row."}]},
    {"title": "Store each payout as pending", "kind": "data", "file": "payouts/store.py", "lines": [19, 21],
     "explanation": "`insert` writes a pending row. The table has no unique constraint on `key`, so the database will accept the same key twice."},
    {"title": "Send what is due and mark it paid", "kind": "job", "file": "payouts/service.py", "lines": [28, 40],
     "explanation": "The job reads every pending row scheduled before now, asks the bank to transfer it, marks it paid and tells the merchant."},
]

PROBLEMS = {
    "F1": {"pin_line": 36, "line_note": "The TransferError is swallowed, so the next line marks a failed transfer as paid.",
           "summary": "When the bank rejects a transfer, `run_due` ignores the error and still marks the payout paid and tells the merchant it was sent. The money never leaves, and nothing will ever retry it because the row is no longer pending.",
           "scenario": ["Payout 7 for merchant m_42 (500.00) is due at 09:00.", "run_due calls bank.transfer(m_42, 50000).", "The bank raises TransferError: account closed.", "The except block passes; mark(7, 'paid') runs.", "m_42 is told 500.00 was sent; the row is never retried."],
           "failure_step": 4,
           "root_cause": "The code treats the transfer call as fire-and-forget: the `try` only protects the loop from crashing, and the status update sits after it unconditionally. Marking paid should depend on the transfer having succeeded, which the current structure never checks.",
           "impact": "Every failed transfer becomes a silent loss for the merchant: they are told the money is on its way and support only finds out when they complain. With a 1-2% bank rejection rate, that is several payouts a day at moderate volume.",
           "fix": {"explanation": "Mark the row failed in the except branch and skip the notification, so a failed transfer stays visible and can be retried.", "file": "payouts/service.py",
                   "patch": "             try:\n                 self.bank.transfer(row.merchant_id, row.amount_cents, ref=row.key)\n             except TransferError:\n-                pass\n+                self.store.mark(row.id, \"failed\")\n+                continue\n             self.store.mark(row.id, \"paid\")"},
           "test": {"name": "tests/test_service.py::test_failed_transfer_is_not_paid", "explanation": "Fails today (status is paid), passes after the fix.",
                    "code": "def test_failed_transfer_is_not_paid():\n    store, bank = PayoutStore(), FailingBank()\n    svc = PayoutService(store, bank, notify=lambda *a: None)\n    store.insert('m_42', 50000, past(), 'k')\n    svc.run_due()\n    assert status(store, 'k') == 'failed'"}},
    "F2": {"pin_line": 18, "line_note": "Floor division drops the remainder: 100.00 in 3 parts pays 99.99.",
           "summary": "Installments are each `amount // parts`, so any remainder is never paid. A 100.00 balance split three ways pays 33.33 three times, and one cent disappears.",
           "scenario": ["A balance.settled event arrives for 10000 cents with installments = 3.", "share = 10000 // 3 = 3333.", "Three rows of 3333 are inserted.", "The merchant receives 9999 cents in total."],
           "root_cause": "The split assumes the amount divides evenly. Integer division is right for cents, but the leftover has to go somewhere, usually the first or last installment.",
           "impact": "One or two cents lost on most split payouts. Small per payout, but reconciliation against the settled balance will never match and finance will chase the difference.",
           "fix": {"explanation": "Give the remainder to the first installment.", "file": "payouts/service.py",
                   "patch": "         share = amount // parts\n+        extra = amount - share * parts\n         ...\n-                amount_cents=share,\n+                amount_cents=share + (extra if i == 0 else 0),"},
           "test": {"name": "tests/test_service.py::test_installments_sum", "explanation": "Sums the inserted rows.",
                    "code": "def test_installments_sum():\n    svc.handle_settled(event(amount_cents=10000, installments=3))\n    assert total(store) == 10000"}},
    "F3": {"pin_line": 24, "line_note": "Same key on a webhook retry, but nothing rejects the duplicate.",
           "summary": "The bank retries `balance.settled` up to five times. Each retry inserts the same installments again because the key is not unique in the table and nothing checks it first.",
           "scenario": ["Event evt_9 arrives; two rows are inserted.", "Our response times out; the bank retries evt_9.", "Two more rows with the same keys are inserted.", "run_due pays all four."],
           "root_cause": "The key was designed for idempotency but nothing enforces it: the table has no unique index and `insert` does a plain insert.",
           "impact": "Any slow webhook response doubles that merchant's payout. Retries are common during deploys, so this would show up within days.",
           "fix": {"explanation": "Add a unique index on key and use insert-or-ignore.", "file": "payouts/store.py",
                   "patch": "-        self.db.execute(\"insert into payouts (merchant_id, amount_cents, scheduled_for, key) values (?,?,?,?)\",\n+        self.db.execute(\"insert or ignore into payouts (merchant_id, amount_cents, scheduled_for, key) values (?,?,?,?)\","},
           "test": {"name": "tests/test_service.py::test_retry_is_idempotent", "explanation": "Send the same event twice.",
                    "code": "def test_retry_is_idempotent():\n    svc.handle_settled(evt)\n    svc.handle_settled(evt)\n    assert count(store) == 2"}},
}


def build(out: Path):
    src = out / "src"
    files = {"payouts/service.py": SERVICE, "payouts/store.py": STORE, "payouts/bank.py": BANK,
             "payouts/webhook.py": WEBHOOK, "payouts/__init__.py": ""}
    for p, t in files.items():
        (src / p).parent.mkdir(parents=True, exist_ok=True)
        (src / p).write_text(t)
    diff = "".join(numbered_new_file(p, files[p]) for p in ("payouts/service.py", "payouts/webhook.py"))
    meta = dict(repo="acme-payments", description="PR #52: Installment payouts and the run_due job (https://github.com/acme/acme-payments/pull/52)",
                collection_status="completed", repo_root=str(src), reviewed_commit="6d1d3900d2e4b1c0a9f8e7d6c5b4a3928170f6e5",
                base="main", branch="feature/installments", added=46, deleted=3,
                files=[{"path": "payouts/service.py", "status": "added", "added": 40, "deleted": 0},
                       {"path": "payouts/webhook.py", "status": "added", "added": 6, "deleted": 0},
                       {"path": "payouts/store.py", "status": "modified", "added": 0, "deleted": 3}],
                risk=["money", "webhook"])
    explainer = dict(title="Installment payouts", one_liner="Turns each `balance.settled` webhook into weekly installment payouts, and adds a job that sends due payouts to the bank and tells the merchant.",
                     why="From the PR and docs/payouts.md: merchants asked to receive large balances in weekly parts. Each event must create its payouts exactly once, and a failed transfer must never be reported as paid.",
                     before="Settled balances sat in the account until someone triggered a payout by hand. There were no installments.",
                     after="The webhook creates one pending row per installment, a week apart. Every minute `run_due` transfers the due rows, marks them paid and notifies the merchant.",
                     entry_point="on_event(balance.settled) and run_due() every minute",
                     architecture=ARCH, sequences=[SEQ], steps=STEPS,
                     key_concepts=[{"term": "Idempotency key", "meaning": "A value that lets the server do a request at most once, however often it is retried."}],
                     try_it_yourself=["Send the same balance.settled event twice: expect the same number of rows as once."],
                     changed_files=[{"path": "payouts/service.py", "role": "Creates and sends payouts", "change": "new", "order": 2},
                                    {"path": "payouts/webhook.py", "role": "Routes the bank event", "change": "new", "order": 1},
                                    {"path": "payouts/store.py", "role": "Row storage", "change": "modified", "order": 3}])
    review_steps = json.loads(json.dumps(STEPS))
    review_steps[1]["finding_ids"] = ["F2", "F3"]
    review_steps[3]["finding_ids"] = ["F1"]
    arch = json.loads(json.dumps(ARCH))
    arch["nodes"][2]["finding_ids"] = ["F1", "F2", "F3"]
    findings = [
        finding("F1", "Failed bank transfers are marked paid", 33, 39, "critical",
                "Mark the payout failed in the except branch and skip the notification.",
                "TransferError is swallowed and the row is marked paid."),
        finding("F2", "Installments don't add up to the settled amount", 18, 25, "important",
                "Add the remainder to the first installment.", "Floor division drops the remainder."),
        finding("F3", "A webhook retry creates the payouts again", 20, 25, "important",
                "Enforce the key with a unique index and insert-or-ignore.", "Duplicate keys are accepted."),
    ]
    review = dict(mode="deep", execution_status="completed", verdict="dont-ship",
                  summary="Three money-losing bugs on the main paths: failed transfers are marked paid, installments don't sum to the amount, and a webhook retry pays twice.",
                  findings=findings,
                  plausible=[{"title": "Notification text uses float formatting for money", "file": "payouts/service.py", "line_start": 38,
                              "check": "Whether merchants ever see amounts over 2^53 cents; if not, this is fine."}],
                  dropped=[{"title": "SQL injection in pending_before", "confidence": 20, "reason": "The query is parameterised; `now` is bound, not formatted in."}])
    for name, fx, ex in (("review-pkg", review, {**explainer, "steps": review_steps, "architecture": arch, "problems": PROBLEMS}),
                         ("explain-pkg", dict(mode="explain", execution_status="completed", verdict="ship",
                                              summary="Walkthrough of PR 52: installment payouts and the run_due job.", findings=[]), explainer)):
        pkg = out / name
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "meta.json").write_text(json.dumps(meta, indent=1))
        (pkg / "diff-numbered.txt").write_text(diff)
        (pkg / "findings.json").write_text(json.dumps(fx, indent=1))
        (pkg / "explainer.json").write_text(json.dumps(ex, indent=1))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1])))
