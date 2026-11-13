"""Self-contained SVG diagrams for the walkthrough page: no network, no JS, themed by CSS vars.

- architecture(spec): boxes and arrows, layered top-down (longest path), changed parts highlighted
- sequence(spec): actors, lifelines and ordered messages, with finding markers
- import_graph(root, files): the Python modules a change touches, what they import and who imports them
"""
import ast
import html
import os
from pathlib import Path

NODE_W, NODE_H, GAP_X, GAP_Y, PAD = 188, 58, 56, 72, 16
SEV_VAR = {"critical": "var(--crit)", "important": "var(--imp)", "minor": "var(--min)"}


def e(s):
    return html.escape("" if s is None else str(s), quote=True)


def _clip(text, n):
    text = str(text)
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _wrap(text, width):
    words, lines, cur = [], [], ""
    for w in str(text or "").split():
        while len(w) > width:  # break long dotted or snake_case names at a separator
            cut = max(w.rfind(".", 0, width), w.rfind("_", 0, width), w.rfind("/", 0, width))
            cut = cut + 1 if cut > 0 else width
            words.append(w[:cut])
            w = w[cut:]
        words.append(w)
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1][:max(0, width - 1)].rstrip() + "…"
    return lines or [""]


def _layers(ids, edges, fixed=None):
    """Layer = distance from the entry nodes (the first node and nodes nothing points to).
    Edges that point to the same or an earlier layer are drawn around the side."""
    fixed = fixed or {}
    incoming = {b for a, b in edges}
    roots = [n for n in ids if n == ids[0] or n not in incoming]
    layer, frontier = {n: 0 for n in roots}, list(roots)
    while frontier:
        nxt = []
        for a in frontier:
            for x, b in edges:
                if x == a and b not in layer:
                    layer[b] = layer[a] + 1
                    nxt.append(b)
        frontier = nxt
    for n in ids:
        layer.setdefault(n, 0)
    if fixed:
        layer.update({n: int(v) for n, v in fixed.items() if n in layer})
    back = {(a, b) for a, b in edges if layer[b] <= layer[a]}
    return layer, back


def _layers_longest(ids, edges, entry=None):
    """Longest-path layering. Cycle edges, and edges back into the entry node, are drawn as
    back edges, so the entry stays on top and everything it reaches sits below what calls it."""
    succ = {i: [] for i in ids}
    back = set()
    for a, b in edges:
        if a in succ and b in succ and a != b:
            if b == entry:
                back.add((a, b))
            else:
                succ[a].append(b)
    incoming = {b for a, b in edges if (a, b) not in back}
    state, order = {}, []

    def dfs(n):
        state[n] = 1
        for m in succ[n]:
            if state.get(m) == 1:
                back.add((n, m))
            elif m not in state:
                dfs(m)
        state[n] = 2
        order.append(n)

    roots = ([entry] if entry else []) + [n for n in ids if n not in incoming] + ids
    for n in roots:
        if n not in state:
            dfs(n)
    layer = {n: 0 for n in ids}
    for n in reversed(order):
        for m in succ[n]:
            if (n, m) not in back:
                layer[m] = max(layer[m], layer[n] + 1)
    return layer, back


def _order(ids, edges, layer):
    rows = {}
    for n in ids:
        rows.setdefault(layer[n], []).append(n)
    pos = {}
    for k in sorted(rows):
        if k > 0:
            def bary(n, k=k):
                ps = [pos[a] for a, b in edges if b == n and a in pos and layer[a] < k]
                return sum(ps) / len(ps) if ps else 1e9
            rows[k].sort(key=bary)
        for i, n in enumerate(rows[k]):
            pos[n] = i
    return rows


