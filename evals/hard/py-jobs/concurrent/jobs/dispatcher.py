"""Concurrent dispatcher (docs/dispatch.md): claim due jobs, run up to `concurrency` at once,
ack / retry / fail, and drain on shutdown."""
import asyncio
import logging
import signal
from datetime import datetime, timedelta

from .clock import utcnow
from .models import Job
from .registry import lookup

log = logging.getLogger(__name__)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** attempts * 5, 3600))


class Dispatcher:
    def __init__(self, queue, concurrency: int = 20, batch_size: int = 10,
                 poll_interval: float = 1.0, drain_timeout: float = 30.0):
        self.queue = queue
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.drain_timeout = drain_timeout
        self._slots = asyncio.Semaphore(concurrency)
        self._stopping = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        self.processed = 0

    def stop(self) -> None:
        self._stopping.set()

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop)

    async def run(self, once: bool = False) -> None:
        """Dispatch until stop() is called (or after one batch with once=True), then drain."""
        while not self._stopping.is_set():
            jobs = await self.queue.claim(self.batch_size, datetime.utcnow())
            if not jobs:
                if once:
                    break
                await asyncio.sleep(self.poll_interval)
                continue
            for job in jobs:
                if self._stopping.is_set():
                    await self.queue.release(job)
                    continue
                await self._slots.acquire()
                asyncio.create_task(self._run(job))
            if once:
                break
        await self._drain()

    async def _drain(self) -> None:
        if not self._inflight:
            return
        log.info("draining %d running jobs", len(self._inflight))
        done, pending = await asyncio.wait(self._inflight, timeout=self.drain_timeout)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, job: Job) -> None:
        try:
            await asyncio.wait_for(lookup(job.kind)(job), timeout=job.timeout)
        except asyncio.CancelledError:
            await self.queue.release(job)
            raise
        except Exception as exc:
            await self._retry_or_fail(job, exc)
        else:
            await self.queue.ack(job)
        finally:
            self.processed += 1
            self._slots.release()

    async def _retry_or_fail(self, job: Job, exc: Exception) -> None:
        err = f"{type(exc).__name__}: {exc}"
        if job.attempts + 1 >= job.max_attempts:
            log.error("job %s failed permanently: %s", job.id, err)
            await self.queue.fail(job, err)
        else:
            await self.queue.retry(job, utcnow() + backoff(job.attempts), err)


async def main(queue) -> None:
    d = Dispatcher(queue)
    d.install_signal_handlers()
    await d.run()
