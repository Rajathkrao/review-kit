#!/usr/bin/env python3
"""score.py <report.md> <case-key> : rough recall / false-alarm scoring against the answer key.
Splits the report into finding blocks, matches each expected defect by file basename + keyword.
Always double-check by reading the report; this is a first pass."""
import json, re, sys
from pathlib import Path

rep = Path(sys.argv[1]).read_text()
key = json.loads(Path(__file__).with_name('answer-keys.json').read_text())[sys.argv[2]]

# Keep only the findings part: up to "Spec compliance" / "Not reported" / "Lower confidence"
main = re.split(r"\n#+\s*(Spec compliance|Not reported|Lower confidence|Existing PR comments|What was not)", rep)[0]
blocks = re.split(r"\n(?=\*\*\d+\.|\d+\.\s|#{2,4}\s*\d|\*\*[A-Z][a-z]+:\*\*|- \*\*(Critical|Important|Minor))", main)
blocks = [b for b in blocks if b and re.search(r"[\w/.-]+\.(tsx?|jsx?|cs|py|html|cshtml|razor|go|java|scss|css|json|ya?ml)\b", b)]

def hit(item, b):
    base = Path(item['file']).name.lower()
    bl = b.lower()
    return base in bl and any(k.lower() in bl for k in item['keys'])

found = {i['id']: any(hit(i, b) for b in blocks) for i in key['must_find']}
nice = {i['id']: any(hit(i, b) for b in blocks) for i in key.get('nice_to_find', [])}
bait = {i['id']: any(hit(i, b) for b in blocks) for i in key.get('bait', [])}
print(json.dumps({"finding_blocks": len(blocks), "must_find": found,
                  "recall": f"{sum(found.values())}/{len(found)}", "nice": nice, "bait_hits": bait}, indent=1))