def architecture(spec, findings_by_id=None):
    """spec: {"nodes": [{"id","label","kind","file","changed","finding_ids","note"}], "edges": [{"from","to","label"}]}"""
    findings_by_id = findings_by_id or {}
    nodes = [n for n in (spec or {}).get("nodes", []) if isinstance(n, dict) and n.get("id")]
    if not nodes:
        return ""
    ids = [str(n["id"]) for n in nodes]
    byid = {str(n["id"]): n for n in nodes}
    edges = [(str(x.get("from")), str(x.get("to")), x.get("label", ""))
             for x in (spec or {}).get("edges", []) if isinstance(x, dict)
             and str(x.get("from")) in byid and str(x.get("to")) in byid]
    fixed = {str(n["id"]): n["layer"] for n in nodes if isinstance(n.get("layer"), int)}
    pairs = [(a, b) for a, b, _ in edges]
    if spec.get("layering") == "entry":
        layer, back = _layers(ids, pairs, fixed)
    else:
        layer, back = _layers_longest(ids, pairs, None if spec.get("layering") == "longest" else ids[0])
        layer.update({n: int(v) for n, v in fixed.items() if n in layer})
    # Compact empty layers created by fixed values.
    used = sorted(set(layer.values()))
    layer = {n: used.index(v) for n, v in layer.items()}
    rows = _order(ids, [(a, b) for a, b, _ in edges], layer)
    widest = max(len(r) for r in rows.values())
    width = PAD * 2 + widest * NODE_W + (widest - 1) * GAP_X
    height = PAD * 2 + len(rows) * NODE_H + (len(rows) - 1) * GAP_Y + 8
    xy = {}
    for k, row in rows.items():
        row_w = len(row) * NODE_W + (len(row) - 1) * GAP_X
        x0 = (width - row_w) / 2
        for i, n in enumerate(row):
            xy[n] = (x0 + i * (NODE_W + GAP_X), PAD + k * (NODE_H + GAP_Y))
    width += 40  # room for edges routed around the right side
    out = [f'<svg class="dg" style="max-width:{width * 1.15:.0f}px;min-width:{min(width, 760) * 0.78:.0f}px" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{e(spec.get("title") or "Architecture of the change")}">',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" class="dg-head"/></marker></defs>']
    out_count, indeg, placed = {}, {}, []
    for _, b, _ in edges:
        indeg[b] = indeg.get(b, 0) + 1
    row_of = {n: rows[layer[n]].index(n) for n in ids}
    for a, b, label in edges:
        (ax, ay), (bx, by) = xy[a], xy[b]
        k = out_count[a] = out_count.get(a, -1) + 1
        tip = None
        if layer[b] == layer[a] and a != b and abs(row_of[a] - row_of[b]) > 1:
            # Same row, not neighbours: arc below the row instead of through the boxes between.
            sx, sy, tx, ty = ax + NODE_W / 2, ay + NODE_H, bx + NODE_W / 2, by + NODE_H + 2
            dip = sy + GAP_Y * 0.55
            d = f"M{sx:.0f},{sy:.0f} C{sx:.0f},{dip:.0f} {tx:.0f},{dip:.0f} {tx:.0f},{ty:.0f}"
            lx, ly = (sx + tx) / 2, dip - 8
        elif layer[b] == layer[a] and a != b:
            # Same row: a straight line between the facing sides.
            left = ax < bx
            sx, tx = (ax + NODE_W, bx - 3) if left else (ax, bx + NODE_W + 3)
            sy = ty = ay + NODE_H / 2
            d = f"M{sx:.0f},{sy:.0f} L{tx:.0f},{ty:.0f}"
            lx, ly = (sx + tx) / 2, sy - 12
            if label and abs(tx - sx) < 7 * len(str(label)[:34]) + 10:
                label = ""  # no room between the boxes; the arrow alone says enough
        elif (a, b) in back or layer[b] < layer[a]:
            # Upward or same-row edge: route around the right side of the boxes.
            sx, sy, tx, ty = ax + NODE_W, ay + NODE_H / 2, bx + NODE_W, by + NODE_H / 2
            bend = max(sx, tx) + 30
            d = f"M{sx:.0f},{sy:.0f} C{bend:.0f},{sy:.0f} {bend:.0f},{ty:.0f} {tx + 2:.0f},{ty:.0f}"
            lx, ly = bend - 4, (sy + ty) / 2
        elif layer[b] - layer[a] > 1:
            # Skips a row: run down through a free column so it never passes behind a box.
            sx, sy, tx, ty = ax + NODE_W / 2, ay + NODE_H, bx + NODE_W / 2, by - 2
            between = [xy[n][0] for n in ids if layer[a] < layer[n] < layer[b]]
            free = lambda x, between=between: all(not (bx0 - 10 < x < bx0 + NODE_W + 10) for bx0 in between)
            cands = sorted({8.0, width - 8.0, *(x0 - GAP_X / 2 for x0 in between),
                            *(x0 + NODE_W + GAP_X / 2 for x0 in between)}, key=lambda x: abs(x - (sx + tx) / 2))
            cx = next((x for x in cands if free(x)), (sx + tx) / 2)
            y1, y2 = sy + GAP_Y / 2, ty - GAP_Y / 2
            d = (f"M{sx:.0f},{sy:.0f} C{sx:.0f},{y1:.0f} {cx:.0f},{sy:.0f} {cx:.0f},{y1:.0f} "
                 f"L{cx:.0f},{y2:.0f} C{cx:.0f},{ty:.0f} {tx:.0f},{y2:.0f} {tx:.0f},{ty:.0f}")
            lx, ly = cx, (y1 + y2) / 2
            half = (7 * len(str(label)[:34]) + 10) / 2
            if label and not (free(cx - half) and free(cx + half)):
                tip, label = label, ""  # no room in the column: keep it as a hover title
        else:
            sx, sy, tx, ty = ax + NODE_W / 2, ay + NODE_H, bx + NODE_W / 2, by - 2
            my = (sy + ty) / 2
            d = f"M{sx:.0f},{sy:.0f} C{sx:.0f},{my:.0f} {tx:.0f},{my:.0f} {tx:.0f},{ty:.0f}"
            # Place the label at the first point along the curve where it overlaps no other label.
            lw = 7 * len(str(label)[:34]) + 10
            for t in (0.6, 0.42, 0.76, 0.3, 0.86, 0.5):
                lx = (1 - t) ** 3 * sx + 3 * (1 - t) ** 2 * t * sx + 3 * (1 - t) * t ** 2 * tx + t ** 3 * tx
                ly = (1 - t) ** 3 * sy + 3 * (1 - t) ** 2 * t * my + 3 * (1 - t) * t ** 2 * my + t ** 3 * ty
                if not any(abs(lx - px) < (lw + pw) / 2 and abs(ly - py) < 19 for px, py, pw in placed):
                    break
            else:
                tip, label = label, ""  # every spot collides: keep it as a hover title
        tip = tip or label
        out.append(f'<path d="{d}" class="dg-edge" marker-end="url(#ah)"><title>{e(byid[a].get("label") or a)} → {e(byid[b].get("label") or b)}{(": " + e(tip)) if tip else ""}</title></path>')
        if label:
            placed.append((lx, ly, 7 * len(str(label)[:34]) + 10))
            text = e(_clip(label, 34))
            if len(str(label)) > 34:
                tip = label
            w = 7 * len(str(label)[:34]) + 10
            out.append(f'<rect x="{lx - w / 2:.0f}" y="{ly - 10:.0f}" width="{w}" height="18" rx="4" class="dg-label-bg"/>'
                       f'<text x="{lx:.0f}" y="{ly + 3:.0f}" class="dg-label" text-anchor="middle">{text}</text>')
    for n in ids:
        node, (x, y) = byid[n], xy[n]
        kind = node.get("kind") or "logic"
        fids = [f for f in node.get("finding_ids", []) if f in findings_by_id]
        cls = ["dg-node", f"dg-{e(kind)}"] + (["dg-changed"] if node.get("changed") else [])
        sev = min((findings_by_id[f].get("severity", "minor") for f in fids),
                  key=lambda s: ["critical", "important", "minor"].index(s) if s in SEV_VAR else 3, default=None)
        stroke = f' style="stroke:{SEV_VAR[sev]}"' if sev in SEV_VAR else ""
        title = e(node.get("note") or node.get("file") or node.get("label"))
        out.append(f'<g><title>{title}</title><rect x="{x:.0f}" y="{y:.0f}" width="{NODE_W}" height="{NODE_H}" rx="8" class="{" ".join(cls)}"{stroke}/>')
        lines = _wrap(node.get("label") or n, 24)
        sub = node.get("file") or {"external": "external", "data": "data", "job": "job"}.get(kind, "")
        ty = y + (NODE_H / 2 - (len(lines) - 1) * 8 - (6 if sub else 0)) + 5
        for i, ln in enumerate(lines):
            out.append(f'<text x="{x + NODE_W / 2:.0f}" y="{ty + i * 16:.0f}" class="dg-text" text-anchor="middle">{e(ln)}</text>')
        if sub:
            out.append(f'<text x="{x + NODE_W / 2:.0f}" y="{ty + len(lines) * 16 - 2:.0f}" class="dg-sub" text-anchor="middle">{e(Path(str(sub)).name if "/" in str(sub) else sub)}</text>')
        if fids:
            bx = x + NODE_W - 8
            for f in reversed(fids[:3]):
                w = 8 * len(f) + 8
                bx -= w
                fsev = findings_by_id[f].get("severity", "minor")
                out.append(f'<a href="#{e(f)}"><rect x="{bx:.0f}" y="{y - 9:.0f}" width="{w}" height="18" rx="9" style="fill:{SEV_VAR.get(fsev, "var(--min)")}"/>'
                           f'<text x="{bx + w / 2:.0f}" y="{y + 4:.0f}" class="dg-badge" text-anchor="middle">{e(f)}</text></a>')
                bx -= 4
        out.append('</g>')
    out.append('</svg>')
    return "".join(out)


def sequence(spec, findings_by_id=None):
    """spec: {"title", "actors": [...], "messages": [{"from","to","label","finding_id","kind":"call|return|async|note"}]}"""
    findings_by_id = findings_by_id or {}
    actors = [str(a) for a in (spec or {}).get("actors", []) if a]
    msgs = [m for m in (spec or {}).get("messages", []) if isinstance(m, dict)]
    for m in msgs:
        for k in ("from", "to"):
            if m.get(k) and str(m[k]) not in actors:
                actors.append(str(m[k]))
    if not actors or not msgs:
        return ""
    col, top, row = 168, 54, 44
    width = PAD * 2 + col * len(actors)
    height = top + row * len(msgs) + 34
    cx = {a: PAD + col * i + col / 2 for i, a in enumerate(actors)}
    out = [f'<svg class="dg dg-seq" style="max-width:{width * 1.15:.0f}px;min-width:{min(width, 760) * 0.78:.0f}px" viewBox="0 0 {width} {height}" role="img" aria-label="{e(spec.get("title") or "Sequence")}">',
           '<defs><marker id="sh" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" class="dg-head"/></marker></defs>']
    for a in actors:
        x = cx[a]
        out.append(f'<line x1="{x:.0f}" y1="{top - 6}" x2="{x:.0f}" y2="{height - 8}" class="dg-life"/>')
        lines = _wrap(a, 20)
        out.append(f'<rect x="{x - col / 2 + 8:.0f}" y="6" width="{col - 16}" height="{top - 14}" rx="7" class="dg-node dg-actor"/>')
        for i, ln in enumerate(lines):
            out.append(f'<text x="{x:.0f}" y="{(top - 8) / 2 + 6 + (i - (len(lines) - 1) / 2) * 15:.0f}" class="dg-text" text-anchor="middle">{e(ln)}</text>')
    for i, m in enumerate(msgs):
        y = top + row * i + row / 2 + 6
        a, b = str(m.get("from") or actors[0]), str(m.get("to") or m.get("from") or actors[0])
        fid = m.get("finding_id")
        sev = findings_by_id.get(fid, {}).get("severity") if fid else None
        style = f' style="stroke:{SEV_VAR[sev]}"' if sev in SEV_VAR else ""
        kind = m.get("kind") or "call"
        dash = " dg-dash" if kind in ("return", "async") else ""
        raw = str(m.get("label") or "")
        span = abs(cx[b] - cx[a]) if a != b and kind != "note" else col * 2.4
        fit = max(18, int(span / 6.6))
        lines2 = [_clip(raw, fit)] if kind == "note" or a == b else _wrap(raw, fit)
        label = e(lines2[-1])
        label_top = e(lines2[0]) if len(lines2) > 1 else ""
        out.append(f'<g><title>{e(raw)}</title>')
        if kind == "note" or a == b:
            x = cx[a]
            if kind == "note":
                w = min(col * 2.4, 7 * len(lines2[0]) + 16)
                x = min(max(x, w / 2 + 2), width - w / 2 - 2)
                out.append(f'<rect x="{x - w / 2:.0f}" y="{y - 14:.0f}" width="{w:.0f}" height="22" rx="4" class="dg-note"{style}/>'
                           f'<text x="{x:.0f}" y="{y + 1:.0f}" class="dg-label" text-anchor="middle">{label}</text>')
            else:
                out.append(f'<path d="M{x:.0f},{y - 8:.0f} h34 v16 h-32" class="dg-edge{dash}"{style} marker-end="url(#sh)"/>'
                           f'<text x="{x + 40:.0f}" y="{y + 4:.0f}" class="dg-label">{label}</text>')
        else:
            x1, x2 = cx[a], cx[b]
            out.append(f'<line x1="{x1:.0f}" y1="{y:.0f}" x2="{x2 + (-3 if x2 > x1 else 3):.0f}" y2="{y:.0f}" class="dg-edge{dash}"{style} marker-end="url(#sh)"/>'
                       f'<text x="{(x1 + x2) / 2:.0f}" y="{y - 6:.0f}" class="dg-label" text-anchor="middle">{label}</text>')
            if label_top:
                out.append(f'<text x="{(x1 + x2) / 2:.0f}" y="{y - 19:.0f}" class="dg-label" text-anchor="middle">{label_top}</text>')
        out.append('</g>')
        n = f"{i + 1}"
        out.append(f'<text x="{PAD - 4}" y="{y + 4:.0f}" class="dg-sub">{n}</text>')
        if fid and fid in findings_by_id:
            bx = (cx[a] + cx[b]) / 2 if a != b else cx[a] + 60
            w = 8 * len(fid) + 8
            out.append(f'<a href="#{e(fid)}"><rect x="{bx - w / 2:.0f}" y="{y + 3:.0f}" width="{w}" height="16" rx="8" style="fill:{SEV_VAR.get(sev, "var(--min)")}"/>'
                       f'<text x="{bx:.0f}" y="{y + 15:.0f}" class="dg-badge" text-anchor="middle">{e(fid)}</text></a>')
    out.append('</svg>')
    return "".join(out)


def _module_name(root, path):
    rel = Path(path).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    # Drop a leading src/ layout folder.
    if parts and parts[0] == "src" and (Path(root) / "src").is_dir():
        parts = parts[1:]
    return ".".join(parts)


def _imports(tree, module):
    found = set()
    pkg = module.rsplit(".", 1)[0] if "." in module else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                base = base[:len(base) - node.level] if len(base) >= node.level else []
                if not module.endswith("__init__") and node.level and pkg == "":
                    base = []
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            if mod:
                found.add(mod)
                found.update(f"{mod}.{a.name}" for a in node.names)
    return found


def import_graph(root, changed_files, max_files=3000):
    """Nodes: changed Python modules, plus in-repo modules they import and modules that import them."""
    root = Path(root)
    changed = [p for p in changed_files if p.endswith(".py")]
    if not changed:
        return {}
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in
                       ("node_modules", "venv", ".venv", "env", "build", "dist", "__pycache__", "site-packages")]
        files += [os.path.relpath(os.path.join(dirpath, f), root) for f in filenames if f.endswith(".py")]
        if len(files) > max_files:
            return {}
    mods = {_module_name(root, f): f for f in files}
    graph = {}
    for f in files:
        try:
            tree = ast.parse((root / f).read_text(errors="ignore"))
        except (SyntaxError, ValueError, OSError):
            continue
        m = _module_name(root, f)
        # A relative import inside a package resolves against the module's own package.
        targets = set()
        for imp in _imports(tree, m if not f.endswith("__init__.py") else m + ".__init__"):
            while imp and imp not in mods:
                imp = imp.rsplit(".", 1)[0] if "." in imp else ""
            if imp and imp != m:
                targets.add(imp)
        graph[m] = targets
    changed_mods = {_module_name(root, p) for p in changed if _module_name(root, p) in mods}
    keep = set(changed_mods)
    for m in changed_mods:
        keep.update(graph.get(m, ()))
        keep.update(k for k, v in graph.items() if m in v)
    if len(keep) > 24:  # too big to draw usefully: keep changed modules and their direct imports
        keep = set(changed_mods) | {t for m in changed_mods for t in graph.get(m, ())}
    nodes = [{"id": m, "label": m.rsplit(".", 1)[-1] if m.count(".") else m, "file": mods[m],
              "kind": "test" if "test" in mods[m].lower() else "logic", "changed": m in changed_mods}
             for m in sorted(keep)]
    edges = [{"from": a, "to": b} for a in sorted(keep) for b in sorted(graph.get(a, ())) if b in keep]
    return {"title": "Python modules touched by this change", "layering": "longest", "nodes": nodes, "edges": edges}


