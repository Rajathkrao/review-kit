#!/usr/bin/env python3
"""Build the harder eval fixtures (git repos) from the plain-file sources in evals/hard/.

    build_hard_fixtures.py OUTDIR

Each evals/hard/<fixture>/ holds:
  fixture.json   {"main_message": "...", "branches": [{"name", "dir", "message", "delete": [...]}]}
  main/          the tree committed on main
  <dir>/         files that a branch adds or replaces on top of main (a full copy of each file)

Sources are kept as plain files (not a tarball) so a reviewer of this repo can read every case.
Commits use fixed dates and identities so a rebuild gives the same history.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "hard"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
       "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args, date=None):
    env = dict(ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def copy_tree(src, dst):
    for f in sorted(src.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            t = dst / f.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, t)


def build(fixture_dir, out):
    spec = json.loads((fixture_dir / "fixture.json").read_text())
    repo = out / fixture_dir.name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    copy_tree(fixture_dir / "main", repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", spec["main_message"], date="2026-09-01T10:00:00Z")
    for i, br in enumerate(spec["branches"]):
        git(repo, "checkout", "-q", "-b", br["name"], "main")
        for rel in br.get("delete", []):
            git(repo, "rm", "-q", rel)
        copy_tree(fixture_dir / br["dir"], repo)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", br["message"], date=f"2026-09-{10 + i:02d}T15:30:00Z")
    git(repo, "checkout", "-q", "main")


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: build_hard_fixtures.py OUTDIR")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for d in sorted(p for p in SRC.iterdir() if (p / "fixture.json").is_file()):
        if (out / d.name).exists():
            sys.exit(f"already exists: {out / d.name}")
        build(d, out)
        print(f"built {d.name}")


if __name__ == "__main__":
    main()
