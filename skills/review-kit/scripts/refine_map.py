#!/usr/bin/env python3
"""Structure map for refine mode: measured facts about the code, in one call.

Reads the target files (Python through the ast module, other languages by line count and git
history only) and prints what a refactor should be judged against:

- a scoreboard (code lines, functions, longest function, deepest nesting, special cases)
- special cases: swallowed exceptions, sleeps, one-value branches, flag parameters, skipped tests,
  type switches, workaround comments
- shallow pieces: pass-through wrappers, base classes with one subclass
- copies: function bodies with the same shape, literals repeated across files
- names defined here that nothing else in the repository mentions
- which target files import which, import cycles, and how many files depend on each
- git history: how often each file changes, and files that change together without importing
  each other

Everything printed is a lead to check, never a finding. Standard library only, read-only.

Usage:
  refine_map.py [PATH ...] [--root DIR] [--json OUT]      print the map, optionally save the scoreboard
  refine_map.py [PATH ...] --compare BEFORE.json           print the scoreboard before and after
                                                           (no PATH: the files BEFORE.json measured)
"""
import argparse
import ast
import json
import re
import subprocess
import sys
import tokenize
from collections import Counter, defaultdict
from pathlib import Path

MAX_FILES = 400
MAX_ITEMS = 12
HISTORY_COMMITS = 400
SKELETON_OVER = 1500
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php",
            ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".scala", ".sh"}
MARKER = re.compile(r"\b(TODO|FIXME|HACK|XXX|workaround|temporary|for now|special[- ]case|legacy)\b", re.I)
SUPPRESS = re.compile(r"#\s*(noqa|type:\s*ignore|pragma:\s*no cover|pylint:\s*disable)")
# Shown in this order: the kinds most likely to hide a requirement nobody wrote down come first.
KINDS = ["swallowed exception", "sleep", "skipped test", "workaround note", "silenced check",
         "flag parameter", "type switch", "one-value branch"]
NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.match_case, ast.BoolOp)
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
SCORE_KEYS = [("code_lines", "Code lines"), ("functions", "Functions and methods"),
              ("longest_function", "Longest function (lines)"), ("max_nesting", "Deepest nesting"),
              ("branches", "Branch points"), ("special_cases", "Special cases"),
              ("pass_throughs", "Pass-through wrappers"), ("copies", "Copied function bodies"),
              ("unused", "Names nothing else mentions"), ("cycles", "Import cycles")]


def git(root, *args):
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def repo_files(root, paths):
    """Tracked and untracked-but-not-ignored files under the given paths, relative to root."""
    listed = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", *(paths or ["."]))
    if listed:
        return [f for f in dict.fromkeys(listed.splitlines()) if (root / f).is_file()]
    found = []
    for p in paths or ["."]:
        full = root / p
        found += [full] if full.is_file() else sorted(q for q in full.rglob("*") if q.is_file() and ".git" not in q.parts)
    return [str(f.relative_to(root)) for f in found]


def read(path):
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def nesting(node, depth=0):
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, FUNC + (ast.ClassDef, ast.Lambda)):
            continue
        deepest = max(deepest, nesting(child, depth + isinstance(child, NESTING)))
    return deepest


def body_without_docstring(fn):
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


class Shape(ast.NodeTransformer):
    """Blank out names and constants, so two bodies that differ only in those compare equal."""

    def visit_Name(self, node):
        return ast.Name(id="_", ctx=node.ctx)

    def visit_Constant(self, node):
        return ast.Constant(value=0)

    def visit_arg(self, node):
        return ast.arg(arg="_")

    def visit_Attribute(self, node):
        return ast.Attribute(value=self.visit(node.value), attr="_", ctx=node.ctx)


def shape_of(body):
    module = ast.Module(body=[Shape().visit(ast.parse(ast.unparse(stmt)).body[0]) for stmt in body], type_ignores=[])
    return ast.dump(module, annotate_fields=False)


def is_pass_through(fn):
    """The whole body hands the function's own parameters to one other call."""
    body = body_without_docstring(fn)
    if len(body) != 1 or not isinstance(body[0], (ast.Return, ast.Expr)):
        return False
    call = body[0].value
    if isinstance(call, ast.Await):
        call = call.value
    if not isinstance(call, ast.Call) or fn.decorator_list:
        return False
    params = {a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs} - {"self", "cls"}
    if not params:
        return False
    values = list(call.args) + [k.value for k in call.keywords]
    plain = [v.value if isinstance(v, ast.Starred) else v for v in values]
    return bool(plain) and all(isinstance(v, ast.Name) and v.id in params for v in plain)


