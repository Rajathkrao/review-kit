"""Read partner NDJSON files."""
import json
from typing import Iterable, Iterator


def parse_line(line: str) -> dict:
    """One NDJSON line. A malformed line becomes {'_raw': ..., '_error': ...} so it is dead-lettered."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"_raw": line.rstrip("\n"), "_error": f"bad json: {exc.msg}"}
    if not isinstance(row, dict):
        return {"_raw": line.rstrip("\n"), "_error": "not an object"}
    return row


def rows_from_lines(lines: Iterable[str]) -> Iterator[dict]:
    return (parse_line(line) for line in lines if line.strip())


def read_ndjson(path: str) -> Iterator[dict]:
    """Stream a partner file row by row; files can be several GB, so never read them whole."""
    with open(path, encoding="utf-8") as fh:
        return rows_from_lines(fh)
