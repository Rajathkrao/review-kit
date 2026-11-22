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
ICON = {"critical": "🔴", "important": "🟠", "minor": "🟡"}
RANK = {"critical": 0, "important": 1, "minor": 2}
VERDICT = {"dont-ship": "🔴 Don't merge yet", "ship-after-fixes": "🟠 Merge after fixes", "ship": "✅ Looks good to merge"}
EVIDENCE = {"source-verified": "confirmed by reading the code", "test-reproduced": "reproduced with a test"}
MARK = "<!-- review-kit"  # hidden marker so later runs can find their own comments
MAX_BODY = 60000          # GitHub rejects comment bodies over 65,536 characters
FIX_ONE = "Fix this code review finding. Write a failing test first if the project has tests, make the smallest change that removes the root cause, then run the closest tests."
FIX_ALL = "Fix these code review findings one at a time, most severe first. For each: write a failing test first if the project has tests, make the smallest change that removes the root cause, then run the closest tests. Do not commit."


def commentable_lines(diff_text):
    """Map path -> {line_no: hunk_index} for RIGHT-side lines present in the diff."""
    lines = {}
    path = None
    new_ln = None
    hunk = -1
    in_hunk = False
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            path, new_ln = None, None
            in_hunk = False
            continue
        if not in_hunk and raw.startswith("+++ "):
            p = raw[4:].strip()
            path = None if p == "/dev/null" else re.sub(r"^b/", "", p)
            continue
        if not in_hunk and raw.startswith("--- "):
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            new_ln = int(m.group(1))
            hunk += 1
            in_hunk = True
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


