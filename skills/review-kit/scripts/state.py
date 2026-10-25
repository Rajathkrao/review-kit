#!/usr/bin/env python3
"""Track review-kit run progress so any later session can resume a run.

  state.py PKG STAGE [--note TEXT] [--args "ORIGINAL ARGS"]   mark STAGE done
  state.py --list [REPO_DIR]                                   list runs, newest first
  state.py --show PKG                                          print one run's state
  state.py --cleanup PKG                                       remove the run's temporary source worktree

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
from collect import remove_source  # noqa: E402

STAGES = ["packaged", "contract", "lenses", "tests", "verified", "reported"]


def load(pkg):
    try:
        data = json.loads((Path(pkg) / "state.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {"stages_done": [], "notes": []}


def mark(pkg, stage, note=None, args=None):
    pkg = Path(pkg)
    if stage not in STAGES:
        sys.exit(f"unknown stage {stage}; expected one of {', '.join(STAGES)}")
    if not pkg.is_dir():
        sys.exit(f"no such run folder: {pkg}")
    st = load(pkg)
    done = [s for s in st.get("stages_done", []) if s in STAGES and s != stage] + [stage]
    st["stages_done"] = sorted(done, key=STAGES.index)
    remaining = [s for s in STAGES if s not in st["stages_done"]]
    st["next"] = remaining[0] if remaining else None
    st["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    if note:
        st.setdefault("notes", []).append(f"{stage}: {note}")
    if args is not None:
        st["args"] = args
    msg = ""
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
        print(remove_source(Path(a[1]) / "meta.json"))
    elif len(a) >= 2:
        note = a[a.index("--note") + 1] if "--note" in a else None
        args = a[a.index("--args") + 1] if "--args" in a else None
        mark(a[0], a[1], note, args)
    else:
        sys.exit(__doc__)
