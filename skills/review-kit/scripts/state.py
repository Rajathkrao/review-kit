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
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import remove_source, html_decision, validate_source  # noqa: E402
from review_data import load_object, validate_review  # noqa: E402

# Lens outputs a finished run must have, by mode (quick reviews inline and needs none).
MIN_LENSES = {"deep": 4, "full": 5, "pr": 3, "arch": 2, "spec": 1, "standards": 1, "test": 1}


def missing_for_report(pkg, st):
    """What a run still needs before it may be marked `reported`. Empty list = complete."""
    pkg = Path(pkg)
    try:
        meta = load_object(pkg / "meta.json")
    except ValueError as exc:
        return [f"valid meta.json ({exc})"]
    missing = []
    try:
        fx = validate_review(load_object(pkg / "findings.json"), meta)
    except ValueError as exc:
        return [f"a valid findings.json ({exc}); run scripts/review_data.py"]
    if not (pkg / "report.md").is_file() or not (pkg / "report.md").read_text().strip():
        missing.append("report.md (save the final report text)")
    if fx["execution_status"] != "completed":
        return missing  # failed/partial/empty runs are reported honestly, without the full pipeline
    if not (pkg / "contract.md").is_file() or not (pkg / "contract.md").read_text().strip():
        missing.append("contract.md (record the change's purpose)")
    mode = meta.get("mode") or st.get("mode") or "review"
    args = st.get("args") or ""
    if mode in ("test", "full") or "tests" in st.get("stages_done", []):
        if not (pkg / "test-results.md").is_file() or not (pkg / "test-results.md").read_text().strip():
            missing.append("test-results.md (record checks run, declined or unavailable)")
    need = 0 if mode == "pr" and "--quick" in args.split() else MIN_LENSES.get(mode, 0)
    have, raised = 0, 0
    for c in (pkg / "candidates").glob("*.json"):
        try:
            data = load_object(c)
            if not isinstance(data.get("candidates"), list):
                raise ValueError("requires a candidates array")
            # The optional second model supplements the mode's lenses; it cannot replace one.
            if c.stem != "second-model":
                have += 1
            raised += len(data["candidates"])
            if any(isinstance(c, dict) and c.get("needs_test") for c in data["candidates"]):
                if not (pkg / "test-results.md").is_file() or not (pkg / "test-results.md").read_text().strip():
                    missing.append(f"test-results.md (test requested by {c.name})")
        except ValueError as exc:
            missing.append(f"valid lens output {c.name} ({exc})")
    if have < need:
        missing.append(f"lens results: {have} of at least {need} files in candidates/ ({mode} mode runs "
                       f"its lenses as rk:lens-reviewer subagents whatever the diff size)")
    if raised:
        try:
            merged = json.loads((pkg / "candidates-merged.json").read_text())
            if not isinstance(merged, (list, dict)):
                raise ValueError("expected merged candidates")
        except (OSError, ValueError):
            missing.append("candidates-merged.json and the rk:finding-verifier pass")
    decision = html_decision((meta.get("config") or {}).get("html", "auto"), mode)
    wants_html = ("--html" in args.split() and not decision.startswith("no")) or \
                 (decision.startswith("yes") and "--no-html" not in args.split())
    if wants_html and not (pkg / "review.html").is_file():
        missing.append("review.html (write explainer.json per references/html-explainer.md, then run render_html.py)")
    if meta.get("source_kind"):
        try:
            validate_source(meta, pkg)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            missing.append(f"unchanged reviewed source ({exc}); start a fresh run")
    return missing

STAGES = ["packaged", "contract", "lenses", "tests", "verified", "reported"]


def check_source(pkg):
    """Reject reused committed context if its revision or visible files changed."""
    try:
        meta = load_object(Path(pkg) / "meta.json")
        validate_source(meta, pkg)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        sys.exit(f"Cannot reuse source: {exc}; start a fresh run before reusing results.")
    print("Reviewed source is unchanged.")


def load(pkg):
    path = Path(pkg) / "state.json"
    data = load_object(path, optional=True)
    done = data.get("stages_done", [])
    if (not isinstance(done, list) or any(s not in STAGES for s in done) or
            len(set(done)) != len(done) or not isinstance(data.get("notes", []), list)):
        raise ValueError(f"Invalid run state in {path}")
    data["stages_done"] = done
    data.setdefault("notes", [])
    last = max((STAGES.index(s) for s in done), default=-1)
    data["next"] = STAGES[last + 1] if last + 1 < len(STAGES) else None
    return data


def mark(pkg, stage, note=None, args=None, force=False):
    pkg = Path(pkg)
    if stage not in STAGES:
        sys.exit(f"unknown stage {stage}; expected one of {', '.join(STAGES)}")
    if not pkg.is_dir():
        sys.exit(f"no such run folder: {pkg}")
    st = load(pkg)
    if "reported" in st["stages_done"] and stage != "reported":
        sys.exit("Run is already reported; start a fresh run instead of reusing terminal results.")
    if "reported" in st["stages_done"]:
        print(f"{pkg.name}: already reported, next: complete")
        return
    if any(STAGES.index(s) > STAGES.index(stage) for s in st["stages_done"]):
        # Revisiting an upstream stage invalidates downstream evidence and resume caches.
        paths = ["report.md", "review.html", "review-payload.json", "review-preview.md", "explainer.json"]
        if stage == "packaged":
            paths.append("contract.md")
        if STAGES.index(stage) < STAGES.index("verified"):
            paths += ["findings.json", "candidates-merged.json"]
        if STAGES.index(stage) < STAGES.index("tests"):
            paths += ["test-results.md", "test-plan.json"]
        if STAGES.index(stage) < STAGES.index("lenses"):
            paths += [str(p.relative_to(pkg)) for p in (pkg / "candidates").glob("*.json")]
            paths += ["second-model-status.json", "codex-output.json"]
        for name in paths:
            (pkg / name).unlink(missing_ok=True)
        st["stages_done"] = [s for s in st["stages_done"] if STAGES.index(s) <= STAGES.index(stage)]
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
    with tempfile.NamedTemporaryFile(mode="w", dir=pkg, prefix=".state-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(st, indent=2))
    try:
        temporary.replace(pkg / "state.json")
    finally:
        temporary.unlink(missing_ok=True)
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
        try:
            st = load(d)
        except ValueError as exc:
            rows.append(f"{d}\n    invalid state: {exc}; start a fresh run")
            continue
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
