"""Partner timestamps: ISO 8601 with offset, or epoch seconds."""
from datetime import datetime, timezone


def parse_ts(text) -> datetime | None:
    """Return an aware UTC datetime, or None when the partner sent no timestamp (heartbeat rows).
    Raises ValueError for a timestamp that is present but unusable."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return datetime.fromtimestamp(text, tz=timezone.utc)
    if not isinstance(text, str):
        raise ValueError(f"bad timestamp: {text!r}")
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without offset: {text!r}")
    return dt.astimezone(timezone.utc)
