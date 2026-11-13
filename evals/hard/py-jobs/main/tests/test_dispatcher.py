import asyncio

from jobs.dispatcher import Dispatcher
from jobs.models import Job
from jobs.queue import InMemoryQueue
from jobs.registry import HANDLERS

calls = []


async def ok(job):
    calls.append(job.id)


async def boom(job):
    raise RuntimeError("nope")


HANDLERS.setdefault("test.ok", ok)
HANDLERS.setdefault("test.boom", boom)


async def run_once(q):
    d = Dispatcher(q, poll_interval=0.01)
    task = asyncio.create_task(d.run())
    await asyncio.sleep(0.05)
    d.stop()
    await task


async def test_ack_and_retry():
    q = InMemoryQueue()
    await q.put(Job("1", "test.ok"))
    await q.put(Job("2", "test.boom"))
    await run_once(q)
    assert q.done == ["1"]
    job2 = (q._ready + q.failed)[0]
    assert job2.id == "2" and job2.attempts >= 1


async def test_fails_after_max_attempts():
    q = InMemoryQueue()
    await q.put(Job("3", "test.boom", attempts=4))
    await run_once(q)
    assert [j.id for j in q.failed] == ["3"]
