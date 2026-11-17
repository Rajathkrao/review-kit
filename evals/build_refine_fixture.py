#!/usr/bin/env python3
"""Build the refine-mode fixture: a small, working, tangled Python package with git history.

  python3 evals/build_refine_fixture.py <dir>      creates <dir>/py-notify (a git repository)

What is planted (the answer key for a refine run):
  bug       notify/service.py send_bulk(): an empty recipient list divides by zero
  move      the per-channel rules (limit, cost, retries) live as `channel == "..."` branches in
            service.py, report.py and retry.py, with the limits copied in settings.py; one
            channel table removes them all
  hidden    settings.py and service.py change together in every commit, with no import
  copies    send_email / send_sms / send_push in channels.py are one function three times
  surplus   BaseSender with one subclass, dispatch() that only forwards, the `legacy` flag nobody
            passes, old_format_report() that nothing calls
  special   a swallowed exception in report.py, a sleep "for the SMS gateway" in channels.py
  keep      the retry ceiling for sms in retry.py is a real requirement (carrier rule, commented)
Tests in tests/ pass before any change and pin send(), cost and retries, but not report.py.
"""
import subprocess
import sys
from pathlib import Path

FILES = {
    "notify/__init__.py": "",
    "notify/settings.py": '''EMAIL_LIMIT = 100
SMS_LIMIT = 20
PUSH_LIMIT = 500
GATEWAY = "https://gateway.example.com/v2/send"
''',
    "notify/channels.py": '''import time

GATEWAY = "https://gateway.example.com/v2/send"
SENT = []


class BaseSender:
    def deliver(self, kind, to, body):
        raise NotImplementedError


class GatewaySender(BaseSender):
    def deliver(self, kind, to, body):
        SENT.append((kind, to, body, GATEWAY))
        return True


_sender = GatewaySender()


def send_email(to, body):
    if not to:
        raise ValueError("no recipient")
    payload = body.strip()
    ok = _sender.deliver("email", to, payload)
    return {"channel": "email", "to": to, "ok": ok}


def send_sms(to, body):
    if not to:
        raise ValueError("no recipient")
    payload = body.strip()
    time.sleep(0.01)  # HACK: the SMS gateway drops messages sent back to back
    ok = _sender.deliver("sms", to, payload)
    return {"channel": "sms", "to": to, "ok": ok}


def send_push(to, body):
    if not to:
        raise ValueError("no recipient")
    payload = body.strip()
    ok = _sender.deliver("push", to, payload)
    return {"channel": "push", "to": to, "ok": ok}
''',
    "notify/service.py": '''from notify import channels
from notify.retry import max_retries


def dispatch(channel, to, body):
    return send(channel, to, body)


def send(channel, to, body, legacy=False):
    if legacy:
        body = body.upper()
    if channel == "email":
        if len(body) > 100:
            raise ValueError("too long")
        result = channels.send_email(to, body)
    elif channel == "sms":
        if len(body) > 20:
            raise ValueError("too long")
        result = channels.send_sms(to, body)
    elif channel == "push":
        if len(body) > 500:
            raise ValueError("too long")
        result = channels.send_push(to, body)
    else:
        raise ValueError("unknown channel")
    result["retries"] = max_retries(channel)
    return result


def cost_cents(channel, count):
    if channel == "email":
        return 0
    elif channel == "sms":
        return count * 4
    elif channel == "push":
        return count * 1
    raise ValueError("unknown channel")


def send_bulk(channel, recipients, body):
    results = []
    for i in range(len(recipients)):
        results.append(send(channel, recipients[i], body))
    total = cost_cents(channel, len(recipients))
    return {"results": results, "cost_each": total / len(recipients)}
''',
    "notify/retry.py": '''def max_retries(channel):
    if channel == "email":
        return 5
    if channel == "sms":
        # carriers block a number after 3 attempts in an hour; never raise this
        return 2
    if channel == "push":
        return 5
    return 0
''',
    "notify/report.py": '''import json


def summarize(results):
    out = {"email": 0, "sms": 0, "push": 0, "cost": 0}
    for r in results:
        if r["channel"] == "email":
            out["email"] += 1
        elif r["channel"] == "sms":
            out["sms"] += 1
            out["cost"] += 4
        elif r["channel"] == "push":
            out["push"] += 1
            out["cost"] += 1
    return out


def load_previous(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def old_format_report(results):
    lines = []
    for r in results:
        lines.append(r["channel"] + ":" + r["to"])
    return "\\n".join(lines)
''',
    "tests/__init__.py": "",
    "tests/test_service.py": '''import unittest

from notify import channels, service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        channels.SENT.clear()

    def test_send_each_channel(self):
        for kind in ("email", "sms", "push"):
            result = service.send(kind, "ann", " hi ")
            self.assertEqual(result["channel"], kind)
            self.assertTrue(result["ok"])
        self.assertEqual([s[:3] for s in channels.SENT],
                         [("email", "ann", "hi"), ("sms", "ann", "hi"), ("push", "ann", "hi")])

    def test_limits(self):
        with self.assertRaises(ValueError):
            service.send("sms", "ann", "x" * 21)
        service.send("email", "ann", "x" * 100)
        with self.assertRaises(ValueError):
            service.send("fax", "ann", "x")

    def test_cost_and_retries(self):
        self.assertEqual(service.cost_cents("sms", 3), 12)
        self.assertEqual(service.cost_cents("email", 3), 0)
        self.assertEqual(service.send("sms", "ann", "hi")["retries"], 2)

    def test_bulk(self):
        out = service.send_bulk("push", ["a", "b"], "hi")
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["cost_each"], 1)


if __name__ == "__main__":
    unittest.main()
''',
    "README.md": "# notify\n\nSends email, SMS and push messages through one gateway. Run tests: `python -m unittest`.\n",
}
# Later commits: each new limit is edited in settings.py and service.py together.
HISTORY = [("Raise push limit", "PUSH_LIMIT = 300", "PUSH_LIMIT = 500", "> 300", "> 500"),
           ("Lower sms limit", "SMS_LIMIT = 40", "SMS_LIMIT = 20", "> 40", "> 20"),
           ("Raise email limit", "EMAIL_LIMIT = 80", "EMAIL_LIMIT = 100", "> 80", "> 100")]


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def main():
    repo = Path(sys.argv[1]) / "py-notify"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    files = dict(FILES)
    for _, old_setting, new_setting, old_check, new_check in HISTORY:  # start from the oldest values
        files["notify/settings.py"] = files["notify/settings.py"].replace(new_setting, old_setting)
        files["notify/service.py"] = files["notify/service.py"].replace(new_check, old_check)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Notification service")
    for message, old_setting, new_setting, old_check, new_check in HISTORY:
        for rel, old, new in (("notify/settings.py", old_setting, new_setting), ("notify/service.py", old_check, new_check)):
            path = repo / rel
            path.write_text(path.read_text().replace(old, new))
        git(repo, "commit", "-qam", message)
    assert all((repo / rel).read_text() == text for rel, text in FILES.items()), "history does not end at FILES"
    print(repo)


if __name__ == "__main__":
    main()