CSS = """
.dg-wrap{margin:16px 0 8px;background:var(--sheet);border:1px solid var(--rule);border-radius:8px;padding:10px;overflow-x:auto}
.dg-wrap figcaption{font-size:13px;color:var(--soft);margin:6px 4px 0}
svg.dg{display:block;margin:0 auto;width:100%;height:auto;max-height:78vh;font-family:var(--sans)}
.dg-node{fill:var(--paper);stroke:var(--rule);stroke-width:1.5}
.dg-changed{fill:var(--accent-wash);stroke:var(--accent);stroke-width:2.2}
.dg-external{stroke-dasharray:5 4}
.dg-data{rx:14}
.dg-test{fill:var(--sheet)}
.dg-actor{fill:var(--accent-wash);stroke:var(--accent)}
.dg-text{fill:var(--ink);font-size:13px;font-weight:600}
.dg-sub{fill:var(--soft);font-size:11px;font-family:var(--mono)}
.dg-edge{fill:none;stroke:var(--soft);stroke-width:1.5}
.dg-dash{stroke-dasharray:5 4}
.dg-head{fill:var(--soft)}
.dg-life{stroke:var(--rule);stroke-width:1.5;stroke-dasharray:3 4}
.dg-label{fill:var(--ink);font-size:11.5px}
.dg-label-bg{fill:var(--sheet);opacity:.92}
.dg-note{fill:var(--imp-wash);stroke:var(--rule)}
.dg-badge{fill:#fff;font-size:11px;font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--soft);margin:8px 4px 0}
.legend span::before{content:"";display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-2px;border:1.5px solid var(--rule);background:var(--paper)}
.legend .lg-changed::before{background:var(--accent-wash);border-color:var(--accent)}
.legend .lg-crit::before{border-color:var(--crit)}
.legend .lg-ext::before{border-style:dashed}
"""
