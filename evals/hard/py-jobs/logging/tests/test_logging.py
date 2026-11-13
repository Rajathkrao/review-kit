import asyncio
import logging

from jobs.dispatcher import Dispatcher, fields
from jobs.models import Job
from jobs.queue import InMemoryQueue
from jobs.registry import HANDLERS


async def ok(job):
    pass


async def boom(job):
    raise RuntimeError("nope")


HANDLERS.setdefault("log.ok", ok)
HANDLERS.setdefault("log.boom", boom)


async def run_once(q):
    d = Dispatcher(q, poll_interval=0.01)
    task = asyncio.create_task(d.run())
    await asyncio.sleep(0.05)
    d.stop()
    await task


def test_fields_do_not_clash_with_logrecord():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    assert not set(fields(Job("1", "k"), error="e")) & set(vars(record))


async def test_success_and_retry_are_logged(caplog):
    caplog.set_level(logging.INFO, logger="jobs.dispatcher")
    q = InMemoryQueue()
    await q.put(Job("1", "log.ok"))
    await q.put(Job("2", "log.boom"))
    await run_once(q)
    by_msg = {}
    for r in caplog.records:
        by_msg.setdefault(r.getMessage(), r)
    assert by_msg["job succeeded"].job_id == "1"
    assert by_msg["job succeeded"].duration_ms >= 0
    retry = by_msg["job failed, will retry"]
    assert (retry.job_id, retry.attempt, retry.retry_in_s) == ("2", 1, 5)
    assert retry.error == "RuntimeError: nope"
