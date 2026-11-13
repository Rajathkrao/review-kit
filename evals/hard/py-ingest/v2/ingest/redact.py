"""Remove personal data from event bodies before storage (docs/ingest-v2.md #4)."""
import re

EMAIL = r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}"
CARD = r"\b(?:\d[ -]?){12,18}\d\b"


def redact(text: str) -> str:
    text = re.sub(EMAIL, "[email]", text, re.IGNORECASE)
    text = re.sub(CARD, "[card]", text)
    return text
