"""Dependency-free validation at review output boundaries."""
import json
import math
import sys
from pathlib import Path


def load_object(path, optional=False):
    path = Path(path)
    if optional and not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_schema(value, schema, where="output"):
    """Validate the subset used by the bundled Codex schema (not general JSON Schema)."""
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "number": (int, float)}
    kind = schema.get("type")
    if kind in kinds and (not isinstance(value, kinds[kind]) or
                          kind in ("integer", "number") and isinstance(value, bool)):
        raise ValueError(f"{where}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: invalid value {value!r}")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        extra = value.keys() - schema.get("properties", {}).keys()
        if missing or schema.get("additionalProperties") is False and extra:
            raise ValueError(f"{where}: missing {sorted(missing)}, unexpected {sorted(extra)}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate_schema(value[key], sub, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{where}[{index}]")
    elif isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise ValueError(f"{where}: empty string")
    elif isinstance(value, (int, float)):
        if not math.isfinite(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{where}: number outside allowed range")


def validate_codex(value):
    schema = load_object(Path(__file__).resolve().parent.parent / "assets/codex-review-schema.json")
    validate_schema(value, schema)
    if value["verdict"] == "approve" and value["findings"]:
        raise ValueError("Codex approval contradicts nonempty findings")
    if value["verdict"] == "needs-attention" and not value["findings"]:
        raise ValueError("Codex needs-attention result must identify a material finding")
    for finding in value["findings"]:
        if finding["line_end"] < finding["line_start"]:
            raise ValueError("Codex finding has a reversed line range")
    return value


def validate_review(value, meta=None):
    statuses = ("completed", "partial", "failed", "nothing-to-review")
    status = value.get("execution_status")
    if status not in statuses:
        raise ValueError("findings.json requires execution_status: " + ", ".join(statuses))
    if meta and meta.get("size") == "empty" and status != "nothing-to-review":
        raise ValueError("Empty collected scopes require execution_status nothing-to-review")
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        raise ValueError("findings.json requires a nonempty summary")
    findings = value.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings.json requires a findings array")
    for finding in findings:
        validate_schema(finding, {"type": "object", "required": [
            "title", "body", "file", "line_start", "line_end", "severity", "confidence",
            "recommendation", "evidence", "evidence_status"], "properties": {
                **{k: {"type": "string", "minLength": 1} for k in
                   ("title", "body", "file", "recommendation", "evidence")},
                "line_start": {"type": "integer", "minimum": 1},
                "line_end": {"type": "integer", "minimum": 1},
                "severity": {"enum": ["critical", "important", "minor"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 100},
                "evidence_status": {"enum": ["source-verified", "test-reproduced", "unverified"]}}})
        if finding["line_end"] < finding["line_start"]:
            raise ValueError("Finding has a reversed line range")
        if status == "completed" and finding["evidence_status"] == "unverified":
            raise ValueError("Unverified findings require a partial review")
        if finding["evidence_status"] == "test-reproduced":
            test = finding.get("test_evidence")
            validate_schema(test, {"type": "object", "required": [
                "command", "exit_code", "observed", "setup_succeeded", "target_exercised"],
                "properties": {
                    "command": {"type": "string", "minLength": 1},
                    "exit_code": {"type": "integer", "minimum": 0},
                    "observed": {"type": "string", "minLength": 1}}}, "test_evidence")
            if test["setup_succeeded"] is not True or test["target_exercised"] is not True:
                raise ValueError("Test reproduction requires successful setup and target exercise")
    if status != "completed":
        if value.get("verdict") != "inconclusive":
            raise ValueError("Incomplete reviews require verdict inconclusive")
        if status in ("failed", "nothing-to-review") and findings:
            raise ValueError(f"{status} cannot include findings")
    else:
        if meta and meta.get("collection_status") in ("partial", "failed"):
            raise ValueError("Incomplete collection cannot produce a completed review")
        kept = [f for f in findings if f["confidence"] >= 80]
        expected = ("dont-ship" if any(f["severity"] == "critical" for f in kept) else
                    "ship-after-fixes" if any(f["severity"] == "important" for f in kept) else "ship")
        if value.get("verdict") != expected:
            raise ValueError(f"Verdict must be {expected} for the verified findings")
    return value

def main():
    if len(sys.argv) != 2:
        sys.exit("usage: review_data.py PKG")
    pkg = Path(sys.argv[1])
    try:
        data = validate_review(load_object(pkg / "findings.json"), load_object(pkg / "meta.json"))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.exit(f"Review validation failed: {exc}")
    print(f"Review valid: {data['execution_status']}")


if __name__ == "__main__":
    main()
