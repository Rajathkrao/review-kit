"""Partner timestamps: ISO 8601 with offset, or epoch seconds."""
from datetime import datetime, timezone


def parse_ts(text) -> datetime:
    """Return an aware UTC datetime. Raises ValueError for anything else."""
    if isinstance(text, (int, float)):
        return datetime.fromtimestamp(text, tz=timezone.utc)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"missing timestamp: {text!r}")
    text = text.strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without offset: {text!r}")
    return dt.astimezone(timezone.utc)
