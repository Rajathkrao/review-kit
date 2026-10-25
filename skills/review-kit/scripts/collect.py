#!/usr/bin/env python3
"""Build a review package for review-kit.

Resolves the review target (branch, range, commit, PR, path), writes the diff with
10 lines of context, file stats, commits, purpose-document candidates and project
instruction files into one directory, and prints that directory's path on the last
line of output.

Usage: collect.py [--target T] [--base REF] [--out DIR]
"""
import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONTEXT = "-U10"
INSTRUCTION_FILES = ["CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", ".editorconfig",
                     "REVIEW.md", ".github/copilot-instructions.md"]
ADR_DIRS = ["docs/adr", "docs/adrs", "docs/decisions", "doc/adr", "adr", "adrs",
            "Documentation/Decisions", "docs/architecture/decisions", "architecture/decisions"]
SPEC_PATTERNS = re.compile(r"(spec|plan|design|rfc|prd|requirements?|adr|decision)", re.I)


def run(cmd, cwd=None, check=False, input_text=None, timeout=120):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    try:
        p = subprocess.run(cmd, cwd=cwd, input=input_text, capture_output=True, text=True,
                           env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        p = subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")
    except OSError as exc:
        p = subprocess.CompletedProcess(cmd, 127, "", str(exc))
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {p.stderr.strip()}")
    return p


def git(*args, cwd=None, check=False):
    return run(["git", *args], cwd=cwd, check=check)


def out(*args, cwd=None):
    p = git(*args, cwd=cwd)
    return p.stdout.strip() if p.returncode == 0 else ""


def die(msg, code=2):
    print(f"review-kit collect: {msg}", file=sys.stderr)
    sys.exit(code)


def commit_ref(root, ref):
    return git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}",
               cwd=root, check=True).stdout.strip()


def empty_tree(root):
    return run(["git", "hash-object", "-w", "-t", "tree", "--stdin"], cwd=root,
               input_text="", check=True).stdout.strip()


def snapshot(root, head, pkg):
    """Keep the caller's HEAD/index/files intact and pin all context reads."""
    dest = pkg / "source"
    git("worktree", "add", "--detach", str(dest), head, cwd=root, check=True)
    return str(dest)


def no_index_diff(root, path):
    result = git("diff", "--no-index", CONTEXT, "--", "/dev/null", path, cwd=root)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Cannot read {path}: {result.stderr.strip()}")
    return result.stdout


def default_base(root):
    for cand in ("origin/HEAD",):
        ref = out("symbolic-ref", "--quiet", "--short", "refs/remotes/" + cand, cwd=root)
        if ref:
            return ref
    for cand in ("main", "master", "origin/main", "origin/master", "develop"):
        if git("rev-parse", "--verify", "--quiet", cand + "^{commit}", cwd=root).returncode == 0:
            return cand
    return None


def untracked_diff(root, paths_filter=None):
    files = out("ls-files", "--others", "--exclude-standard", cwd=root).splitlines()
    if paths_filter:
        files = [f for f in files if any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths_filter)]
    chunks = []
    for f in files:
        full = Path(root, f)
        try:
            if full.stat().st_size > 400_000:
                continue
        except OSError:
            continue
        chunks.append(no_index_diff(root, f))
    return "".join(chunks), files


def parse_pr_ref(target):
    m = re.fullmatch(r"#?(\d+)", target.strip())
    if m:
        return m.group(1), None
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", target)
    if m:
        return m.group(3), f"{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"(?i)pr\s*#?(\d+)", target.strip())
    if m:
        return m.group(1), None
    return None, None


def gh_json(args, cwd):
    p = run(["gh", *args], cwd=cwd)
    if p.returncode != 0:
        return None, p.stderr.strip()
    try:
        return json.loads(p.stdout), None
    except json.JSONDecodeError:
        return None, "invalid JSON from gh"


