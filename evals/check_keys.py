#!/usr/bin/env python3
"""Check the harder eval set: every hard fixture branch has an answer key, and every key item
that carries an `anchor` points at a line containing it on that branch.

    check_keys.py FIXTURES_DIR      (a folder built by build_hard_fixtures.py)
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
keys = json.loads((HERE / "answer-keys.json").read_text())
root = Path(sys.argv[1])
errors = []
for spec in sorted((HERE / "hard").glob("*/fixture.json")):
    fix = spec.parent.name
    for br in json.loads(spec.read_text())["branches"]:
        if f"{fix}:{br['name']}" not in keys:
            errors.append(f"no answer key for {fix}:{br['name']}")
for case, key in keys.items():
    if key.get("set") != "hard":
        continue
    fix, br = case.split(":", 1)
    for item in key["must_find"] + key.get("nice_to_find", []) + key.get("bait", []):
        if "anchor" not in item:
            continue
        text = subprocess.run(["git", "-C", str(root / fix), "show", f"{br}:{item['file']}"],
                              capture_output=True, text=True)
        if text.returncode:
            errors.append(f"{case} {item['id']}: {item['file']} not on branch")
            continue
        lines = text.stdout.splitlines()
        start, end = item["lines"]
        if not any(item["anchor"] in l for l in lines[start - 1:end]):
            errors.append(f"{case} {item['id']}: anchor {item['anchor']!r} not in {item['file']}:{start}-{end}")
    if key.get("clean") and key["must_find"]:
        errors.append(f"{case}: clean case with must_find items")
if errors:
    sys.exit("\n".join(errors))
print(f"answer keys ok for {sum(v.get('set') == 'hard' for v in keys.values())} hard cases")
