#!/usr/bin/env python3
"""Gather everything a review needs in one call, and print it.

Resolves the target (branch + uncommitted, range, commit, PR, path), writes the numbered diff
and metadata to a scratch folder OUTSIDE the repository, and prints a compact context block:
size, risk signals, suggested depth, files, commits, purpose documents, project rules and
learnings, static hints (ruff bug rules on changed Python lines), callers of changed Python
symbols, and the numbered diff itself when it is small enough to read inline.

Usage:
  collect.py [--target T] [--base REF] [--mode M] [--no-diff]   print context; last line: PKG=<dir>
  collect.py --done PKG                                         remove a pinned source copy

Nothing is written inside the repository. Exit code is nonzero on any collection failure:
never treat a failure as an empty diff.
"""
import argparse
import datetime as _dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CONTEXT = "-U10"
INLINE_DIFF_MAX_LINES = 1500
INSTRUCTION_FILES = ["CLAUDE.md", "AGENTS.md", "REVIEW.md", "CONTRIBUTING.md",
                     ".github/copilot-instructions.md"]
LEARNINGS = ".review-kit/learnings.md"
ADR_DIRS = ["docs/adr", "docs/adrs", "docs/decisions", "doc/adr", "adr", "adrs",
            "Documentation/Decisions", "docs/architecture/decisions", "architecture/decisions"]
SPEC_PATTERNS = re.compile(r"(spec|plan|design|rfc|prd|requirements?|adr|decision)", re.I)
TEST_PATH = re.compile(r"(\.spec\.|\.test\.|_test\.|(^|/)test_[^/]*\.py$|(^|/)tests?/|Tests?/|\.Tests\b|Tests?\.cs$|conftest\.py$)")

# Risk signals: categories of change where a missed bug is expensive. Matched on added lines.
RISK = {
    "auth": r"\b(auth|permission|is_admin|role|tenant|owner_id|login|session|jwt|token|csrf)\b",
    "money": r"\b(amount|price|charge|refund|invoice|balance|payout|payment|currency|cents|fee)\b",
    "data": r"\b(DELETE|UPDATE|INSERT|ALTER\s+TABLE|DROP|migration|bulk_|transaction|atomic|commit\(\))",
    "concurrency": r"\b(async\s+def|await|asyncio|thread|Lock|Semaphore|multiprocessing|celery|queue|retry|webhook|idempot)",
    "injection": r"(subprocess|os\.system|eval\(|exec\(|pickle|yaml\.load|\.execute\(|raw\(|f\"SELECT|f'SELECT|shell=True|innerHTML|mark_safe|\|safe)",
    "secrets": r"(secret|password|api_key|private_key|BEGIN [A-Z ]*PRIVATE KEY)",
}
RUFF_SELECT = "F,B,E9,PLE,ASYNC,S,BLE,DTZ,RUF006,RUF012,PLW0120,PLW0602,PLW1508,PLW1510,PLW3301,TRY002"
RUFF_IGNORE = "S101,S311,B008,B904,S603,S607,F401"  # noise for review purposes (B008 = FastAPI Depends)
SYMBOL_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")


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


def source_clean(root):
    return not git("status", "--porcelain", "--untracked-files=all", cwd=root,
                   check=True).stdout.strip()


def validate_source(meta, package=None):
    """Raise if the source the review read no longer matches the reviewed revision."""
    root = meta["repo_root"]
    if not Path(root).is_dir():
        raise ValueError("reviewed source is gone")
    if meta.get("source_kind") == "pinned-copy" and commit_ref(root, "HEAD") != meta["reviewed_commit"]:
        raise ValueError("pinned source copy moved")
    if meta.get("source_kind") == "working-tree" and meta.get("head_at_collection") and \
            commit_ref(root, "HEAD") != meta["head_at_collection"]:
        raise ValueError("checkout moved since the review")


