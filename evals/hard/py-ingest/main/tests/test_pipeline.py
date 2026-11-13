from datetime import datetime, timezone

import pytest

from ingest.pipeline import process
from ingest.timeparse import parse_ts


def test_parse_ts():
    assert parse_ts("2026-09-01T10:00:00Z") == datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    assert parse_ts("2026-09-01T12:00:00+02:00") == datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    assert parse_ts(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["", "   ", None, "2026-09-01T10:00:00", "yesterday"])
def test_parse_ts_rejects(bad):
    with pytest.raises(ValueError):
        parse_ts(bad)


def test_process_sorts_and_dead_letters():
    res = process([
        {"tenant": "t1", "ts": "2026-09-01T11:00:00Z", "kind": "click"},
        {"tenant": "t1", "ts": "2026-09-01T10:00:00Z", "kind": "view"},
        {"tenant": "t1", "kind": "view"},
        {"tenant": "t1", "ts": "nope", "kind": "view"},
    ])
    assert [e.kind for e in res.events] == ["view", "click"]
    assert len(res.dead) == 2