def collect_pr(root, num, repo_slug, pkg):
    fields = ("number,title,body,state,isDraft,author,baseRefName,headRefName,headRefOid,"
              "baseRefOid,url,closingIssuesReferences,labels,files,commits,reviewDecision")
    args = ["pr", "view", num, "--json", fields]
    if repo_slug:
        args += ["--repo", repo_slug]
    pr, err = gh_json(args, root)
    if not isinstance(pr, dict):
        die(f"could not read PR {num} with gh: {err}. Check `gh auth status`.")
    (pkg / "pr.json").write_text(json.dumps(pr, indent=2))
    slug = repo_slug or out("config", "--get", "remote.origin.url", cwd=root)
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", slug or "")
    owner, name = (m.group(1), m.group(2)) if m else (None, None)
    if repo_slug:
        owner, name = repo_slug.split("/")

    # Fetch exact commits from the requested repository, never a different local PR.
    base, head = pr.get("baseRefOid"), pr.get("headRefOid")
    if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{40,64}", v)
               for v in (base, head)):
        die("PR metadata is missing valid base/head commit IDs")
    remote = f"https://github.com/{repo_slug}.git" if repo_slug else "origin"
    missing = [ref for ref in (base, head)
               if git("cat-file", "-e", f"{ref}^{{commit}}", cwd=root).returncode]
    if missing:
        git("fetch", "--quiet", "--no-tags", remote, *missing, cwd=root, check=True)
    base, head = commit_ref(root, base), commit_ref(root, head)
    diff = git("diff", CONTEXT, f"{base}...{head}", cwd=root, check=True).stdout
    # Inline anchors come from GitHub, and must describe the same head we pinned.
    a = ["pr", "diff", num] + (["--repo", repo_slug] if repo_slug else [])
    raw = run(["gh", *a], cwd=root, check=True).stdout
    latest_args = ["pr", "view", num, "--json", "headRefOid,baseRefOid"]
    if repo_slug:
        latest_args += ["--repo", repo_slug]
    latest, err = gh_json(latest_args, root)
    if not isinstance(latest, dict) or latest.get("headRefOid") != head or latest.get("baseRefOid") != base:
        die(f"PR changed or could not be rechecked while collecting: {err or 'commit mismatch'}")
    if diff.strip() and not raw.strip():
        die("GitHub returned an empty diff for a nonempty PR")
    (pkg / "pr-github.diff").write_text(raw)
    warnings = []

    comments = {"threads": [], "issue_comments": [], "reviews": []}
    if owner and name:
        q = """query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){
          reviewThreads(first:100){nodes{isResolved isOutdated path line comments(first:30){nodes{
            databaseId body author{login} createdAt path line originalLine}}}}
          reviews(first:50){nodes{databaseId state body author{login} submittedAt}}}}}"""
        data, _ = gh_json(["api", "graphql", "-f", f"query={q}", "-F", f"o={owner}",
                           "-F", f"n={name}", "-F", f"p={num}"], root)
        try:
            prq = data["data"]["repository"]["pullRequest"]
            comments["threads"] = prq["reviewThreads"]["nodes"]
            comments["reviews"] = prq["reviews"]["nodes"]
        except (TypeError, KeyError):
            warnings.append("GraphQL review context unavailable; REST fallback lacks resolved-thread state and review summaries")
            rest, rest_err = gh_json(["api", f"repos/{owner}/{name}/pulls/{num}/comments", "--paginate"], root)
            if not isinstance(rest, list):
                warnings.append(f"Review threads unavailable: {rest_err or 'invalid response'}")
                rest = []
            comments["threads"] = [{"isResolved": None, "comments": {"nodes": [c]}} for c in (rest or [])]
        ic, ic_err = gh_json(["api", f"repos/{owner}/{name}/issues/{num}/comments", "--paginate"], root)
        if not isinstance(ic, list):
            warnings.append(f"Issue comments unavailable: {ic_err or 'invalid response'}")
            ic = []
        comments["issue_comments"] = ic
    if not owner or not name:
        warnings.append("Repository identity unavailable; comment triage incomplete")
    comments["warnings"] = warnings
    (pkg / "pr-comments.json").write_text(json.dumps(comments, indent=2))
    commits = "\n".join(f"{c.get('oid','')[:10]} {c.get('messageHeadline','')}" for c in pr.get("commits", []))
    desc = f"PR #{num}: {pr.get('title','')} ({pr.get('url','')})"
    return diff, commits, base, head, desc, {"owner": owner, "repo": name, "pr": int(num)}