def scratch_home():
    return Path(os.environ.get("RK_SCRATCH") or Path(tempfile.gettempdir()) / "review-kit")


def prune_old(home, days=7):
    """Old scratch folders are disposable; remove them (and their pinned copies) quietly."""
    if not home.is_dir():
        return
    cutoff = _dt.datetime.now().timestamp() - days * 86400
    for d in home.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                done(d, quiet=True)
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def pin_source(root, head, pkg):
    """Use the checkout if it already is the reviewed commit; else a detached copy in PKG/src."""
    if commit_ref(root, "HEAD") == head and source_clean(root):
        return root, "checkout-at-reviewed-commit"
    dest = pkg / "src"
    git("worktree", "add", "--detach", "--quiet", str(dest), head, cwd=root, check=True)
    return str(dest), "pinned-copy"


def done(pkg, quiet=False):
    """Remove the pinned copy of a finished review. Never forced: an edited copy is kept."""
    pkg = Path(pkg)
    try:
        meta = json.loads((pkg / "meta.json").read_text())
    except (OSError, ValueError):
        return "no meta"
    src = Path(meta.get("repo_root", ""))
    if meta.get("source_kind") != "pinned-copy" or not src.is_dir():
        return "nothing to remove"
    if src.resolve().parent != pkg.resolve():
        return "refused: copy is not inside the scratch folder"
    r = git("worktree", "remove", str(src), cwd=meta["original_repo_root"])
    git("worktree", "prune", cwd=meta["original_repo_root"])
    msg = "removed" if r.returncode == 0 else f"kept: {r.stderr.strip()}"
    if not quiet:
        print(msg)
    return msg


def no_index_diff(root, path):
    result = git("diff", "--no-index", CONTEXT, "--", "/dev/null", path, cwd=root)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Cannot read {path}: {result.stderr.strip()}")
    return result.stdout


def default_base(root):
    ref = out("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=root)
    if ref:
        return ref
    for cand in ("main", "master", "origin/main", "origin/master", "develop"):
        if git("rev-parse", "--verify", "--quiet", cand + "^{commit}", cwd=root).returncode == 0:
            return cand
    return None


def untracked_diff(root, paths_filter=None):
    files = out("ls-files", "--others", "--exclude-standard", cwd=root).splitlines()
    files = [f for f in files if not f.startswith(".review-kit/")]
    if paths_filter:
        files = [f for f in files if any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths_filter)]
    chunks = []
    for f in files:
        try:
            if Path(root, f).stat().st_size > 400_000:
                continue
        except OSError:
            continue
        chunks.append(no_index_diff(root, f))
    return "".join(chunks), files


def load_config(root):
    cfg = {"html": "auto"}
    for p in (Path.home() / ".review-kit" / "config.json", Path(root) / ".review-kit" / "config.json"):
        try:
            data = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            cfg.update(data)
    return cfg


