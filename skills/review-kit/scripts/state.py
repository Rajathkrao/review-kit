#!/usr/bin/env python3
"""Track review-kit run progress so any later session can resume a run.

  state.py PKG STAGE [--note TEXT] [--args "ORIGINAL ARGS"]   mark STAGE done
                                                               (`reported` checks the run is complete; --force skips that)
  state.py --list [REPO_DIR]                                   list runs, newest first
  state.py --show PKG                                          print one run's state
  state.py --cleanup PKG                                       remove the run's temporary source worktree
                                                               (even if keep_source kept it; never if it has local changes)
  state.py --check-source PKG                                  validate committed source before resuming

Stages, in order: packaged, contract, lenses, tests, verified, reported.
Marking `reported` also removes the run's temporary source worktree, unless the
config sets "keep_source": true or the worktree has local changes.
"""
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import remove_source, commit_ref, source_clean, html_decision  # noqa: E402
from review_data import load_object, validate_review  # noqa: E402

# Lens outputs a finished run must have, by mode (quick reviews inline and needs none).
MIN_LENSES = {"deep": 4, "full": 5, "pr": 3, "arch": 2, "spec": 1, "standards": 1, "test": 1}


def missing_for_report(pkg, st):
    """What a run still needs before it may be marked `reported`. Empty list = complete."""
    pkg = Path(pkg)
    try:
        meta = load_object(pkg / "meta.json")
    except ValueError:
        return []  # not a collector package (e.g. a hand-made --out folder): nothing to enforce
    missing = []
    try:
        fx = validate_review(load_object(pkg / "findings.json"), meta)
    except ValueError as exc:
        return [f"a valid findings.json ({exc}); run scripts/review_data.py"]
    if not (pkg / "report.md").is_file() or not (pkg / "report.md").read_text().strip():
        missing.append("report.md (save the final report text)")
    if fx["execution_status"] != "completed":
        return missing  # failed/partial/empty runs are reported honestly, without the full pipeline
    mode = meta.get("mode") or st.get("mode") or "review"
    args = st.get("args") or ""
    need = MIN_LENSES.get(mode, 0)
    have = len(list((pkg / "candidates").glob("*.json")))
    if have < need:
        missing.append(f"lens results: {have} of at least {need} files in candidates/ ({mode} mode runs "
                       f"its lenses as rk:lens-reviewer subagents whatever the diff size)")
    if need and fx.get("findings") is not None and not (pkg / "candidates-merged.json").exists():
        missing.append("candidates-merged.json and the rk:finding-verifier pass")
    decision = html_decision((meta.get("config") or {}).get("html", "auto"), mode)
    wants_html = ("--html" in args.split() and not decision.startswith("no")) or \
                 (decision.startswith("yes") and "--no-html" not in args.split())
    if wants_html and not (pkg / "review.html").is_file():
        missing.append("review.html (write explainer.json per references/html-explainer.md, then run render_html.py)")
    return missing

STAGES = ["packaged", "contract", "lenses", "tests", "verified", "reported"]


def check_source(pkg):
    """Reject reused committed context if its revision or visible files changed."""
    try:
        meta = json.loads((Path(pkg) / "meta.json").read_text())
        if meta.get("source_kind") == "working-tree":
            print("Live working tree: compare HEAD and diff with the saved run before resuming.")
            return
        root = meta["repo_root"]
        if not Path(root).is_dir() or commit_ref(root, "HEAD") != meta["reviewed_commit"] or not source_clean(root):
            raise ValueError("reviewed source is missing or changed")
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        sys.exit(f"Cannot reuse source: {exc}; start a fresh run before reusing results.")
    print("Reviewed source is unchanged.")


def load(pkg):
    try:
        data = json.loads((Path(pkg) / "state.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {"stages_done": [], "notes": []}


def mark(pkg, stage, note=None, args=None, force=False):
    pkg = Path(pkg)
    if stage not in STAGES:
        sys.exit(f"unknown stage {stage}; expected one of {', '.join(STAGES)}")
    if not pkg.is_dir():
        sys.exit(f"no such run folder: {pkg}")
    st = load(pkg)
    done = [s for s in st.get("stages_done", []) if s in STAGES and s != stage] + [stage]
    st["stages_done"] = sorted(done, key=STAGES.index)
    # Stages can be skipped (e.g. `tests` in deep mode), so "next" follows the furthest stage
    # reached; once `reported` is done the run is complete.
    last = max(STAGES.index(s) for s in st["stages_done"])
    st["next"] = STAGES[last + 1] if last + 1 < len(STAGES) else None
    st["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    if note:
        st.setdefault("notes", []).append(f"{stage}: {note}")
    if args is not None:
        st["args"] = args
    msg = ""
    if stage == "reported" and not force:
        missing = missing_for_report(pkg, st)
        if missing:
            sys.exit("Not finished, so not marked reported. Still needed:\n- " + "\n- ".join(missing)
                     + "\nDo these steps, then mark reported again. (--force only if the user asked to stop early.)")
    if stage == "reported" and (pkg / "meta.json").exists():
        meta = json.loads((pkg / "meta.json").read_text())
        if not (meta.get("config") or {}).get("keep_source"):
            result = remove_source(pkg / "meta.json")
            if result != "nothing to remove":
                msg = f"; source worktree {result}"
                st.setdefault("notes", []).append(f"source worktree {result}")
    (pkg / "state.json").write_text(json.dumps(st, indent=2))
    print(f"{pkg.name}: {stage} done, next: {st['next'] or 'complete'}{msg}")


def list_runs(repo):
    root = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True).stdout.strip() or repo
    runs = Path(root, ".review-kit", "runs")
    if not runs.is_dir():
        print("No review-kit runs in this repo.")
        return
    rows = []
    for d in sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True):
        st = load(d)
        files = [f for f in ("report.md", "findings.json", "review.html") if (d / f).exists()]
        rows.append(f"{d}\n    mode={st.get('mode')} target={st.get('target')} args={st.get('args', '')!r} "
                    f"done={','.join(st.get('stages_done', []))} next={st.get('next') or 'complete'} "
                    f"files={','.join(files) or '-'}")
    print("\n".join(rows[:20]) if rows else "No review-kit runs in this repo.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "--list":
        list_runs(a[1] if len(a) > 1 else ".")
    elif a[0] == "--show":
        print(json.dumps(load(a[1]), indent=2))
    elif a[0] == "--cleanup":
        print(remove_source(Path(a[1]) / "meta.json", honor_keep=False))
    elif a[0] == "--check-source":
        check_source(a[1])
    elif len(a) >= 2:
        note = a[a.index("--note") + 1] if "--note" in a else None
        args = a[a.index("--args") + 1] if "--args" in a else None
        mark(a[0], a[1], note, args, force="--force" in a)
    else:
        sys.exit(__doc__)
