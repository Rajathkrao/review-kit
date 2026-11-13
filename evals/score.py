#!/usr/bin/env python3
"""Keyword scoring of a review report against evals/answer-keys.json. A first pass only:
always read the report too.

    score.py REPORT.md CASE_KEY            score one report (CASE_KEY like "py-jobs:feature/concurrent-dispatch")
    score.py --suite TAG                   summarise every runs/TAG__<fixture>__<branch>/ made by run_hard.sh
    score.py --suite TAG --json            the same, as JSON

Each expected defect is classified as
  reported   a finding block names the file (basename) and one of the defect's keywords
  dismissed  it only appears in a section for dropped / dismissed / not-reported candidates
             (so a report that lists what its verifier threw away gets no credit for those)
  missed     neither
Sections are found by Markdown headings or bold-only lines; anything under a heading that
matches DISMISSED_HEAD counts as dismissed, "Spec compliance" / PR-comment tables count as
neither. Finding blocks are also counted (with severity) to measure false alarms on clean cases.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = json.loads((HERE / "answer-keys.json").read_text())

FILE_RE = re.compile(r"[\w/.-]+\.(tsx?|jsx?|cs|py|html|cshtml|razor|go|java|scss|css|json|ya?ml|md|txt)\b")
HEAD_RE = re.compile(r"^(#{1,6}\s+.+|\*\*[^*\n]+\*\*:?\s*)$")
DISMISSED_HEAD = re.compile(r"not reported|dismiss|dropped|rejected|false.positive|lower confidence|declined|"
                            r"ruled out|filtered|discarded|not a bug|considered|what was not|refuted|withdrawn", re.I)
OTHER_HEAD = re.compile(r"spec compliance|requirement|existing pr comments|verification|scope|checked against|"
                        r"execution|summary|verdict|walkthrough|test plan", re.I)
FINDING_HEAD = re.compile(r"finding|issue|problem|bug|critical|important|minor|high|medium|low", re.I)
BLOCK_SPLIT = re.compile(r"\n(?=\*\*\d+\.|\d+\.\s|#{2,4}\s*\d|\*\*(?:Critical|Important|Minor|Nit|FYI|High|Medium|Low)\b|"
                         r"- \*\*(?:Critical|Important|Minor)|\|\s*\d+\s*\|)")
SEV_RE = re.compile(r"\b(Critical|Important|Minor|Nit|FYI|High|Medium|Low)\b", re.I)


def sections(report: str):
    """Yield (kind, text) where kind is 'findings', 'dismissed' or 'other'."""
    kind, buf = "findings", []
    for line in report.splitlines():
        stripped = line.strip()
        if HEAD_RE.match(stripped) and not SEV_RE.match(stripped.strip("*# ").split(":")[0]) \
                and not re.match(r"^(#{1,6}\s*)?\**\s*\d+\.", stripped):
            title = stripped.strip("#* :")
            new = ("dismissed" if DISMISSED_HEAD.search(title) else
                   "other" if OTHER_HEAD.search(title) and not FINDING_HEAD.search(title) else
                   "findings" if FINDING_HEAD.search(title) else None)
            if new is not None:
                yield kind, "\n".join(buf)
                kind, buf = new, []
        buf.append(line)
    yield kind, "\n".join(buf)


def finding_blocks(text: str) -> list[str]:
    return [b for b in BLOCK_SPLIT.split(text) if b and FILE_RE.search(b)]


def dismissed_blocks(text: str) -> list[str]:
    return [b for b in re.split(r"\n(?=\s*[-*]\s|\s*\d+\.\s|\|)", text) if b.strip()]


def hit(item, block: str) -> bool:
    bl = block.lower()
    return Path(item["file"]).name.lower() in bl and any(k.lower() in bl for k in item["keys"])


def severity(block: str) -> str:
    m = SEV_RE.search(block)
    return m.group(1).lower() if m else "unknown"


def score(report: str, key: dict) -> dict:
    found, dismissed = [], []
    for kind, text in sections(report):
        if kind == "findings":
            found += finding_blocks(text)
        elif kind == "dismissed":
            dismissed += dismissed_blocks(text)

    def classify(item):
        if any(hit(item, b) for b in found):
            return "reported"
        if any(hit(item, b) for b in dismissed):
            return "dismissed"
        return "missed"

    must = {i["id"]: classify(i) for i in key["must_find"]}
    nice = {i["id"]: classify(i) for i in key.get("nice_to_find", [])}
    bait = {i["id"]: classify(i) for i in key.get("bait", [])}
    sevs: dict[str, int] = {}
    for b in found:
        sevs[severity(b)] = sevs.get(severity(b), 0) + 1
    out = {"finding_blocks": len(found), "severities": sevs,
           "recall": f"{sum(v == 'reported' for v in must.values())}/{len(must)}",
           "must_find": must, "nice": nice, "bait_reported": [k for k, v in bait.items() if v == "reported"]}
    if key.get("clean"):
        # Any reported critical/important block on a correct change is a false alarm.
        out["false_alarms"] = sum(n for s, n in sevs.items() if s in ("critical", "important", "high", "medium", "unknown"))
    return out


def run_meta(run_dir: Path) -> dict:
    try:
        st = json.loads((run_dir / "status.json").read_text())
    except (OSError, ValueError):
        return {}
    return {k: st.get(k) for k in ("execution_status", "seconds", "cost_usd", "num_turns", "reason")}


def suite(tag: str, as_json: bool) -> None:
    runs = sorted((HERE / "runs").glob(f"{tag}__*"))
    by_slug = {k.replace("/", "_").replace(":", "__"): k for k in KEYS}
    rows = []
    for rd in runs:
        case = by_slug.get(rd.name[len(tag) + 2:])
        if case is None:
            continue
        meta = run_meta(rd)
        rep = rd / "report.md"
        res = score(rep.read_text(), KEYS[case]) if rep.is_file() else {"error": "no report.md"}
        rows.append({"case": case, **meta, **res})
    if as_json:
        print(json.dumps(rows, indent=1))
        return
    tot_must = tot_rep = tot_dis = fa = 0
    secs = cost = 0.0
    print(f"| case | recall | dismissed | false alarms | time | cost |\n|---|---|---|---|---|---|")
    for r in rows:
        if "error" in r:
            print(f"| {r['case']} | {r.get('execution_status') or 'error'}: {r.get('reason') or r['error']} | | | | |")
            continue
        must = r["must_find"]
        rep = sum(v == "reported" for v in must.values())
        dis = [k for k, v in must.items() if v == "dismissed"]
        tot_must += len(must); tot_rep += rep; tot_dis += len(dis)
        fa += r.get("false_alarms", 0)
        secs += r.get("seconds") or 0; cost += r.get("cost_usd") or 0
        print(f"| {r['case']} | {r['recall'] if must else 'clean'} | {', '.join(dis) or '-'} | "
              f"{r.get('false_alarms', '-')} | {r.get('seconds', '?')} s | ${(r.get('cost_usd') or 0):.2f} |")
    print(f"| **total** | **{tot_rep}/{tot_must}** | {tot_dis} | {fa} | {secs:.0f} s | ${cost:.2f} |")


def main(argv):
    if len(argv) >= 2 and argv[0] == "--suite":
        return suite(argv[1], "--json" in argv)
    if len(argv) != 2:
        sys.exit(__doc__)
    print(json.dumps(score(Path(argv[0]).read_text(), KEYS[argv[1]]), indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