def parse_pr_ref(target):
    m = re.fullmatch(r"(?i)(?:pr\s*)?#?(\d+)", target.strip())
    if m:
        return m.group(1), None
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", target)
    if m:
        return m.group(3), f"{m.group(1)}/{m.group(2)}"
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
    args = ["pr", "view", num, "--json", fields] + (["--repo", repo_slug] if repo_slug else [])
    pr, err = gh_json(args, root)
    if not isinstance(pr, dict):
        die(f"could not read PR {num} with gh: {err}. Check `gh auth status`.")
    (pkg / "pr.json").write_text(json.dumps(pr, indent=2))
    slug = repo_slug or out("config", "--get", "remote.origin.url", cwd=root)
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", slug or "")
    owner, name = (m.group(1), m.group(2)) if m else (None, None)
    if repo_slug:
        owner, name = repo_slug.split("/")

    base, head = pr.get("baseRefOid"), pr.get("headRefOid")
    if not all(isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{40,64}", v) for v in (base, head)):
        die("PR metadata is missing valid base/head commit IDs")
    remote = f"https://github.com/{repo_slug}.git" if repo_slug else "origin"
    missing = [ref for ref in (base, head)
               if git("cat-file", "-e", f"{ref}^{{commit}}", cwd=root).returncode]
    if missing:
        git("fetch", "--quiet", "--no-tags", remote, *missing, cwd=root, check=True)
    base, head = commit_ref(root, base), commit_ref(root, head)
    diff = git("diff", CONTEXT, f"{base}...{head}", cwd=root, check=True).stdout
    # Inline comment anchors come from GitHub's diff, which must describe the same head.
    raw = run(["gh", "pr", "diff", num] + (["--repo", repo_slug] if repo_slug else []),
              cwd=root, check=True).stdout
    latest, err = gh_json(["pr", "view", num, "--json", "headRefOid,baseRefOid"]
                          + (["--repo", repo_slug] if repo_slug else []), root)
    if not isinstance(latest, dict) or latest.get("headRefOid") != head or latest.get("baseRefOid") != base:
        die(f"PR changed or could not be rechecked while collecting: {err or 'commit mismatch'}")
    if diff.strip() and not raw.strip():
        die("GitHub returned an empty diff for a nonempty PR")
    (pkg / "pr-github.diff").write_text(raw)

    warnings, comments = [], {"threads": [], "issue_comments": [], "reviews": []}
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
            warnings.append("GraphQL review context unavailable; REST fallback lacks resolved-thread state")
            rest, rest_err = gh_json(["api", f"repos/{owner}/{name}/pulls/{num}/comments", "--paginate"], root)
            if not isinstance(rest, list):
                warnings.append(f"Review threads unavailable: {rest_err or 'invalid response'}")
                rest = []
            comments["threads"] = [{"isResolved": None, "comments": {"nodes": [c]}} for c in rest]
        ic, ic_err = gh_json(["api", f"repos/{owner}/{name}/issues/{num}/comments", "--paginate"], root)
        if not isinstance(ic, list):
            warnings.append(f"Issue comments unavailable: {ic_err or 'invalid response'}")
            ic = []
        comments["issue_comments"] = ic
    else:
        warnings.append("Repository identity unavailable; comment triage incomplete")
    comments["warnings"] = warnings
    (pkg / "pr-comments.json").write_text(json.dumps(comments, indent=2))
    commits = "\n".join(f"{c.get('oid', '')[:10]} {c.get('messageHeadline', '')}" for c in pr.get("commits", []))
    desc = f"PR #{num}: {pr.get('title', '')} ({pr.get('url', '')})"
    return diff, commits, base, head, desc, {"owner": owner, "repo": name, "pr": int(num)}, pr.get("body") or "", warnings


def numstat(diff_text):
    files, cur, in_hunk = [], None, False
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
    if cur:
        files.append(cur)
    for f in files:  # `git diff --no-index /dev/null x` names the file b/x
        f["path"] = f["path"].replace("dev/null", "").lstrip("/") or f["path"]
    return files


def numbered_diff(diff_text):
    """Prefix every hunk line with its line number in the NEW file (blank for removed lines)."""
    lines, new_ln = [], None
    for raw in diff_text.splitlines():
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if raw.startswith("diff --git"):
            new_ln = None
            lines.append(raw)
        elif m:
            new_ln = int(m.group(1))
            lines.append(raw)
        elif new_ln is None or raw.startswith("\\"):
            lines.append(raw)
        elif raw.startswith("-"):
            lines.append(f"{'':>6} {raw}")
        else:
            lines.append(f"{new_ln:>6} {raw}")
            new_ln += 1
    return "\n".join(lines) + "\n"


def added_lines(diff_text):
    """{path: {new_line_number: text}} for every added line."""
    result, cur, new_ln = {}, None, None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git"):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", raw)
            cur, new_ln = (m.group(2).replace("dev/null", "").lstrip("/") if m else None), None
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            new_ln = int(m.group(1))
            continue
        if new_ln is None or cur is None or raw.startswith("\\") or raw.startswith("-"):
            continue
        if raw.startswith("+"):
            result.setdefault(cur, {})[new_ln] = raw[1:]
        new_ln += 1
    return result


