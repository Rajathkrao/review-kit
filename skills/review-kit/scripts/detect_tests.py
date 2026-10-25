#!/usr/bin/env python3
"""Propose test commands scoped to a review package's changed files.

Writes PKG/test-plan.json and prints it. Never runs anything.
Covers nx, Angular CLI (Karma/Jest), Jest, Vitest, Mocha via npm scripts,
dotnet (sln/csproj with test projects), pytest, go.
"""
import json
import re
import sys
from pathlib import Path


def load(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def nearest(root: Path, start: Path, names):
    cur = start
    while True:
        for n in names:
            hits = list(cur.glob(n))
            if hits:
                return hits[0]
        if cur == root or cur == cur.parent:
            return None
        cur = cur.parent


def pm(root: Path):
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npx"


def js_plans(root, changed, base):
    plans = []
    js_files = [f for f in changed if re.search(r"\.(ts|tsx|js|jsx|mjs|cjs|html|scss)$", f)]
    if not js_files:
        return plans
    runner = pm(root)
    x = "npx" if runner == "npx" else runner
    if (root / "nx.json").exists():
        b = f" --base={base}" if base and base != "WORKTREE" else ""
        plans.append({"label": "Affected unit tests (nx)", "cost": "low-medium",
                      "command": f"{x} nx affected -t test{b} --head=HEAD",
                      "covers": "every nx project affected by the change"})
    pkg = load(root / "package.json") or {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    scripts = pkg.get("scripts", {})
    rel = " ".join(js_files[:30])
    if "vitest" in deps:
        plans.append({"label": "Related tests (vitest)", "cost": "low",
                      "command": f"{x} vitest related --run {rel}",
                      "covers": "test files that import the changed files"})
    if "jest" in deps or any("jest" in s for s in scripts.values()):
        plans.append({"label": "Related tests (jest)", "cost": "low",
                      "command": f"{x} jest --ci --findRelatedTests {rel}",
                      "covers": "test files that import the changed files"})
    if (root / "angular.json").exists() and not (root / "nx.json").exists():
        specs = []
        for f in js_files:
            p = Path(f)
            spec = p.with_name(p.stem + ".spec.ts") if not p.name.endswith(".spec.ts") else p
            if (root / spec).exists():
                specs.append(str(spec))
        inc = " ".join(f"--include={s}" for s in specs[:20])
        plans.append({"label": "Angular specs for changed files", "cost": "medium",
                      "command": f"{x} ng test --watch=false {inc}".strip(),
                      "covers": ", ".join(specs[:5]) or "whole Angular test target (no matching specs found)"})
    if "node --test" in scripts.get("test", ""):
        stems = {Path(f).name.split(".")[0] for f in js_files}
        tfiles = sorted({f for f in js_files if re.search(r"\.(test|spec)\.", f)} |
                        {str(p.relative_to(root)) for p in root.rglob("*.test.*")
                         if "node_modules" not in p.parts and p.name.split(".")[0] in stems})
        if tfiles:
            plans.append({"label": "Changed and related test files (node:test)", "cost": "low",
                          "command": "node --test " + " ".join(tfiles),
                          "covers": ", ".join(tfiles)})
    if "test" in scripts:
        plans.append({"label": "Project test script", "cost": "medium-high",
                      "command": f"{'npm' if runner == 'npx' else runner} test",
                      "covers": f"package.json script: {scripts.get('test', '')}"})
    return plans


def dotnet_plans(root, changed):
    cs = [f for f in changed if f.endswith((".cs", ".csproj", ".razor", ".cshtml"))]
    if not cs:
        return []
    plans = []
    test_projects = [p for p in root.rglob("*.csproj")
                     if re.search(r"(Tests?|Spec|IntegrationTests?)\.csproj$", p.name)
                     or "Microsoft.NET.Test.Sdk" in p.read_text(errors="ignore")]
    owners = set()
    for f in cs:
        proj = nearest(root, (root / f).parent, ["*.csproj"])
        if proj:
            owners.add(proj)
    related = []
    for tp in test_projects:
        txt = tp.read_text(errors="ignore")
        if tp in owners or any(o.stem in txt for o in owners):
            related.append(tp)
    classes = sorted({Path(f).stem for f in cs if f.endswith(".cs") and not re.search(r"Tests?\.cs$", f)})
    flt = "|".join(f"FullyQualifiedName~{c}" for c in classes[:8])
    for tp in related[:3]:
        rp = tp.relative_to(root)
        if flt:
            plans.append({"label": f"Filtered tests in {tp.stem}", "cost": "low",
                          "command": f"dotnet test {rp} --filter \"{flt}\"",
                          "covers": f"tests whose names mention {', '.join(classes[:8])}"})
        plans.append({"label": f"All tests in {tp.stem}", "cost": "medium",
                      "command": f"dotnet test {rp}", "covers": "the test project that references the changed code"})
    if not related:
        sln = next(iter(root.glob("*.sln")), None) or next(iter(root.glob("*.slnx")), None)
        plans.append({"label": "Solution tests", "cost": "high",
                      "command": f"dotnet test {sln.name}" if sln else "dotnet test",
                      "covers": "no test project found referencing the changed project; runs everything"})
    return plans


def py_plans(root, changed):
    py = [f for f in changed if f.endswith(".py")]
    if not py:
        return []
    tests = [f for f in py if re.search(r"(^|/)test_|_test\.py$", f)]
    targets = " ".join(tests) or "tests"
    return [{"label": "pytest (changed tests or tests/)", "cost": "low-medium",
             "command": f"python -m pytest -q {targets}", "covers": targets}]


def go_plans(root, changed):
    pkgs = sorted({"./" + str(Path(f).parent) for f in changed if f.endswith(".go")})
    if not pkgs:
        return []
    return [{"label": "go test changed packages", "cost": "low",
             "command": f"go test {' '.join(pkgs)}", "covers": ", ".join(pkgs)}]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: detect_tests.py PKG")
    pkgdir = Path(sys.argv[1])
    meta = load(pkgdir / "meta.json")
    if not meta:
        sys.exit("meta.json missing; run collect.py first")
    root = Path(meta["repo_root"])
    changed = [f["path"] for f in meta["files"] if f["status"] != "deleted"]
    base = meta.get("base")
    plans = js_plans(root, changed, base) + dotnet_plans(root, changed) + py_plans(root, changed) + go_plans(root, changed)
    order = {"low": 0, "low-medium": 1, "medium": 2, "medium-high": 3, "high": 4}
    plans.sort(key=lambda p: order.get(p["cost"], 5))
    instr = []
    for p in meta.get("instruction_files", []):
        try:
            txt = (root / p).read_text(errors="ignore")
        except OSError:
            continue
        for line in txt.splitlines():
            if re.search(r"\b(test|tests)\b", line, re.I) and re.search(r"`[^`]+`", line):
                instr.append(f"{p}: {line.strip()[:200]}")
    result = {"plans": plans, "instruction_hints": instr[:10],
              "note": "Commands are proposals. Ask the user before running unless --run was given."}
    (pkgdir / "test-plan.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