def swallowed(handler):
    return all(isinstance(s, (ast.Pass, ast.Continue)) or
               (isinstance(s, ast.Return) and (s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None)))
               or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
               for s in handler.body)


def call_name(node):
    f = node.func
    return f"{call_name_of(f.value)}.{f.attr}" if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def call_name_of(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def literal_branch(test):
    """`x == "gold"` or `x in ("a", "b")`: a branch written for particular values."""
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            right = node.comparators[0]
            items = right.elts if isinstance(right, (ast.Tuple, ast.List, ast.Set)) else [right]
            if items and all(isinstance(i, ast.Constant) and isinstance(i.value, str) and i.value for i in items) \
                    and not (isinstance(node.left, ast.Name) and node.left.id == "__name__"):
                return ", ".join(repr(i.value) for i in items[:3])
    return ""


def analyse_python(rel, text, is_test):
    """Return the facts for one Python file, or None if it does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    info = {"functions": [], "special": [], "pass_through": [], "classes": [], "defs": [], "imports": set(),
            "literals": [], "branches": 0, "max_nesting": 0, "skeleton": []}
    try:
        comments = [(t.start[0], t.string) for t in tokenize.generate_tokens(iter(text.splitlines(True)).__next__)
                    if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, SyntaxError):
        comments = []
    for i, comment in comments:
        if SUPPRESS.search(comment):
            info["special"].append((i, "silenced check", comment.strip()[:60]))
        elif MARKER.search(comment):
            info["special"].append((i, "workaround note", comment.strip()[:70]))
    docstrings = set()
    for node in ast.walk(tree):  # dictionary keys and lookups are field names, not repeated values
        if isinstance(node, ast.Dict):
            docstrings.update(id(k) for k in node.keys if k is not None)
        elif isinstance(node, ast.Subscript):
            docstrings.add(id(node.slice))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "pop", "setdefault", "getattr") and node.args:
            docstrings.add(id(node.args[0]))
    for node in ast.walk(tree):
        if isinstance(node, FUNC + (ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in tree.body:
        if isinstance(node, FUNC + (ast.ClassDef,)) and not node.name.startswith("__"):
            info["defs"].append((node.name, node.lineno))
    for node in ast.walk(tree):
        info["branches"] += isinstance(node, BRANCH)
        if isinstance(node, ast.Import):
            info["imports"].update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            info["imports"].add(base)
            info["imports"].update(f"{base}.{a.name}" if node.module else f"{base}{a.name}" for a in node.names)
        elif isinstance(node, ast.ClassDef):
            bases = [call_name_of(b) for b in node.bases if call_name_of(b)]
            info["classes"].append((node.name, node.lineno, bases))
            info["skeleton"].append((node.lineno, f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"))
        elif isinstance(node, FUNC):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            deep = nesting(node)
            info["max_nesting"] = max(info["max_nesting"], deep)
            body = body_without_docstring(node)
            info["functions"].append({"name": node.name, "line": node.lineno, "length": length, "nesting": deep,
                                      "shape": shape_of(body) if len(body) >= 3 and not is_test else ""})
            info["skeleton"].append((node.lineno, f"  def {node.name}({ast.unparse(node.args)})  [{length} lines]"))
            if is_pass_through(node) and not is_test:
                info["pass_through"].append((node.name, node.lineno, call_name(body[0].value.value if isinstance(body[0].value, ast.Await) else body[0].value)))
            defaults = node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
            flags = [d for d in defaults if isinstance(d, ast.Constant) and isinstance(d.value, bool)]
            if flags and not is_test:
                info["special"].append((node.lineno, "flag parameter", f"{node.name}() switches behavior on a True/False argument"))
            for dec in node.decorator_list:
                if re.search(r"\b(skip|skipIf|skipUnless|xfail)\b", ast.unparse(dec)):
                    info["special"].append((node.lineno, "skipped test", node.name))
        elif isinstance(node, ast.ExceptHandler) and swallowed(node):
            info["special"].append((node.lineno, "swallowed exception", f"except {ast.unparse(node.type) if node.type else ''}: nothing happens".replace(" :", ":")))
        elif isinstance(node, ast.Call) and call_name(node) in ("time.sleep", "asyncio.sleep", "sleep") and not is_test:
            info["special"].append((node.lineno, "sleep", ast.unparse(node)[:60]))
        elif isinstance(node, ast.If) and not is_test:
            values = literal_branch(node.test)
            if values:
                info["special"].append((node.lineno, "one-value branch", f"if … {values}"))
            elif any(isinstance(n, ast.Call) and call_name(n) == "isinstance" for n in ast.walk(node.test)) \
                    and node.orelse and isinstance(node.orelse[0], ast.If):
                info["special"].append((node.lineno, "type switch", ast.unparse(node.test)[:60]))
        elif isinstance(node, ast.Constant) and id(node) not in docstrings and not is_test:
            v = node.value
            if (isinstance(v, str) and re.fullmatch(r"[\w./:-]{8,80}", v) and not v.startswith("__")) or \
                    (isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000):
                info["literals"].append((repr(v), node.lineno))
    info["special"].sort(key=lambda item: (KINDS.index(item[1]), item[0]))
    info["skeleton"].sort()
    return info


def module_names(rel):
    """Dotted names a file can be imported by: `a/b/c.py` answers to a.b.c, b.c and c."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return {".".join(parts[i:]) for i in range(len(parts))} - {""}


def resolve_imports(rel, imports, by_name):
    """Target files that this file imports."""
    pkg = list(Path(rel).parent.parts)
    found = set()
    for imp in imports:
        if imp.startswith("."):
            level = len(imp) - len(imp.lstrip("."))
            base = pkg[:len(pkg) - (level - 1)] if level > 1 else pkg
            imp = ".".join(base + [p for p in imp.lstrip(".").split(".") if p])
        hit = by_name.get(imp) or by_name.get(imp.rsplit(".", 1)[0] if "." in imp else imp)
        if hit and hit != rel:
            found.add(hit)
    return found


def find_cycles(graph):
    """Each import cycle once, as a list of files."""
    cycles, seen = [], set()

    def walk(node, path):
        for nxt in sorted(graph.get(node, ())):
            if nxt in path:
                loop = path[path.index(nxt):]
                key = frozenset(loop)
                if key not in seen:
                    seen.add(key)
                    cycles.append(loop + [nxt])
            elif len(path) < 12:
                walk(nxt, path + [nxt])

    for start in sorted(graph):
        walk(start, [start])
    return cycles


def history(root, targets):
    """Commits per target file, and files that change in the same commits as a target."""
    log = git(root, "log", f"-{HISTORY_COMMITS}", "--no-merges", "--name-only", "--pretty=format:@@%h")
    commits = [[f for f in block.splitlines()[1:] if f.strip()] for block in log.split("@@") if block.strip()]
    target_set = set(targets)
    churn, together = Counter(), Counter()
    for files in commits:
        if len(files) > 30:  # a sweep (rename, formatter) says nothing about what belongs together
            continue
        hit = [f for f in files if f in target_set]
        churn.update(hit)
        for t in hit:
            together.update((t, other) for other in files if other != t and Path(other).suffix in CODE_EXT)
    return churn, together, len(commits)


def mention_counts(root, names):
    """How many tracked files mention each name as a whole word."""
    counts = {}
    for name in names:
        hits = git(root, "grep", "-l", "-w", "-F", "-I", "-e", name)
        counts[name] = len(hits.splitlines())
    return counts


def build(root, paths):
    files = [f for f in repo_files(root, paths) if Path(f).suffix in CODE_EXT][:MAX_FILES]
    is_test = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")
    per_file, parsed, unparsed = {}, {}, []
    for rel in files:
        text = read(root / rel)
        code = sum(1 for line in text.splitlines() if line.strip() and not line.strip().startswith(("#", "//")))
        per_file[rel] = {"code_lines": code}
        if rel.endswith(".py"):
            info = analyse_python(rel, text, bool(is_test.search(rel)))
            if info is None:
                unparsed.append(rel)
            else:
                parsed[rel] = info

    by_name = {}
    for rel in parsed:
        for name in module_names(rel):
            by_name.setdefault(name, rel)
    graph = {rel: resolve_imports(rel, info["imports"], by_name) for rel, info in parsed.items()}
    fan_in = Counter(dep for deps in graph.values() for dep in deps)
    cycles = find_cycles(graph)

    shapes = defaultdict(list)
    for rel, info in parsed.items():
        for fn in info["functions"]:
            if fn["shape"] and fn["length"] >= 4:
                shapes[fn["shape"]].append(f"{rel}:{fn['line']} {fn['name']}() [{fn['length']} lines]")
    copies = [group for group in shapes.values() if len(group) > 1]
    copies.sort(key=lambda g: -len(g))

    literal_sites = defaultdict(list)
    for rel, info in parsed.items():
        for value, line in info["literals"]:
            literal_sites[value].append(f"{rel}:{line}")
    repeated = [(v, sites) for v, sites in literal_sites.items()
                if len({s.split(":")[0] for s in sites}) >= 2]
    repeated.sort(key=lambda item: -len(item[1]))

    subclasses = defaultdict(list)
    class_at = {}
    for rel, info in parsed.items():
        for name, line, bases in info["classes"]:
            class_at[name] = f"{rel}:{line}"
            for base in bases:
                subclasses[base].append(name)
    lone_bases = [(base, class_at[base], kids[0]) for base, kids in subclasses.items()
                  if len(kids) == 1 and base in class_at]

    defs = [(name, f"{rel}:{line}") for rel, info in parsed.items() if not is_test.search(rel)
            for name, line in info["defs"] if not name.startswith(("test", "Test"))]
    counts = mention_counts(root, sorted({n for n, _ in defs})[:150]) if defs else {}
    unused = [(name, where) for name, where in defs if counts.get(name) == 1
              and len(re.findall(rf"\b{re.escape(name)}\b", read(root / where.split(":")[0]))) == 1]

    churn, together, n_commits = history(root, files)
    linked = []
    for (target, other), n in together.most_common():
        if n < 3 or n * 2 < churn[target]:
            continue
        if other in graph.get(target, ()) or target in graph.get(other, ()) or is_test.search(other) \
                or is_test.search(target) or not (root / other).is_file():
            continue
        if (other, target) in {(a, b) for a, b, _, _ in linked}:
            continue
        linked.append((target, other, n, churn[target]))

    functions = [dict(fn, file=rel) for rel, info in parsed.items() for fn in info["functions"]]
    special = sorted(((rel, *item) for rel, info in parsed.items() for item in info["special"]),
                     key=lambda item: KINDS.index(item[2]))
    pass_through = [(rel, *item) for rel, info in parsed.items() for item in info["pass_through"]]
    score = {
        "files": len(files),
        "code_lines": sum(f["code_lines"] for f in per_file.values()),
        "functions": len(functions),
        "longest_function": max((fn["length"] for fn in functions), default=0),
        "max_nesting": max((info["max_nesting"] for info in parsed.values()), default=0),
        "branches": sum(info["branches"] for info in parsed.values()),
        "special_cases": len(special),
        "pass_throughs": len(pass_through),
        "copies": sum(len(g) - 1 for g in copies),
        "unused": len(unused),
        "cycles": len(cycles),
    }
    return {"score": score, "files": files, "per_file": per_file, "parsed": parsed, "unparsed": unparsed,
            "graph": graph, "fan_in": fan_in, "cycles": cycles, "copies": copies, "repeated": repeated,
            "lone_bases": lone_bases, "unused": unused, "churn": churn, "linked": linked,
            "n_commits": n_commits, "functions": functions, "special": special, "pass_through": pass_through}


def capped(items, fmt, limit=MAX_ITEMS):
    lines = [fmt(i) for i in items[:limit]]
    if len(items) > limit:
        lines.append(f"- … and {len(items) - limit} more")
    return lines or ["- none"]


def render(m):
    s = m["score"]
    L = ["## Structure map (measured; every line is a lead to check, not a finding)",
         f"- Scoreboard: {s['code_lines']} code lines in {s['files']} files · {s['functions']} functions · "
         f"longest {s['longest_function']} lines · deepest nesting {s['max_nesting']} · {s['branches']} branch points · "
         f"**{s['special_cases']} special cases** · {s['pass_throughs']} pass-through wrappers · "
         f"{s['copies']} copied bodies · {s['unused']} unmentioned names · {s['cycles']} import cycles"]
    if m["unparsed"]:
        L.append(f"- Not parsed (syntax error): {', '.join(m['unparsed'][:5])}")
    other = [f for f in m["files"] if not f.endswith(".py")]
    if other:
        L.append(f"- {len(other)} non-Python files are counted by lines and git history only; read them yourself.")

    big = sorted(m["functions"], key=lambda fn: (-fn["length"], -fn["nesting"]))
    big = [fn for fn in big if fn["length"] >= 40 or fn["nesting"] >= 4]
    L += ["", "### Long or deeply nested functions",
          *capped(big, lambda fn: f"- {fn['file']}:{fn['line']} {fn['name']}(): {fn['length']} lines, nesting {fn['nesting']}", 8)]

    kinds = Counter(kind for _, _, kind, _ in m["special"])
    L += ["", "### Special cases (" + (", ".join(f"{n} {k}" for k, n in kinds.most_common()) or "none") + ")",
          *capped(m["special"], lambda i: f"- {i[0]}:{i[1]} {i[2]}: {i[3]}", 25)]

    L += ["", "### Shallow pieces (does deleting it lose anything?)",
          *capped(m["pass_through"], lambda i: f"- {i[0]}:{i[2]} {i[1]}() only forwards its arguments to {i[3] or 'another call'}()")]
    L += [f"- {where} {base} has one subclass ({kid})" for base, where, kid in m["lone_bases"][:MAX_ITEMS]]

    L += ["", "### Copies (same shape, different names or constants)",
          *capped(m["copies"], lambda g: "- " + " = ".join(g[:4]) + (f" (+{len(g) - 4})" if len(g) > 4 else ""))]
    if m["repeated"]:
        L += ["", "### Literals repeated across files (one value, several places to change)",
              *capped(m["repeated"], lambda i: f"- {i[0][:50]}: {', '.join(i[1][:4])}" + (f" (+{len(i[1]) - 4})" if len(i[1]) > 4 else ""), 8)]

    L += ["", "### Defined here, mentioned nowhere else in the repository (check dynamic use before deleting)",
          *capped(m["unused"], lambda i: f"- {i[1]} {i[0]}")]

    if len(m["parsed"]) > 1:
        L += ["", "### Imports inside the target (file → what it imports; used-by = files that import it)"]
        rows = sorted(m["graph"], key=lambda r: (-m["fan_in"][r], r))
        L += capped(rows, lambda r: f"- {r} (used by {m['fan_in'][r]}, changed {m['churn'][r]}×) → "
                    + (", ".join(sorted(m["graph"][r])) or "nothing in the target"), 30)
        L += [f"- CYCLE: {' → '.join(c)}" for c in m["cycles"][:6]]
        upside_down = [(r, d) for r in m["graph"] for d in m["graph"][r]
                       if m["fan_in"][r] >= 2 and m["churn"][d] >= 4 and m["churn"][d] >= 2 * max(m["churn"][r], 1)]
        L += [f"- STABLE ON VOLATILE: {r} (changed {m['churn'][r]}×, used by {m['fan_in'][r]}) imports {d} (changed {m['churn'][d]}×)"
              for r, d in upside_down[:6]]

    if m["n_commits"]:
        hot = [(f, n) for f, n in m["churn"].most_common(8) if n >= 2]
        L += ["", f"### Git history (last {m['n_commits']} commits): where change keeps landing",
              *capped(hot, lambda i: f"- {i[0]}: changed in {i[1]} commits")]
        L += ["", "### Files that change together but do not import each other (a link nothing shows)",
              *capped(m["linked"], lambda i: f"- {i[0]} and {i[1]}: together in {i[2]} of {i[0]}'s {i[3]} commits")]
    else:
        L += ["", "### Git history", "- no commits found: judge what changes together from the code alone"]

    if m["score"]["code_lines"] > SKELETON_OVER:
        L += ["", "### Skeleton (signatures only; read bodies where a lead points)"]
        for rel, info in m["parsed"].items():
            L.append(f"{rel}")
            L += [f"  {line:>5} {text}" for line, text in info["skeleton"]]
    return "\n".join(L) + "\n"


def compare(before, after):
    L = ["## Scoreboard: before and after", "", "| Measure | Before | After | Change |", "|---|---|---|---|"]
    for key, label in SCORE_KEYS:
        b, a = before.get(key, 0), after.get(key, 0)
        L.append(f"| {label} | {b} | {a} | {a - b:+d} |" if a != b else f"| {label} | {b} | {a} | same |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="files or folders (default: the whole repository)")
    ap.add_argument("--root", default="", help="repository root (default: git toplevel of the current folder)")
    ap.add_argument("--json", default="", help="also write the scoreboard to this file")
    ap.add_argument("--compare", default="", help="print the scoreboard against one saved earlier with --json")
    a = ap.parse_args()
    root = Path(a.root or git(".", "rev-parse", "--show-toplevel").strip() or ".").resolve()
    paths = [str(Path(p).resolve().relative_to(root)) if Path(p).is_absolute() else p for p in a.paths]
    before = json.loads(Path(a.compare).read_text()) if a.compare else {}
    paths = paths or before.get("paths", [])
    if before.get("paths"):  # files deleted by the refactor no longer exist; that is the point
        paths = [p for p in paths if (root / p).exists()] or ["."]
    m = build(root, paths)
    if not m["files"] and not a.compare:
        sys.exit(f"refine_map: no code files under {', '.join(paths) or root}")
    print(compare(before.get("score", before), m["score"]) if a.compare else render(m))
    if a.json:
        Path(a.json).write_text(json.dumps({"paths": paths, "score": m["score"]}, indent=2))


if __name__ == "__main__":
    main()