def numstat(diff_text):
    files = []
    cur = None
    in_hunk = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            in_hunk = False
            if cur:
                files.append(cur)
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            cur = {"path": m.group(2) if m else line, "added": 0, "deleted": 0, "status": "modified"}
        elif cur is None:
            continue
        elif line.startswith("@@ "):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            cur["added"] += 1
        elif in_hunk and line.startswith("-"):
            cur["deleted"] += 1
        elif line.startswith("new file mode") or line.startswith("--- /dev/null"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode") or line.startswith("+++ /dev/null"):
            cur["status"] = "deleted"
        elif line.startswith("rename to "):
            cur["status"] = "renamed"
        elif line.startswith("+") and not line.startswith("+++"):
            cur["added"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["deleted"] += 1
    if cur:
        files.append(cur)
    # git diff --no-index on /dev/null names the file "b/<path>" with a/dev/null source
    for f in files:
        f["path"] = f["path"].replace("dev/null", "").lstrip("/") or f["path"]
    return files


def numbered_diff(diff_text):
    """Prefix every hunk line with its line number in the NEW file (blank for removed lines)."""
    out, new_ln = [], None
    for raw in diff_text.splitlines():
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if raw.startswith("diff --git"):
            new_ln = None
            out.append(raw)
        elif m:
            new_ln = int(m.group(1))
            out.append(raw)
        elif new_ln is None or raw.startswith("\\"):
            out.append(raw)
        elif raw.startswith("-"):
            out.append(f"{'':>6} {raw}")
        else:
            out.append(f"{new_ln:>6} {raw}")
            new_ln += 1
    return "\n".join(out) + "\n"


def purpose_candidates(root, files, commits_text, pr_body, branch):
    cands = []
    seen = set()

    def add(path, why, rank):
        if path in seen:
            return
        seen.add(path)
        title = ""
        try:
            for line in Path(root, path).read_text(errors="ignore").splitlines():
                if line.strip():
                    title = line.strip().lstrip("# ").strip()[:120]
                    break
        except OSError:
            pass
        cands.append({"path": path, "why": why, "rank": rank, "title": title})

    for f in files:
        if f["path"].lower().endswith((".md", ".mdx", ".rst", ".adoc")) and f["status"] != "deleted":
            add(f["path"], "changed in this diff", 1)

    text = " ".join([commits_text or "", pr_body or "", branch or ""]).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9_-]{3,}", text))
    changed_dirs = {str(Path(f["path"]).parent) for f in files}
    changed_words = set()
    for f in files:
        changed_words.update(w for w in re.split(r"[/._-]", f["path"].lower()) if len(w) > 3)

    adr_dirs = [d for d in ADR_DIRS if Path(root, d).is_dir()]
    adr_file = Path(root, ".adr-dir")
    if adr_file.is_file():
        adr_dirs.append(adr_file.read_text().strip())
    for d in adr_dirs:
        for p in sorted(Path(root, d).rglob("*")):
            if p.suffix.lower() not in (".md", ".rst", ".adoc") or not p.is_file():
                continue
            rel = str(p.relative_to(root))
            name_words = set(w for w in re.split(r"[/._-]", p.stem.lower()) if len(w) > 3)
            num = re.match(r"(?:adr-?)?(0*(\d+))", p.stem.lower())
            mentioned = rel.lower() in text or p.stem.lower() in text or \
                (num and (re.search(rf"(adr|decision|record)[-# ]*0*{num.group(2)}\b", text)
                          or (len(num.group(1)) >= 3 and re.search(rf"\b{num.group(1)}\b", text))))
            haystack = " ".join(f["path"].lower() for f in files) + " " + text
            if mentioned:
                add(rel, "ADR referenced in commits/PR/branch", 2)
            elif any(len(w) > 4 and not w.isdigit() and w in haystack for w in name_words):
                add(rel, "ADR whose title matches the changed area", 3)

    tracked = out("ls-files", "*.md", cwd=root).splitlines()
    for rel in tracked:
        stem = Path(rel).stem.lower()
        if not SPEC_PATTERNS.search(rel):
            continue
        if rel.lower() in text or (len(stem) > 4 and stem in text):
            add(rel, "spec/plan referenced in commits/PR/branch", 3)
        elif str(Path(rel).parent) in changed_dirs:
            add(rel, "spec/plan next to changed code", 4)
        elif "superpowers" in rel or rel.startswith(("specs/", "docs/specs/", "docs/plans/")):
            words = set(w for w in re.split(r"[/._-]", stem) if len(w) > 3)
            if words & (changed_words | tokens):
                add(rel, "plan/spec matching the changed area", 4)
    cands.sort(key=lambda c: c["rank"])
    return cands[:12]


def instruction_files(root, files):
    found = []
    dirs = {""}
    for f in files:
        parts = Path(f["path"]).parts[:-1]
        for i in range(len(parts) + 1):
            dirs.add(str(Path(*parts[:i])) if i else "")
    for d in sorted(dirs):
        for name in INSTRUCTION_FILES:
            p = Path(root, d, name)
            if p.is_file():
                found.append(str(p.relative_to(root)))
    return sorted(set(found))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    root = out("rev-parse", "--show-toplevel")
    if not root:
        die("not inside a git repository")
    target = (a.target or "").strip()
    repo_name = Path(root).name
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if a.out:
        pkg = Path(a.out).resolve()
        if pkg.exists() and any(pkg.iterdir()):
            die("--out must be empty; refusing to reuse stale review artifacts")
        pkg.mkdir(parents=True, exist_ok=True)
    else:
        base_dir = Path(tempfile.gettempdir(), "review-kit")
        base_dir.mkdir(parents=True, exist_ok=True)
        pkg = Path(tempfile.mkdtemp(prefix=f"{repo_name}-{stamp}-", dir=base_dir))
    (pkg / "candidates").mkdir(exist_ok=True)

    meta = {"repo_root": root, "repo": repo_name, "target": target or "(current branch)",
            "created": stamp, "kind": None}
    branch = out("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    pr_body = ""
    untracked = []
    gh_info = None
    base = head = None

    pr_num, pr_repo = parse_pr_ref(target) if target else (None, None)
    if pr_num:
        diff, commits, base, head, desc, gh_info = collect_pr(root, pr_num, pr_repo, pkg)
        pr_body = json.loads((pkg / "pr.json").read_text()).get("body", "")
        meta["kind"] = "pr"
    elif target and (".." in target):
        # Resolve both endpoints separately so bad ranges can never become empty reviews.
        parts = re.split(r"(\.\.\.?)", target)
        if len(parts) != 3:
            die("invalid commit range")
        left, dots, right = parts
        base, head = commit_ref(root, left or "HEAD"), commit_ref(root, right or "HEAD")
        diff = git("diff", CONTEXT, base + dots + head, cwd=root, check=True).stdout
        commits = git("log", "--oneline", "--no-decorate", f"{base}..{head}", cwd=root, check=True).stdout.strip()
        desc = f"range {target}"
        meta["kind"] = "range"
    elif target and git("rev-parse", "--verify", "--quiet", target + "^{commit}", cwd=root).returncode == 0 \
            and not Path(root, target).exists():
        head = commit_ref(root, target)
        base = out("rev-parse", "--verify", head + "^", cwd=root) or empty_tree(root)
        diff = git("diff", CONTEXT, base, head, cwd=root, check=True).stdout
        commits = git("log", "-1", "--oneline", "--no-decorate", head, cwd=root, check=True).stdout.strip()
        desc = f"commit {target}"
        meta["kind"] = "commit"
    else:
        path_filter = None
        if target:
            if not Path(root, target).exists() and not Path(target).exists():
                die(f"target '{target}' is not a PR, range, commit or existing path")
            path_filter = [os.path.relpath(Path(target).resolve(), root) if Path(target).exists() else target]
        upstream = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=root)
        base_ref = a.base or (upstream if upstream and out("rev-parse", upstream, cwd=root) != out("rev-parse", "HEAD", cwd=root) else "") or default_base(root)
        if base_ref and out("rev-parse", base_ref, cwd=root) == out("rev-parse", "HEAD", cwd=root) and not a.base:
            alt = default_base(root)
            base_ref = alt if alt and out("rev-parse", alt, cwd=root) != out("rev-parse", "HEAD", cwd=root) else base_ref
        if base_ref:
            base_ref = commit_ref(root, base_ref)
        mb = git("merge-base", base_ref, "HEAD", cwd=root, check=True).stdout.strip() if base_ref else ""
        if not mb:
            mb = out("rev-parse", "HEAD~1", cwd=root) or empty_tree(root)
        args = ["diff", CONTEXT, mb]
        if path_filter:
            args += ["--", *path_filter]
        diff = git(*args, cwd=root, check=True).stdout
        udiff, untracked = untracked_diff(root, path_filter)
        diff += udiff
        commits = out("log", "--oneline", "--no-decorate", f"{mb}..HEAD", cwd=root)
        base, head = mb, "WORKTREE"
        desc = f"branch {branch} vs {base_ref or mb[:10]} (merge-base {mb[:10]}) + uncommitted"
        meta["kind"] = "branch"
        meta["base_ref"] = base_ref
        if path_filter:
            desc += f", limited to {path_filter[0]}"
            meta["kind"] = "path"
            if not diff.strip():
                # Nothing changed under the path: review its current contents as new code.
                chunks = []
                for f in out("ls-files", "--", *path_filter, cwd=root).splitlines():
                    chunks.append(no_index_diff(root, f))
                diff = "".join(chunks)
                desc = f"current contents of {path_filter[0]} (no pending changes; reviewed as new code)"
                meta["kind"] = "path-snapshot"

    (pkg / "diff.patch").write_text(diff)
    (pkg / "diff-numbered.txt").write_text(numbered_diff(diff))
    files = numstat(diff)
    added = sum(f["added"] for f in files)
    deleted = sum(f["deleted"] for f in files)
    changed = added + deleted
    size = "empty" if not files else "ok" if changed <= 300 else "large" if changed <= 1000 else "too-large"
    tests_changed = [f["path"] for f in files if re.search(r"(\.spec\.|\.test\.|_test\.|Tests?/|tests?/|\.Tests\b|Test\.cs$|Tests\.cs$)", f["path"])]
    original_root = root
    committed = meta["kind"] in ("pr", "range", "commit")
    if committed:
        root = snapshot(root, head, pkg)
    warnings = []
    if gh_info:
        warnings = json.loads((pkg / "pr-comments.json").read_text()).get("warnings", [])
    meta.update({"repo_root": root, "original_repo_root": original_root,
                 "reviewed_commit": head if committed else commit_ref(root, "HEAD"),
                 "source_kind": "pinned-worktree" if committed else "working-tree",
                 # Code context (diff, commits, pinned source) is complete at this point; failures
                 # there already aborted. Missing PR *comment* context only limits comment triage.
                 "collection_status": "completed",
                 "comment_context_status": ("partial" if warnings else "completed") if gh_info else "not-applicable",
                 "collection_warnings": warnings})
    cands = purpose_candidates(root, files, commits, pr_body, branch)
    instr = instruction_files(root, files)

    meta.update({"description": desc, "base": base, "head": head, "branch": branch,
                 "files": files, "added": added, "deleted": deleted, "size": size,
                 "tests_changed": tests_changed, "untracked": untracked,
                 "purpose_candidates": cands, "instruction_files": instr, "github": gh_info})
    (pkg / "meta.json").write_text(json.dumps(meta, indent=2))

    lines = [f"# Review package", "", "Cite lines from diff-numbered.txt: its left column is the line number in the new file.", "", f"- Target: {desc}", f"- Repo: {root}",
             f"- Base: {base}  Head: {head}", f"- Size: {len(files)} files, +{added}/-{deleted} ({size})", ""]
    lines.append("## Files")
    for f in files:
        lines.append(f"- {f['status']:8} {f['path']} (+{f['added']}/-{f['deleted']})")
    lines += ["", "## Commits", commits or "(none: uncommitted changes only)", ""]
    lines.append("## Purpose-document candidates (see references/intake.md)")
    if cands:
        for c in cands:
            lines.append(f"- {c['path']} — {c['why']}" + (f" — \"{c['title']}\"" if c['title'] else ""))
    else:
        lines.append("- none found: ask the user what the change is for")
    if pr_body:
        lines += ["", "## PR description", pr_body.strip()[:4000]]
    lines += ["", "## Project instruction files", *([f"- {p}" for p in instr] or ["- none"])]
    lines += ["", "## Test files changed", *([f"- {p}" for p in tests_changed] or ["- none"])]
    if untracked:
        lines += ["", "## Untracked files included", *[f"- {u}" for u in untracked]]
    (pkg / "summary.md").write_text("\n".join(lines) + "\n")

    if warnings:
        lines += ["", "## PR comment context incomplete (code review is unaffected; say so in the report)",
                  *[f"- {w}" for w in warnings]]
        (pkg / "summary.md").write_text("\n".join(lines) + "\n")
    if size == "empty":
        print(f"EMPTY: nothing to review for {desc}")
    print(str(pkg))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        die(str(exc))