def fence(text, lang=""):
    """Code fence that survives backticks inside the text."""
    ticks = "`" * max(3, max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    return f"{ticks}{lang}\n{text.rstrip(chr(10))}\n{ticks}"


def where(f):
    ls, le = int(f["line_start"]), int(f.get("line_end") or f["line_start"])
    return f"{f['file']}:{ls}" + (f"-{le}" if le != ls else "")


def ext(f):
    """Language hint for a code fence, from the file extension."""
    return {"py": "python", "js": "js", "ts": "ts", "go": "go", "rs": "rust", "rb": "ruby",
            "java": "java", "sh": "bash"}.get(f["file"].rsplit(".", 1)[-1], "")


def agent_prompt(f):
    return "\n".join([f"{f.get('id') or SEV.get(f['severity'])}: {f['title'].strip()}",
                      f"Where: {where(f)}", f"Problem: {' '.join(f['body'].split())}",
                      f"Fix: {' '.join(f['recommendation'].split())}"])


def evidence_text(f):
    lines = [f"{f['evidence'].strip()}", "",
             f"Confidence {f.get('confidence')}/100, {EVIDENCE.get(f['evidence_status'], f['evidence_status'])}."]
    t = f.get("test_evidence") or {}
    if f["evidence_status"] == "test-reproduced" and t:
        lines += ["", f"Ran `{t.get('command')}` (exit {t.get('exit_code')}): {t.get('observed')}"]
    extra = []
    if f.get("found_by") and f["found_by"] != "claude":
        extra.append(f"found by {f['found_by']}")
    if f.get("lenses"):
        extra.append("lens: " + ", ".join(f["lenses"]))
    if f.get("contract_ref"):
        extra.append(f"breaks requirement {f['contract_ref']}")
    if extra:
        lines[-1] = lines[-1][:-1] + "; " + "; ".join(extra) + "."
    return "\n".join(lines)


def details(summary, inner):
    return f"<details>\n<summary>{summary}</summary>\n\n{inner}\n\n</details>"


def finding_body(f, exact_range=True):
    """Inline comment: severity and title, what breaks, the fix, then folded evidence and agent prompt."""
    sev = f.get("severity")
    parts = [f"{MARK} {f.get('id', '')} -->".replace("  ", " "),
             f"{ICON.get(sev, '⚪')} **{SEV.get(sev, 'Note')}** · {f['title'].strip()}", "",
             f["body"].strip(), "", f"**Fix:** {f['recommendation'].strip()}"]
    if f.get("suggestion"):
        # A suggestion block replaces exactly the commented lines; only offer the one-click
        # apply when the comment covers the finding's whole range, otherwise show it as code.
        if exact_range:
            parts += ["", fence(f["suggestion"], "suggestion")]
        else:
            parts += ["", f"Replacement for lines {f['line_start']}-{f['line_end']}:", "", fence(f["suggestion"], ext(f))]
    parts += ["", details("Evidence", evidence_text(f)),
              "", details("🤖 Prompt for AI agents", fence(FIX_ONE + "\n\n" + agent_prompt(f), "text"))]
    return "\n".join(parts)


def build(pkg: Path, write=True):
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

    inline, outside, inline_ids = [], [], set()
    findings = [f for f in fx.get("findings", []) if int(f.get("confidence", 0)) >= 80]
    findings.sort(key=lambda f: (RANK.get(f["severity"], 3), -float(f.get("confidence", 0))))
    for f in findings:
        if f["severity"] == "minor":
            continue  # minors are folded into the summary, not posted as inline noise
        path = f.get("file", "")
        ls, le = int(f.get("line_start") or 0), int(f.get("line_end") or f.get("line_start") or 0)
        avail = cl.get(path, {})
        end = le if le in avail else next((n for n in range(le, ls - 1, -1) if n in avail), None)
        if end is None:
            outside.append(f)
            continue
        start = ls if ls in avail and ls < end and avail[ls] == avail[end] else None
        exact = end == le and (start == ls or ls == le)
        c = {"path": path, "line": end, "side": "RIGHT", "body": finding_body(f, exact)}
        if start:
            c["start_line"] = start
            c["start_side"] = "RIGHT"
        inline.append(c)
        inline_ids.add(id(f))

    def link(f):
        ls, le = int(f["line_start"]), int(f.get("line_end") or f["line_start"])
        return f"https://github.com/{owner}/{repo}/blob/{head}/{f['file']}#L{max(1, ls - 1)}-L{le + 1}"

    verdict = VERDICT.get(fx.get("verdict"), "Review")
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

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEV}
    tally = " · ".join(f"{ICON[s]} {n} {SEV[s].lower()}" for s, n in counts.items() if n)
    body = [f"{MARK}:summary -->", f"## {verdict}", "", fx["summary"].strip(), ""]
    facts = [f"**Found:** {tally}" if findings else "**Found:** no issues"]
    if contract_src:
        facts.append(f"**Checked against:** {contract_src}")
    facts.append(f"**Tests:** {tests}")
    body += ["  \n".join(facts)]

    main = [f for f in findings if f["severity"] != "minor"]
    if main:
        rows = ["| | Issue | Where |", "|---|---|---|"]
        for f in main:
            spot = "inline" if id(f) in inline_ids else "outside the diff"
            title = f["title"].strip().replace("|", "\\|")
            rows.append(f"| {ICON[f['severity']]} | {title} | "
                        f"[`{where(f)}`]({link(f)}) · {spot} |")
        body += ["", "\n".join(rows)]

    out_main = [f for f in outside if f["severity"] != "minor"]
    if out_main:
        items = [f"**{ICON[f['severity']]} {f['title'].strip()}** · [`{where(f)}`]({link(f)})\n\n"
                 f"{f['body'].strip()}\n\n**Fix:** {f['recommendation'].strip()}"
                 + (f"\n\n{fence(f['suggestion'], ext(f))}" if f.get("suggestion") else "") for f in out_main]
        body += ["", details(f"Outside the lines this PR changed ({len(out_main)})", "\n\n---\n\n".join(items))]
    minors = [f for f in findings if f["severity"] == "minor"]
    if minors:
        items = [f"- **{f['title'].strip()}** · [`{where(f)}`]({link(f)}): {' '.join(f['body'].split())} "
                 f"Fix: {' '.join(f['recommendation'].split())}" for f in minors]
        body += ["", details(f"🟡 Minor ({len(minors)})", "\n".join(items))]
    endorse = fx.get("endorsed_comments", [])
    if endorse:
        # Names in code spans so the summary does not notify everyone it agrees with.
        items = [f"- `@{c.get('author')}` on `{c.get('where')}`: {c.get('why')}" for c in endorse]
        body += ["", details(f"Agree with existing comments ({len(endorse)})", "\n".join(items))]
    if findings:
        prompt = FIX_ALL + "\n\n" + "\n\n".join(agent_prompt(f) for f in findings)
        body += ["", details("🤖 Prompt to fix all with an AI agent", fence(prompt, "text"))]
    else:
        body += ["", "Checked for bugs, contract compliance and error handling."]
    ver = f" v{meta['rk_version']}" if meta.get("rk_version") else ""
    body += ["", f"<sub>review-kit{ver} · commit {head[:7]} · "
                 "react 👍 or 👎 to say if this helped</sub>"]
    text = "\n".join(body)
    if len(text) > MAX_BODY:
        text = text[:MAX_BODY] + "\n\n…(cut to fit GitHub's comment limit; full review in review.html)"

    payload = {"commit_id": head, "event": "COMMENT", "body": text, "comments": inline}
    preview = [f"# Review to post on {owner}/{repo}#{num} (commit {head[:10]})", "", "## Summary comment", "",
               payload["body"], ""]
    for c in inline:
        rng = f"{c.get('start_line', c['line'])}-{c['line']}" if c.get("start_line") else str(c["line"])
        preview += [f"## Inline: {c['path']}:{rng}", "", c["body"], ""]
    if write:
        (pkg / "review-payload.json").write_text(json.dumps(payload, indent=2))
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
    approved = load_object(pkg / "review-payload.json") if a.submit else None
    payload, (owner, repo, num, head) = build(pkg, write=not a.submit)
    if a.submit and payload != approved:
        raise ValueError("Review changed since preview; rebuild and approve the new preview before submitting")

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
