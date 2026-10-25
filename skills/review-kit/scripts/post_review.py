#!/usr/bin/env python3
"""Build (and optionally submit) a GitHub PR review from PKG/findings.json.

  post_review.py PKG                     build payload + preview, print preview (no network writes)
  post_review.py PKG --submit            submit the review (event COMMENT) with inline comments
  post_review.py PKG --reply ID --body-file F   reply in an existing review thread

Findings whose lines are not in the PR diff go into the review body with links.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from review_data import load_object, validate_review

SEV = {"critical": "Critical", "important": "Important", "minor": "Minor"}


def commentable_lines(diff_text):
    """Map path -> {line_no: hunk_index} for RIGHT-side lines present in the diff."""
    lines = {}
    path = None
    new_ln = None
    hunk = -1
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            path, new_ln = None, None
            continue
        if raw.startswith("+++ "):
            p = raw[4:].strip()
            path = None if p == "/dev/null" else re.sub(r"^b/", "", p)
            continue
        if raw.startswith("--- "):
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            new_ln = int(m.group(1))
            hunk += 1
            continue
        if path is None or new_ln is None:
            continue
        if raw.startswith("+") or raw.startswith(" "):
            lines.setdefault(path, {})[new_ln] = hunk
            new_ln += 1
        elif raw.startswith("-"):
            pass
        elif raw.startswith("\\"):
            pass
    return lines


def finding_body(f):
    parts = [f"**{SEV.get(f.get('severity'), 'Note')}:** {f.get('title','').strip()}", "",
             f.get("body", "").strip()]
    if f.get("recommendation"):
        parts += ["", f"**Suggested fix:** {f['recommendation'].strip()}"]
    if f.get("suggestion"):
        parts += ["", "```suggestion", f["suggestion"].rstrip("\n"), "```"]
    bits = [f"confidence {f.get('confidence')}"]
    bits.append(f"evidence: {f['evidence_status']}")
    if f.get("found_by") and f["found_by"] != "claude":
        bits.append(f"found by {f['found_by']}")
    parts += ["", f"<sub>review-kit · {' · '.join(bits)}</sub>"]
    return "\n".join(parts)


def build(pkg: Path):
    meta = load_object(pkg / "meta.json")
    fx = validate_review(load_object(pkg / "findings.json"), meta)
    if fx["execution_status"] != "completed":
        raise ValueError("Only completed reviews can be posted")
    pr = json.loads((pkg / "pr.json").read_text())
    gh = meta.get("github") or {}
    head = pr["headRefOid"]
    if meta.get("reviewed_commit", head) != head:
        raise ValueError("Reviewed commit does not match the PR payload")
    diff = (pkg / "pr-github.diff").read_text() if (pkg / "pr-github.diff").exists() else (pkg / "diff.patch").read_text()
    cl = commentable_lines(diff)
    owner, repo, num = gh.get("owner"), gh.get("repo"), gh.get("pr")

    inline, outside = [], []
    findings = [f for f in fx.get("findings", []) if int(f.get("confidence", 0)) >= 80]
    for f in findings:
        path = f.get("file", "")
        ls, le = int(f.get("line_start") or 0), int(f.get("line_end") or f.get("line_start") or 0)
        avail = cl.get(path, {})
        end = le if le in avail else next((n for n in range(le, ls - 1, -1) if n in avail), None)
        if end is None:
            outside.append(f)
            continue
        c = {"path": path, "line": end, "side": "RIGHT", "body": finding_body(f)}
        start = ls if ls in avail and ls < end and avail[ls] == avail[end] else None
        if start:
            c["start_line"] = start
            c["start_side"] = "RIGHT"
        inline.append(c)

    def link(f):
        ls, le = f.get("line_start"), f.get("line_end") or f.get("line_start")
        lo, hi = max(1, int(ls) - 1), int(le) + 1
        return f"https://github.com/{owner}/{repo}/blob/{head}/{f.get('file')}#L{lo}-L{hi}"

    verdict = {"dont-ship": "Don't ship yet", "ship-after-fixes": "Ship after fixes", "ship": "Ship"}.get(fx.get("verdict"), "Review")
    crit = sum(1 for f in findings if f.get("severity") == "critical")
    imp = sum(1 for f in findings if f.get("severity") == "important")
    contract_src = ""
    cpath = pkg / "contract.md"
    if cpath.exists():
        m = re.search(r"^Source:\s*(.+)$", cpath.read_text(), re.M)
        contract_src = m.group(1).strip() if m else ""
    tests = "not run"
    tpath = pkg / "test-results.md"
    if tpath.exists():
        m = re.search(r"## Summary\s*\n(.+)", tpath.read_text())
        tests = m.group(1).strip() if m else "see review"
    body = ["### Code review (review-kit)", "",
            f"**Verdict:** {verdict} — {fx.get('summary','').strip()}"]
    if contract_src:
        body.append(f"**Checked against:** {contract_src}")
    body.append(f"**Verification:** {tests}")
    body += ["", f"Found {len(findings)} issue{'s' if len(findings) != 1 else ''} ({crit} critical, {imp} important)." +
             (" Inline comments below." if inline else "")]
    endorse = fx.get("endorsed_comments", [])
    if endorse:
        body += ["", "Agree with existing comments:", ""] + [f"- @{c.get('author')} on `{c.get('where')}`: {c.get('why')}" for c in endorse]
    if outside:
        body += ["", "Issues outside the lines changed in this PR:", ""]
        for i, f in enumerate(outside, 1):
            body.append(f"{i}. **{SEV.get(f.get('severity'),'Note')}:** {f.get('title')} — {f.get('body','').strip()} "
                        f"**Fix:** {f.get('recommendation','').strip()}\n\n   {link(f)}")
    if not findings:
        body += ["", "No issues found. Checked for bugs, contract compliance and error handling."]
    body += ["", "<sub>Generated with review-kit for Claude Code. React 👍 / 👎 to tell us if this was useful.</sub>"]

    payload = {"commit_id": head, "event": "COMMENT", "body": "\n".join(body), "comments": inline}
    (pkg / "review-payload.json").write_text(json.dumps(payload, indent=2))
    preview = [f"# Review to post on {owner}/{repo}#{num} (commit {head[:10]})", "", "## Summary comment", "",
               payload["body"], ""]
    for c in inline:
        rng = f"{c.get('start_line', c['line'])}-{c['line']}" if c.get("start_line") else str(c["line"])
        preview += [f"## Inline: {c['path']}:{rng}", "", c["body"], ""]
    (pkg / "review-preview.md").write_text("\n".join(preview))
    return payload, (owner, repo, num, head)


def gh_api(args, input_obj=None):
    p = subprocess.run(["gh", "api", *args] + (["--input", "-"] if input_obj is not None else []),
                       input=json.dumps(input_obj) if input_obj is not None else None,
                       capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"gh api failed: {p.stderr.strip()}")
    return json.loads(p.stdout or "{}")


def check_eligible(owner, repo, num, head):
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(num), "--repo", f"{owner}/{repo}",
             "--json", "headRefOid,state"], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ValueError(f"PR eligibility lookup failed: {result.stderr.strip()}")
        pr = json.loads(result.stdout)
        if not isinstance(pr, dict) or not all(pr.get(k) for k in ("headRefOid", "state")):
            raise ValueError("PR eligibility response lacks head/state")
        if pr["headRefOid"] != head:
            raise ValueError("PR head moved since review; re-run before posting")
        if pr["state"] != "OPEN":
            raise ValueError(f"PR is {pr['state']}; not posting")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Cannot verify PR eligibility: {exc}") from exc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pkg")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--reply", type=int)
    ap.add_argument("--body-file")
    a = ap.parse_args()
    pkg = Path(a.pkg)
    payload, (owner, repo, num, head) = build(pkg)

    if a.reply:
        check_eligible(owner, repo, num, head)
        if not a.body_file:
            sys.exit("--reply needs --body-file")
        body = Path(a.body_file).read_text()
        r = gh_api(["-X", "POST", f"repos/{owner}/{repo}/pulls/{num}/comments/{a.reply}/replies"], {"body": body})
        print(r.get("html_url", "reply posted"))
        return
    if not a.submit:
        print((pkg / "review-preview.md").read_text())
        print(f"\n[payload: {pkg/'review-payload.json'} · {len(payload['comments'])} inline comments · not posted]")
        return
    check_eligible(owner, repo, num, head)
    r = gh_api(["-X", "POST", f"repos/{owner}/{repo}/pulls/{num}/reviews"], payload)
    print(r.get("html_url", "review posted"))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        sys.exit(f"Review posting failed: {exc}")