def removed_symbols(diff_text):
    names = set()
    for raw in diff_text.splitlines():
        if raw.startswith("-") and not raw.startswith("---"):
            m = SYMBOL_DEF.match(raw[1:])
            if m:
                names.add(m.group(1))
    return names


def risk_signals(added):
    text = "\n".join(t for lines in added.values() for t in lines.values())
    return [k for k, pat in RISK.items() if re.search(pat, text, re.I if k != "data" else 0)]


def suggest_depth(changed, risks, files):
    code = [f for f in files if not f["path"].lower().endswith((".md", ".rst", ".txt", ".lock"))]
    if changed > 400 or len(code) > 12:
        return "deep", "large change"
    if len(risks) >= 2 and changed > 120:
        return "deep", f"risky areas ({', '.join(risks)}) in a medium-size change"
    return "quick", "small or low-risk change"


def ruff_hints(root, added):
    """Bug-class ruff rules on changed Python files, reported only for added lines."""
    py = [p for p in added if p.endswith(".py") and Path(root, p).is_file()]
    if not py:
        return None, []
    exe = shutil.which("ruff")
    if not exe:
        return "ruff not installed (pip install ruff adds a fast static pass)", []
    p = run([exe, "check", "--isolated", "--no-cache", "--select", RUFF_SELECT, "--ignore", RUFF_IGNORE,
             "--output-format", "json", "--exit-zero", *py], cwd=root, timeout=30)
    try:
        items = json.loads(p.stdout or "[]")
    except ValueError:
        return f"ruff failed: {p.stderr.strip()[:200]}", []
    hints = []
    for it in items:
        rel = os.path.relpath(it.get("filename", ""), root)
        line = (it.get("location") or {}).get("row")
        if line in added.get(rel, {}):
            hints.append(f"- {rel}:{line} {it.get('code')} {it.get('message')}")
    return None, hints[:40]


def callers(root, added, diff_text, rev=None):
    """Where changed/removed Python symbols are used outside their own definition."""
    names = set(removed_symbols(diff_text))
    for path, lines in added.items():
        if path.endswith(".py"):
            names.update(m.group(1) for t in lines.values() if (m := SYMBOL_DEF.match(t)))
    names = sorted(n for n in names if not n.startswith("__") and len(n) > 3 and n not in ("main", "test"))
    report = []
    for n in names[:20]:
        if n.startswith("test_"):
            continue
        args = ["grep", "-n", "-I", "-w", "-e", n] + ([rev] if rev else []) + ["--", "*.py"]
        hits = []
        for line in out(*args, cwd=root).splitlines():
            loc = line.split(":", 2) if not rev else line.split(":", 3)[1:]
            if len(loc) < 3 or SYMBOL_DEF.match(loc[2]) or loc[2].lstrip().startswith(("#", "import ", "from ")):
                continue
            hits.append(f"{loc[0]}:{loc[1]}")
        tag = " (removed in this change)" if n in removed_symbols(diff_text) and not any(
            SYMBOL_DEF.match(t) and SYMBOL_DEF.match(t).group(1) == n for ls in added.values() for t in ls.values()) else ""
        report.append(f"{n}{tag}: " + (", ".join(hits[:6]) + (f" (+{len(hits) - 6} more)" if len(hits) > 6 else "")
                                     if hits else "no callers found"))
    return report


