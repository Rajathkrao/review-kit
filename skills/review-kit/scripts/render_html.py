#!/usr/bin/env python3
"""Render the review-kit HTML explainer from a review package.

Reads PKG/explainer.json (optional), PKG/findings.json, PKG/meta.json,
PKG/contract.md and PKG/test-results.md; writes PKG/review.html and a copy under
~/.review-kit/reports/. Self-contained: no network, no external assets.
"""
import datetime as _dt
import html
import json
import re
import shutil
import sys
from pathlib import Path


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def read(p):
    try:
        return Path(p).read_text()
    except Exception:
        return ""


e = lambda s: html.escape(str(s if s is not None else ""))

SEV_ORDER = {"critical": 0, "important": 1, "minor": 2}
SEV_LABEL = {"critical": "Critical", "important": "Important", "minor": "Minor"}
VERDICT = {"dont-ship": ("Don't ship yet", "crit"), "ship-after-fixes": ("Ship after fixes", "imp"),
           "ship": ("Ship", "ok")}
KIND_LABEL = {"request": "Request", "data": "Data", "logic": "Logic", "ui": "UI", "job": "Job",
              "config": "Config", "test": "Test", "external": "External call"}


def inline_md(s):
    s = e(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def para(s):
    return "".join(f"<p>{inline_md(p)}</p>" for p in str(s or "").split("\n\n") if p.strip())


def render(pkg: Path):
    meta = load_json(pkg / "meta.json", {})
    fx = load_json(pkg / "findings.json", {"findings": []})
    ex = load_json(pkg / "explainer.json", {})
    contract = read(pkg / "contract.md")
    tests = read(pkg / "test-results.md")

    findings = sorted(fx.get("findings", []), key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), -int(f.get("confidence", 0))))
    for i, f in enumerate(findings, 1):
        f.setdefault("id", f"F{i}")
    by_id = {f["id"]: f for f in findings}
    verdict_txt, verdict_cls = VERDICT.get(fx.get("verdict", ""), ("Review", "ok"))
    title = ex.get("title") or meta.get("description", "Code review")
    counts = {k: sum(1 for f in findings if f.get("severity") == k) for k in SEV_ORDER}

    # Steps: attach any finding not referenced by a step to an "Elsewhere" step.
    steps = list(ex.get("steps", []))
    referenced = {fid for s in steps for fid in s.get("finding_ids", [])}
    orphans = [f["id"] for f in findings if f["id"] not in referenced]
    if steps and orphans:
        steps.append({"title": "Elsewhere in the change", "where": "", "kind": "logic",
                      "what_happens": "Findings that don't sit on the main flow above.", "finding_ids": orphans})

    def badge(fid):
        f = by_id.get(fid)
        if not f:
            return ""
        return f'<a class="badge sev-{e(f.get("severity"))}" href="#{e(fid)}">{e(fid)} · {e(SEV_LABEL.get(f.get("severity"), ""))}</a>'

    flow = []
    for n, s in enumerate(steps, 1):
        badges = "".join(badge(fid) for fid in s.get("finding_ids", []))
        worst = min((SEV_ORDER.get(by_id[f]["severity"], 3) for f in s.get("finding_ids", []) if f in by_id), default=9)
        cls = {0: "has-crit", 1: "has-imp", 2: "has-min"}.get(worst, "")
        flow.append(f'''
      <li class="node {cls}">
        <a class="node-link" href="#step-{n}">
          <span class="num">{n}</span>
          <span class="node-body">
            <span class="kind">{e(KIND_LABEL.get(s.get("kind"), s.get("kind", "")))}</span>
            <span class="node-title">{e(s.get("title"))}</span>
          </span>
        </a>
        <span class="badges">{badges}</span>
      </li>''')

    step_html = []
    for n, s in enumerate(steps, 1):
        snippet = f'<pre class="code"><code>{e(s.get("snippet"))}</code></pre>' if s.get("snippet") else ""
        where = f'<div class="where"><code>{e(s.get("where"))}</code></div>' if s.get("where") else ""
        fl = "".join(badge(fid) for fid in s.get("finding_ids", []))
        step_html.append(f'''
    <section class="step" id="step-{n}">
      <div class="step-head"><span class="num">{n}</span><h3>{e(s.get("title"))}</h3>
        <span class="kind">{e(KIND_LABEL.get(s.get("kind"), s.get("kind", "")))}</span></div>
      {where}
      {para(s.get("what_happens"))}
      {snippet}
      {f'<div class="badges">Problems here: {fl}</div>' if fl else ''}
    </section>''')

    finding_html = []
    for f in findings:
        loc = f'{f.get("file")}:{f.get("line_start")}' + (f'-{f.get("line_end")}' if f.get("line_end") and f.get("line_end") != f.get("line_start") else "")
        meta_line = " · ".join(x for x in [
            f"confidence {f.get('confidence')}",
            ", ".join(f.get("lenses", [])) if f.get("lenses") else "",
            f"found by {f.get('found_by')}" if f.get("found_by") else "",
            f"verified by {f.get('verified_by')}" if f.get("verified_by") else "",
            f"contract {f.get('contract_ref')}" if f.get("contract_ref") else ""] if x)
        finding_html.append(f'''
    <article class="finding sev-{e(f.get("severity"))}" id="{e(f["id"])}">
      <header><span class="pill sev-{e(f.get("severity"))}">{e(SEV_LABEL.get(f.get("severity"), f.get("severity")))}</span>
        <h3>{e(f["id"])}. {e(f.get("title"))}</h3></header>
      <div class="where"><code>{e(loc)}</code></div>
      <h4>What goes wrong</h4>{para(f.get("body"))}
      <h4>Fix</h4>{para(f.get("recommendation"))}
      {f'<h4>Evidence</h4>{para(f.get("evidence"))}' if f.get("evidence") else ''}
      <div class="meta">{e(meta_line)}</div>
    </article>''')

    spec_rows = "".join(
        f'<tr><td>{e(s.get("id"))}</td><td class="st st-{e(s.get("status"))}">{e(s.get("status","").replace("_"," "))}</td><td>{inline_md(s.get("evidence",""))}</td></tr>'
        for s in fx.get("spec_status", []))
    dropped = "".join(f'<li><strong>{e(d.get("title"))}</strong> <span class="muted">(score {e(d.get("confidence"))})</span>: {inline_md(d.get("reason",""))}</li>'
                      for d in fx.get("dropped", []))
    concepts = "".join(f'<dt>{e(c.get("term"))}</dt><dd>{inline_md(c.get("meaning"))}</dd>' for c in ex.get("key_concepts", []))
    tryit = "".join(f'<li><label><input type="checkbox"> {inline_md(t)}</label></li>' for t in ex.get("try_it_yourself", []))
    files_rows = "".join(
        f'<tr><td><code>{e(c.get("path"))}</code></td><td>{e(c.get("change",""))}</td><td>{inline_md(c.get("role",""))}</td></tr>'
        for c in ex.get("changed_files", [])) or "".join(
        f'<tr><td><code>{e(f.get("path"))}</code></td><td>{e(f.get("status"))}</td><td>+{f.get("added")}/−{f.get("deleted")}</td></tr>'
        for f in meta.get("files", []))
    not_checked = "".join(f"<li>{inline_md(x)}</li>" for x in fx.get("not_checked", []) + fx.get("declined", []))

    overview = ""
    if ex:
        overview = f'''
  <section class="cards">
    <div class="card"><h4>Why this change</h4>{para(ex.get("why"))}</div>
    <div class="card"><h4>Before</h4>{para(ex.get("before"))}</div>
    <div class="card"><h4>After</h4>{para(ex.get("after"))}</div>
  </section>'''
    flow_section = ""
    if steps:
        flow_section = f'''
  <section>
    <h2>Step by step</h2>
    <p class="muted">Starts at <code>{e(ex.get("entry_point",""))}</code> and follows the code in the order it runs. Click a step for details.</p>
    <ol class="flow">{"".join(flow)}</ol>
    {"".join(step_html)}
  </section>'''
    else:
        flow_section = '<section><p class="muted">No walkthrough was written for this review (explainer.json missing).</p></section>'

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · review</title>
<style>
:root {{
  --bg:#fbfaf7; --surface:#ffffff; --ink:#1d1c1a; --muted:#6b6862; --line:#e4e0d8;
  --accent:#2f5d8a; --code-bg:#f3f1ec;
  --crit:#b3261e; --crit-bg:#fbe9e7; --imp:#9a5b00; --imp-bg:#fdf1dc; --min:#46607a; --min-bg:#e9eff5;
  --ok:#2e6b3f; --ok-bg:#e5f2e8;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#141413; --surface:#1d1c1a; --ink:#ece9e2; --muted:#a29e96; --line:#33312d;
  --accent:#8db4dc; --code-bg:#262521;
  --crit:#f2b8b5; --crit-bg:#3a1e1c; --imp:#f0c674; --imp-bg:#35290f; --min:#a9c1d9; --min-bg:#1f2a35;
  --ok:#9fd3ad; --ok-bg:#1b2e21; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif }}
main {{ max-width:880px; margin:0 auto; padding:32px 16px 80px }}
h1 {{ font-size:1.7rem; line-height:1.25; margin:.2em 0 .3em }}
h2 {{ font-size:1.25rem; margin:2.2em 0 .6em; padding-bottom:.3em; border-bottom:1px solid var(--line) }}
h3 {{ font-size:1.05rem; margin:0 }}
h4 {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:1em 0 .2em }}
p {{ margin:.35em 0 }}
code {{ font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; background:var(--code-bg); padding:1px 5px; border-radius:4px }}
pre.code {{ background:var(--code-bg); border:1px solid var(--line); border-radius:8px; padding:12px; overflow-x:auto }}
pre.code code {{ background:none; padding:0 }}
.muted {{ color:var(--muted) }}
.verdict {{ display:inline-block; font-weight:600; padding:4px 12px; border-radius:999px; font-size:.95rem }}
.verdict.crit {{ background:var(--crit-bg); color:var(--crit) }} .verdict.imp {{ background:var(--imp-bg); color:var(--imp) }} .verdict.ok {{ background:var(--ok-bg); color:var(--ok) }}
.summary {{ font-size:1.05rem; margin:.6em 0 }}
.stats {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px }}
.stat {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:6px 12px; font-size:.9rem }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-top:24px }}
.card {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:12px 14px }}
.card h4 {{ margin-top:0 }}
ol.flow {{ list-style:none; padding:0; margin:16px 0 28px; position:relative }}
ol.flow::before {{ content:""; position:absolute; left:19px; top:20px; bottom:20px; width:2px; background:var(--line) }}
.node {{ position:relative; display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:0 0 10px }}
.node-link {{ display:flex; align-items:center; gap:12px; text-decoration:none; color:inherit; flex:1 1 320px; background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:8px 12px 8px 0 }}
.node-link:hover {{ border-color:var(--accent) }}
.node.has-crit .node-link {{ border-left:4px solid var(--crit) }} .node.has-imp .node-link {{ border-left:4px solid var(--imp) }} .node.has-min .node-link {{ border-left:4px solid var(--min) }}
.num {{ flex:none; width:40px; height:40px; display:grid; place-items:center; border-radius:50%; background:var(--bg); border:2px solid var(--accent); color:var(--accent); font-weight:700; position:relative; z-index:1; margin-left:-1px }}
.node-body {{ display:flex; flex-direction:column }}
.node-title {{ font-weight:600 }}
.kind {{ font-size:.72rem; text-transform:uppercase; letter-spacing:.07em; color:var(--muted) }}
.badges {{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; font-size:.85rem }}
.node > .badges {{ flex:0 0 240px }}
@media (max-width:640px) {{ .node > .badges {{ flex:1 1 100%; padding-left:52px }} }}
.badge {{ font-size:.78rem; text-decoration:none; padding:2px 8px; border-radius:999px; font-weight:600 }}
.badge.sev-critical,.pill.sev-critical {{ background:var(--crit-bg); color:var(--crit) }}
.badge.sev-important,.pill.sev-important {{ background:var(--imp-bg); color:var(--imp) }}
.badge.sev-minor,.pill.sev-minor {{ background:var(--min-bg); color:var(--min) }}
.step {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin:12px 0; scroll-margin-top:16px }}
.step-head {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap }}
.step-head .num {{ width:30px; height:30px; font-size:.9rem }}
.where {{ margin:6px 0 }}
.finding {{ background:var(--surface); border:1px solid var(--line); border-left:5px solid var(--min); border-radius:10px; padding:14px 16px; margin:12px 0; scroll-margin-top:16px }}
.finding.sev-critical {{ border-left-color:var(--crit) }} .finding.sev-important {{ border-left-color:var(--imp) }}
.finding header {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap }}
.pill {{ font-size:.75rem; font-weight:700; padding:2px 9px; border-radius:999px }}
.meta {{ margin-top:10px; font-size:.82rem; color:var(--muted) }}
table {{ width:100%; border-collapse:collapse; font-size:.92rem; background:var(--surface) }}
th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
.st {{ font-weight:600; white-space:nowrap }} .st-met {{ color:var(--ok) }} .st-missing,.st-misunderstood {{ color:var(--crit) }} .st-cannot_verify {{ color:var(--imp) }}
dl dt {{ font-weight:600; margin-top:8px }} dl dd {{ margin:2px 0 0 0 }}
ul.try {{ list-style:none; padding:0 }} ul.try li {{ margin:6px 0 }}
details {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:10px 0 }}
summary {{ cursor:pointer; font-weight:600 }}
pre.tests {{ white-space:pre-wrap; background:var(--code-bg); border-radius:8px; padding:12px; font-size:13px; overflow-x:auto }}
.table-wrap {{ overflow-x:auto }}
footer {{ margin-top:48px; font-size:.82rem; color:var(--muted) }}
</style></head>
<body><main>
  <div class="muted">{e(meta.get("repo",""))} · {e(meta.get("description",""))}</div>
  <h1>{e(title)}</h1>
  {f'<p class="summary">{inline_md(ex.get("one_liner"))}</p>' if ex.get("one_liner") else ''}
  <span class="verdict {verdict_cls}">{e(verdict_txt)}</span>
  <p class="summary">{inline_md(fx.get("summary",""))}</p>
  <div class="stats">
    <span class="stat">{len(meta.get("files", []))} files · +{meta.get("added",0)}/−{meta.get("deleted",0)}</span>
    <span class="stat">{counts["critical"]} critical</span><span class="stat">{counts["important"]} important</span><span class="stat">{counts["minor"]} minor</span>
    <span class="stat">{len(fx.get("dropped", []))} dropped after verification</span>
  </div>
  {overview}
  {flow_section}
  <section><h2>Findings</h2>
    {"".join(finding_html) or '<p>No issues found.</p>'}
  </section>
  {f'<section><h2>Checked against the purpose</h2><div class="table-wrap"><table><tr><th>Req</th><th>Status</th><th>Evidence</th></tr>{spec_rows}</table></div><details><summary>Contract used</summary><pre class="tests">{e(contract)}</pre></details></section>' if spec_rows or contract else ''}
  {f'<section><h2>Test evidence</h2><pre class="tests">{e(tests)}</pre></section>' if tests else '<section><h2>Test evidence</h2><p class="muted">No tests were run for this review.</p></section>'}
  {f'<section><h2>Key concepts</h2><dl>{concepts}</dl></section>' if concepts else ''}
  {f'<section><h2>Try it yourself</h2><ul class="try">{tryit}</ul></section>' if tryit else ''}
  <section><h2>Changed files</h2><div class="table-wrap"><table>{files_rows}</table></div></section>
  {f'<section><h2>What was not reported</h2><details><summary>{len(fx.get("dropped", []))} candidates dropped after verification</summary><ul>{dropped}</ul></details>' + (f'<details><summary>Not checked / declined</summary><ul>{not_checked}</ul></details>' if not_checked else '') + '</section>' if dropped or not_checked else ''}
  <footer>Generated by review-kit on {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")}. Package: <code>{e(pkg)}</code></footer>
</main></body></html>'''
    out = pkg / "review.html"
    out.write_text(page)
    reports = Path.home() / ".review-kit" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    mode = ex.get("mode") or fx.get("mode") or "review"
    copy = reports / f"{meta.get('repo','repo')}-{_dt.datetime.now().strftime('%Y%m%d-%H%M')}-{mode}.html"
    shutil.copy(out, copy)
    print(copy)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: render_html.py PKG")
    render(Path(sys.argv[1]))
