import pytest

from jobs.registry import HANDLERS


@pytest.fixture(autouse=True)
def test_handlers():
    calls = []

    async def ok(job):
        calls.append(job.id)

    async def boom(job):
        raise RuntimeError("nope")

    HANDLERS["test.ok"] = ok
    HANDLERS["test.boom"] = boom
    yield calls
    HANDLERS.pop("test.ok"); HANDLERS.pop("test.boom")