def purpose_candidates(root, files, commits_text, pr_body, branch):
    cands, seen = [], set()

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
    changed_words = {w for f in files for w in re.split(r"[/._-]", f["path"].lower()) if len(w) > 3}
    haystack = " ".join(f["path"].lower() for f in files) + " " + text
    adr_dirs = [d for d in ADR_DIRS if Path(root, d).is_dir()]
    if Path(root, ".adr-dir").is_file():
        adr_dirs.append(Path(root, ".adr-dir").read_text().strip())
    for d in adr_dirs:
        for p in sorted(Path(root, d).rglob("*")):
            if p.suffix.lower() not in (".md", ".rst", ".adoc") or not p.is_file():
                continue
            rel = str(p.relative_to(root))
            name_words = {w for w in re.split(r"[/._-]", p.stem.lower()) if len(w) > 3}
            num = re.match(r"(?:adr-?)?(0*(\d+))", p.stem.lower())
            mentioned = rel.lower() in text or p.stem.lower() in text or \
                (num and (re.search(rf"(adr|decision|record)[-# ]*0*{num.group(2)}\b", text)
                          or (len(num.group(1)) >= 3 and re.search(rf"\b{num.group(1)}\b", text))))
            if mentioned:
                add(rel, "ADR referenced in commits/PR/branch", 2)
            elif any(len(w) > 4 and not w.isdigit() and w in haystack for w in name_words):
                add(rel, "ADR whose title matches the changed area", 3)
    for rel in out("ls-files", "*.md", cwd=root).splitlines():
        stem = Path(rel).stem.lower()
        if not SPEC_PATTERNS.search(rel) and Path(rel).parent.name not in ("docs", "doc"):
            continue
        if rel.lower() in text or (len(stem) > 4 and stem in text):
            add(rel, "doc referenced in commits/PR/branch", 3)
        elif str(Path(rel).parent) in changed_dirs:
            add(rel, "doc next to changed code", 4)
        elif {w for w in re.split(r"[/._-]", stem) if len(w) > 3} & (changed_words | tokens):
            add(rel, "doc matching the changed area", 4)
    cands.sort(key=lambda c: c["rank"])
    return cands[:8]


def instruction_files(root, files):
    dirs = {""}
    for f in files:
        parts = Path(f["path"]).parts[:-1]
        dirs.update(str(Path(*parts[:i])) if i else "" for i in range(len(parts) + 1))
    found = {str(Path(d, n)) for d in dirs for n in INSTRUCTION_FILES if Path(root, d, n).is_file()}
    return sorted(found)


