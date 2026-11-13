import jobs.handlers  # noqa: F401
from jobs.registry import HANDLERS, LEGACY_KINDS, lookup


def test_legacy_kinds_are_registered():
    for legacy in LEGACY_KINDS:
        assert lookup(legacy) is not None


def test_current_kinds():
    for kind in ("email.send", "webhook.deliver", "report.export"):
        assert kind in HANDLERS
