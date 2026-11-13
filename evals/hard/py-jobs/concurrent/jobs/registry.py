from typing import Awaitable, Callable

from .models import Job

Handler = Callable[[Job], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}

# Kinds renamed in 2.0 that old producers still send (docs/dispatch.md #6).
LEGACY_KINDS = {
    "mail": "email.send",
    "hook": "webhook.deliver",
    "export": "report.export",
}


class UnknownKind(LookupError):
    pass


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        if kind in HANDLERS:
            raise ValueError(f"duplicate handler for {kind}")
        HANDLERS[kind] = fn
        return fn
    return deco


def register_legacy_aliases() -> None:
    """Route legacy kinds to the current handler. Call after all handlers are imported."""
    for legacy, current in LEGACY_KINDS.items():
        if current not in HANDLERS:
            raise UnknownKind(current)
        HANDLERS[legacy] = lambda job: HANDLERS[current](job)


def lookup(kind: str) -> Handler:
    try:
        return HANDLERS[kind]
    except KeyError:
        raise UnknownKind(kind) from None