def resolve(root, target, base_opt, pkg):
    """Returns diff, commits, base, head, desc, kind, gh_info, pr_body, untracked, warnings."""
    pr_num, pr_repo = parse_pr_ref(target) if target else (None, None)
    if pr_num:
        diff, commits, base, head, desc, gh, body, warn = collect_pr(root, pr_num, pr_repo, pkg)
        return diff, commits, base, head, desc, "pr", gh, body, [], warn
    if target and ".." in target:
        parts = re.split(r"(\.\.\.?)", target)
        if len(parts) != 3:
            die("invalid commit range")
        left, dots, right = parts
        base, head = commit_ref(root, left or "HEAD"), commit_ref(root, right or "HEAD")
        diff = git("diff", CONTEXT, base + dots + head, cwd=root, check=True).stdout
        commits = out("log", "--oneline", "--no-decorate", f"{base}..{head}", cwd=root)
        return diff, commits, base, head, f"range {target}", "range", None, "", [], []
    if target and not Path(root, target).exists() and not Path(target).exists() and \
            git("rev-parse", "--verify", "--quiet", target + "^{commit}", cwd=root).returncode == 0:
        head = commit_ref(root, target)
        base = out("rev-parse", "--verify", head + "^", cwd=root) or empty_tree(root)
        diff = git("diff", CONTEXT, base, head, cwd=root, check=True).stdout
        commits = out("log", "-1", "--oneline", "--no-decorate", head, cwd=root)
        return diff, commits, base, head, f"commit {target}", "commit", None, "", [], []

    path_filter = None
    if target:
        if not Path(root, target).exists() and not Path(target).exists():
            die(f"target '{target}' is not a PR, range, commit or existing path")
        path_filter = [os.path.relpath(Path(target).resolve(), root) if Path(target).exists() else target]
    head_sha = out("rev-parse", "HEAD", cwd=root)
    upstream = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=root)
    base_ref = base_opt or (upstream if upstream and out("rev-parse", upstream, cwd=root) != head_sha else "")
    if not base_ref:
        base_ref = default_base(root)
        if base_ref and out("rev-parse", base_ref, cwd=root) == head_sha:
            base_ref = None
    if base_ref:
        base_ref = commit_ref(root, base_ref)
    mb = git("merge-base", base_ref, "HEAD", cwd=root, check=True).stdout.strip() if base_ref else ""
    if not mb:
        mb = out("rev-parse", "HEAD~1", cwd=root) if not path_filter else head_sha
        mb = mb or empty_tree(root)
    diff = git("diff", CONTEXT, mb, "--", *(path_filter or ["."]), cwd=root, check=True).stdout
    udiff, untracked = untracked_diff(root, path_filter)
    diff += udiff
    commits = out("log", "--oneline", "--no-decorate", f"{mb}..HEAD", cwd=root)
    branch = out("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    desc = f"branch {branch} vs {mb[:10]} + uncommitted"
    kind = "branch"
    if path_filter:
        desc += f", limited to {path_filter[0]}"
        kind = "path"
        if not diff.strip():
            diff = "".join(no_index_diff(root, f) for f in out("ls-files", "--", *path_filter, cwd=root).splitlines())
            desc = f"current contents of {path_filter[0]} (no pending changes; reviewed as whole files)"
            kind = "path-snapshot"
    return diff, commits, mb, "WORKTREE", desc, kind, None, "", untracked, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--mode", default="review")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-diff", action="store_true", help="do not print the diff inline")
    ap.add_argument("--done", metavar="PKG", help="remove the pinned source copy of a finished review")
    a = ap.parse_args()
    if a.done:
        done(a.done)
        return

    root = out("rev-parse", "--show-toplevel")
    if not root:
        die("not inside a git repository")
    target = a.target.strip()
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    home = scratch_home()
    prune_old(home)
    if a.out:
        pkg = Path(a.out).resolve()
        if pkg.exists() and any(pkg.iterdir()):
            die("--out must be empty")
    else:
        pkg = home / f"{Path(root).name}-{stamp}-{secrets.token_hex(3)}"
    pkg.mkdir(parents=True, exist_ok=True)
    meta = {"repo_root": root, "original_repo_root": root, "repo": Path(root).name,
            "target": target or "(current branch)", "created": stamp, "mode": a.mode,
            "run_dir": str(pkg), "collection_status": "failed"}
    (pkg / "meta.json").write_text(json.dumps(meta, indent=2))

    diff, commits, base, head, desc, kind, gh, pr_body, untracked, warnings = resolve(root, target, a.base, pkg)
    committed = kind in ("pr", "range", "commit")
    src_root, source_kind = pin_source(root, head, pkg) if committed and diff.strip() else (root, "working-tree")

    numbered = numbered_diff(diff)
    (pkg / "diff.patch").write_text(diff)
    (pkg / "diff-numbered.txt").write_text(numbered)
    files = numstat(diff)
    added_n = sum(f["added"] for f in files)
    deleted_n = sum(f["deleted"] for f in files)
    changed = added_n + deleted_n
    size = "empty" if not files else "small" if changed <= 150 else "medium" if changed <= 400 \
        else "large" if changed <= 1000 else "too-large"
    added = added_lines(diff)
    risks = risk_signals(added)
    depth, why = suggest_depth(changed, risks, files)
    tests_changed = [f["path"] for f in files if TEST_PATH.search(f["path"])]
    cfg = load_config(root)
    cands = purpose_candidates(src_root, files, commits, pr_body, out("rev-parse", "--abbrev-ref", "HEAD", cwd=root))
    instr = instruction_files(src_root, files)
    ruff_note, hints = ruff_hints(src_root, added) if files else (None, [])
    used_by = callers(src_root, added, diff) if files else []
    learnings = ""
    for lp in (Path(root, LEARNINGS),):
        if lp.is_file():
            learnings = lp.read_text(errors="ignore")[-3000:]

    meta.update({"repo_root": src_root, "source_kind": source_kind, "kind": kind, "description": desc,
                 "base": base, "head": head, "reviewed_commit": head if committed else commit_ref(root, "HEAD"),
                 "head_at_collection": commit_ref(root, "HEAD"),
                 "files": files, "added": added_n, "deleted": deleted_n, "size": size, "risk": risks,
                 "suggested_depth": depth, "tests_changed": tests_changed, "untracked": untracked,
                 "purpose_candidates": cands, "instruction_files": instr, "github": gh, "config": cfg,
                 "collection_status": "completed",
                 "comment_context_status": ("partial" if warnings else "completed") if gh else "not-applicable",
                 "collection_warnings": warnings})
    (pkg / "meta.json").write_text(json.dumps(meta, indent=2))

    L = [f"# Review context: {desc}",
         f"- Size: {len(files)} files, +{added_n}/-{deleted_n} ({size}) · risk signals: {', '.join(risks) or 'none'}"
         f" · suggested depth: {depth} ({why})",
         f"- Read source from: {src_root} ({source_kind})" + ("" if committed else ", the live checkout"),
         f"- Reviewed commit: {meta['reviewed_commit'][:12]}" + ("" if committed else " + uncommitted changes"),
         f"- HTML walkthrough default: {cfg.get('html', 'auto')}", "", "## Files"]
    L += [f"- {f['status']:8} {f['path']} (+{f['added']}/-{f['deleted']})" for f in files] or ["- none"]
    L += ["", "## Commits", commits or "(none: uncommitted changes only)"]
    if pr_body:
        L += ["", "## PR description", pr_body.strip()[:4000]]
    if warnings:
        L += ["", "## PR comment context incomplete (say so under Not checked)", *[f"- {w}" for w in warnings]]
    L += ["", "## Purpose documents (read the relevant ones; never ask unless spec mode found none)"]
    L += [f"- {c['path']}: {c['why']}" + (f' ("{c["title"]}")' if c["title"] else "") for c in cands] or ["- none found"]
    L += ["", "## Project rules (read these)", *([f"- {p}" for p in instr] or ["- none"])]
    if learnings:
        L += ["", f"## Learnings from earlier reviews ({LEARNINGS}); obey them", learnings.strip()]
    L += ["", "## Static hints: ruff bug rules on added lines (leads to check, not findings)"]
    L += hints or [f"- {ruff_note}" if ruff_note else "- none"]
    if used_by:
        L += ["", "## Changed Python symbols and their call sites (check callers when a contract changed)", *[f"- {u}" for u in used_by]]
    L += ["", "## Tests changed", *([f"- {p}" for p in tests_changed] or ["- none"])]
    if untracked:
        L += ["", "## Untracked files included", *[f"- {u}" for u in untracked]]
    summary = "\n".join(L) + "\n"
    (pkg / "summary.md").write_text(summary)
    print(summary)
    if size == "empty":
        print(f"EMPTY: nothing to review for {desc}")
    elif not a.no_diff and numbered.count("\n") <= INLINE_DIFF_MAX_LINES:
        print("## Numbered diff (left column = line number in the new file; cite these)")
        print(numbered)
    else:
        print(f"## Diff is in {pkg / 'diff-numbered.txt'} ({numbered.count(chr(10))} lines); read it in parts")
    print(f"PKG={pkg}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        die(str(exc))
