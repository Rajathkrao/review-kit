import io
from datetime import datetime, timezone

from ingest.config import Settings
from ingest.dedupe import drop_duplicates
from ingest.export import export_tenant
from ingest.models import Event
from ingest.reader import rows_from_lines
from ingest.redact import redact
from ingest.sharding import partition_for
from ingest.store import Store

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def ev(i, tenant="t1", eid=None, body=""):
    return Event(tenant=tenant, ts=T0, kind="k", body=body, event_id=eid if eid is not None else str(i))


def test_reader_dead_letters_bad_lines():
    rows = list(rows_from_lines(io.StringIO('{"a": 1}\n\nnot json\n[1]\n')))
    assert rows[0] == {"a": 1}
    assert rows[1]["_error"].startswith("bad json")
    assert rows[2]["_error"] == "not an object"


def test_dedupe_keeps_first():
    a, b = ev(1), ev(2)
    out = drop_duplicates([a, b, ev(1, body="resent")])
    assert out == [a, b]


def test_dedupe_keeps_events_without_id():
    out = drop_duplicates([ev(1, eid=""), ev(2, eid="")])
    assert len(out) == 2


def test_redact():
    assert redact("contact bob@example.com now") == "contact [email] now"
    assert redact("card 4111 1111 1111 1111 ok") == "card [card] ok"
    assert redact("nothing here") == "nothing here"


def test_partition_is_stable_and_in_range():
    p = partition_for("tenant-42", 16)
    assert 0 <= p < 16
    assert all(partition_for("tenant-42", 16) == p for _ in range(100))


def test_settings_from_env():
    s = Settings.from_env({"INGEST_DRY_RUN": "1", "INGEST_PARTITIONS": "8", "INGEST_REDACT": "0"})
    assert s.dry_run and s.partitions == 8 and not s.redact
    assert not Settings.from_env({}).dry_run


def test_export_in_pages():
    st = Store()
    st.write_events([ev(i) for i in range(1000)], lambda t: 0)
    assert len(export_tenant(st, "t1", page_size=500)) == 1000


def test_count_events():
    st = Store()
    st.write_events([ev(1), ev(2, tenant="t2")], lambda t: 0)
    assert st.count_events() == 2 and st.count_events("t2") == 1
