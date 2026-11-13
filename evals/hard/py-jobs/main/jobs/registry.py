from typing import Awaitable, Callable

from .models import Job

Handler = Callable[[Job], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}


class UnknownKind(LookupError):
    pass


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        if kind in HANDLERS:
            raise ValueError(f"duplicate handler for {kind}")
        HANDLERS[kind] = fn
        return fn
    return deco


def lookup(kind: str) -> Handler:
    try:
        return HANDLERS[kind]
    except KeyError:
        raise UnknownKind(kind) from None
