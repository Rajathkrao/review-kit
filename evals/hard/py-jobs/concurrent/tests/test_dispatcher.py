import asyncio
from datetime import datetime, timedelta

from jobs.dispatcher import Dispatcher
from jobs.models import Job
from jobs.queue import InMemoryQueue
from jobs.registry import HANDLERS


async def test_ack_and_retry(test_handlers):
    q = InMemoryQueue()
    await q.put(Job("1", "test.ok"))
    await q.put(Job("2", "test.boom"))
    await Dispatcher(q).run(once=True)
    await asyncio.sleep(0.01)
    assert q.done == ["1"]
    assert q._ready[0].attempts == 1


async def test_fails_after_max_attempts():
    q = InMemoryQueue()
    await q.put(Job("3", "test.boom", attempts=4))
    await Dispatcher(q).run(once=True)
    await asyncio.sleep(0.01)
    assert [j.id for j in q.failed] == ["3"]


async def test_future_jobs_are_not_claimed(test_handlers):
    q = InMemoryQueue()
    await q.put(Job("later", "test.ok", run_at=datetime.utcnow() + timedelta(hours=1)))
    await q.put(Job("now", "test.ok"))
    await Dispatcher(q).run(once=True)
    await asyncio.sleep(0.01)
    assert test_handlers == ["now"]
    assert [j.id for j in q._ready] == ["later"]


async def test_runs_jobs_concurrently():
    started = asyncio.Event()
    release = asyncio.Event()
    running = 0
    peak = 0

    async def slow(job):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        started.set()
        await release.wait()
        running -= 1

    HANDLERS["test.slow"] = slow
    try:
        q = InMemoryQueue()
        for i in range(5):
            await q.put(Job(str(i), "test.slow"))
        d = Dispatcher(q, concurrency=3)
        runner = asyncio.create_task(d.run(once=True))
        await started.wait()
        await asyncio.sleep(0.01)
        assert peak == 3
        release.set()
        await runner
        await asyncio.sleep(0.01)
        assert len(q.done) == 5
    finally:
        HANDLERS.pop("test.slow")


async def test_timeout_is_retried():
    async def hang(job):
        await asyncio.sleep(10)

    HANDLERS["test.hang"] = hang
    try:
        q = InMemoryQueue()
        await q.put(Job("h", "test.hang", timeout=0.01))
        await Dispatcher(q).run(once=True)
        await asyncio.sleep(0.05)
        assert q._ready[0].last_error.startswith("TimeoutError")
    finally:
        HANDLERS.pop("test.hang")
