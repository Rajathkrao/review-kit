#!/usr/bin/env python3
"""Render the review-kit HTML walkthrough from a review package.

Reads PKG/meta.json, PKG/findings.json (validated), PKG/explainer.json (optional),
PKG/contract.md, PKG/test-results.md and PKG/diff-numbered.txt. Code shown on the page is
read from the reviewed source (meta.repo_root), never retyped by the model; changed lines are
taken from the diff. Writes PKG/review.html. Self-contained: no network, no external assets.
"""
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_data import load_object, validate_review  # noqa: E402

SEV_ORDER = {"critical": 0, "important": 1, "minor": 2}
SEV_LABEL = {"critical": "Critical", "important": "Important", "minor": "Minor"}
VERDICT = {"dont-ship": "Don't ship yet", "ship-after-fixes": "Ship after fixes", "ship": "Ready to ship"}
KIND_LABEL = {"request": "Request", "data": "Data", "logic": "Logic", "ui": "UI", "job": "Background job",
              "config": "Config", "test": "Test", "external": "External call"}
STATUS_TEXT = {"source-verified": "confirmed by reading the code",
               "test-reproduced": "reproduced by a test",
               "unverified": "not yet confirmed"}


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def read(p):
    try:
        return Path(p).read_text()
    except (OSError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------- text formatting

def inline_md(s):
    s = e(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def prose(s):
    """Paragraphs, '- ' bullets and '1. ' numbered lists from plain text."""
    out = []
    for block in re.split(r"\n\s*\n", str(s or "").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        if all(re.match(r"\s*[-*] ", l) for l in lines):
            out.append("<ul>" + "".join(f"<li>{inline_md(re.sub(r'^\s*[-*] ', '', l))}</li>" for l in lines) + "</ul>")
        elif all(re.match(r"\s*\d+[.)] ", l) for l in lines):
            out.append("<ol>" + "".join(f"<li>{inline_md(re.sub(r'^\s*\d+[.)] ', '', l))}</li>" for l in lines) + "</ol>")
        else:
            out.append(f"<p>{inline_md(' '.join(l.strip() for l in lines))}</p>")
    return "".join(out)


# ---------------------------------------------------------------- syntax highlighting

KEYWORDS = set("""
abstract as async await base bool break case catch class const continue default delete do double else enum
export extends false finally float for foreach from function get if implements import in int interface is
let long new null of override package private protected public readonly record return sealed set static
string super switch this throw true try type typeof var void while with yield using namespace def elif
except lambda None True False pass raise self and or not await decimal Task void undefined
""".split())
TOKEN = re.compile(r"""
  (?P<comment>//[^\n]*|/\*.*?\*/|\#(?![\w{])[^\n]*)
 |(?P<string>`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\$"(?:\\.|[^"\\])*")
 |(?P<number>\b\d[\d_]*(?:\.\d+)?\b)
 |(?P<word>[A-Za-z_$][\w$]*)
""", re.X | re.S)


def highlight(line):
    out, pos = [], 0
    for m in TOKEN.finditer(line):
        out.append(e(line[pos:m.start()]))
        kind, text = m.lastgroup, m.group(0)
        if kind == "word":
            if text in KEYWORDS:
                out.append(f'<span class="tk">{e(text)}</span>')
            elif text[:1].isupper():
                out.append(f'<span class="tt">{e(text)}</span>')
            else:
                out.append(e(text))
        else:
            cls = {"comment": "tc", "string": "ts", "number": "tn"}[kind]
            out.append(f'<span class="{cls}">{e(text)}</span>')
        pos = m.end()
    out.append(e(line[pos:]))
    return "".join(out)


# ---------------------------------------------------------------- source access

class Source:
    def __init__(self, pkg, meta):
        self.root = Path(meta.get("repo_root") or ".")
        self.changed = {}  # path -> set of new-file line numbers added/modified
        self.diff_text = {}  # path -> {line: text} from the diff (fallback when source is gone)
        self.new_files = set()
        cur = None
        for raw in read(pkg / "diff-numbered.txt").splitlines():
            m = re.match(r"diff --git a/(.*?) b/(.*)$", raw)
            if m:
                cur = m.group(2)
                continue
            if cur and (raw.startswith("new file mode") or raw.startswith("--- /dev/null")):
                self.new_files.add(cur)
                continue
            m = re.match(r"\s*(\d+) ([+ ])(.*)$", raw)
            if cur and m:
                n = int(m.group(1))
                self.diff_text.setdefault(cur, {})[n] = m.group(3)
                if m.group(2) == "+":
                    self.changed.setdefault(cur, set()).add(n)

    def lines(self, path):
        text = read(self.root / path)
        if text:
            return text.split("\n")
        known = self.diff_text.get(path)
        if not known:
            return []
        out = [None] * max(known)
        for n, t in known.items():
            out[n - 1] = t
        return out


def parse_where(where):
    """'src/a.ts:12-17' -> ('src/a.ts', 12, 17)."""
    m = re.match(r"\s*([^:]+?)(?::(\d+)(?:-(\d+))?)?\s*(?:,|$)", str(where or ""))
    if not m:
        return None, None, None
    s = int(m.group(2)) if m.group(2) else None
    return m.group(1), s, int(m.group(3)) if m.group(3) else s


def code_block(src, path, start, end, pins=None, context=2, fallback=None, caption=True, window=None):
    """Real source lines with line numbers, changed-line marks and margin pins.

    pins: {line_number: [(kind, label, text, href)]} where kind is a severity or 'note'.
    """
    pins = pins or {}
    lines = src.lines(path) if path else []
    if not lines or not start:
        if not fallback:
            return ""
        rows = "".join(f'<div class="ln"><span class="no"></span><span class="mk"></span><code>{highlight(l)}</code></div>'
                       for l in str(fallback).split("\n"))
        return f'<figure class="code"><figcaption>{e(path or "")} <span class="soft">(excerpt)</span></figcaption><div class="src">{rows}</div></figure>'
    end = end or start
    lo = max(1, start - context)
    hi = min(len(lines), end + context)
    show = set(range(lo, hi + 1))
    if window and hi - lo > window:
        # Long span: show the flagged range (if short) and a few lines around each pin.
        show = set()
        if end - start <= 8:
            show |= set(range(max(1, start - 1), min(len(lines), end + 1) + 1))
        for pn in pins:
            show |= set(range(max(1, pn - context), min(len(lines), pn + context) + 1))
        if not show:
            show = set(range(lo, min(hi, lo + window) + 1))
    is_new = path in src.new_files
    changed = set() if is_new else src.changed.get(path, set())
    rows = []
    prev = None
    for n in sorted(show):
        if prev is not None and n != prev + 1:
            rows.append(f'<div class="ln gap"><span class="no">⋯</span><span class="mk"></span><code class="soft">{n - prev - 1} lines not shown</code></div>')
        prev = n
        text = lines[n - 1] if n - 1 < len(lines) else ""
        if text is None:
            rows.append('<div class="ln gap"><span class="no">…</span><span class="mk"></span><code></code></div>')
            continue
        cls = ["ln"]
        if n in changed:
            cls.append("add")
        here = pins.get(n, [])
        if here:
            worst = min(here, key=lambda p: SEV_ORDER.get(p[0], 9))[0]
            cls.append(f"hit-{worst}" if worst in SEV_ORDER else "hit-note")
        notes = "".join(
            f'<a class="pin pin-{e(k)}" href="{e(h)}"><b>{e(lbl)}</b>{(" " + inline_md(t)) if t else ""}</a>' if h else
            f'<span class="pin pin-{e(k)}"><b>{e(lbl)}</b>{(" " + inline_md(t)) if t else ""}</span>'
            for k, lbl, t, h in here)
        mark = "+" if n in changed else ""
        rows.append(f'<div class="{" ".join(cls)}"><span class="no">{n}</span><span class="mk">{mark}</span>'
                    f'<code>{highlight(text)}</code>{f"<span class=pins>{notes}</span>" if notes else ""}</div>')
    shown = sorted(show)
    what = ("new file in this change" if is_new else
            "+ marks lines this change adds or edits" if changed & show else "unchanged by this change")
    cap = (f'<figcaption><span class="path">{e(path)}</span> <span class="soft">lines {shown[0]}–{shown[-1]}, {what}'
           f'</span></figcaption>') if caption else ""
    return f'<figure class="code">{cap}<div class="src">{"".join(rows)}</div></figure>'


def patch_block(patch, title="Suggested fix"):
    if not patch:
        return ""
    rows = []
    for l in str(patch).rstrip("\n").split("\n"):
        if l.startswith(("+++", "---")):
            rows.append(f'<div class="pl ph"><code>{e(l)}</code></div>')
        elif l.startswith("@@"):
            rows.append(f'<div class="pl ph"><code>{e(l)}</code></div>')
        elif l.startswith("+"):
            rows.append(f'<div class="pl pa"><span class="mk">+</span><code>{highlight(l[1:])}</code></div>')
        elif l.startswith("-"):
            rows.append(f'<div class="pl pd"><span class="mk">−</span><code>{highlight(l[1:])}</code></div>')
        else:
            rows.append(f'<div class="pl"><span class="mk"></span><code>{highlight(l[1:] if l.startswith(" ") else l)}</code></div>')
    return (f'<figure class="code patch"><figcaption>{e(title)}<button type="button" class="copy" '
            f'data-copy="{e(patch)}">Copy</button></figcaption><div class="src">{"".join(rows)}</div></figure>')


def snippet_block(code, title):
    if not code:
        return ""
    rows = "".join(f'<div class="pl"><span class="mk"></span><code>{highlight(l)}</code></div>' for l in str(code).rstrip("\n").split("\n"))
    return (f'<figure class="code patch"><figcaption>{e(title)}<button type="button" class="copy" '
            f'data-copy="{e(code)}">Copy</button></figcaption><div class="src">{rows}</div></figure>')


# ---------------------------------------------------------------- page

CSS = """
:root{
  --paper:#f2f4f1; --sheet:#fbfcfa; --ink:#1d2421; --soft:#5b6762; --rule:#d5dbd6; --rule-2:#e6eae6;
  --accent:#2c4f7c; --accent-wash:#e6edf6;
  --crit:#b3261e; --crit-wash:#fbe7e4; --imp:#9a5a05; --imp-wash:#fbf0dc; --min:#4f6474; --min-wash:#e8eef2;
  --ok:#2f6b46; --ok-wash:#e2f1e7; --add:#e9f3ea; --add-mark:#3f7d4f; --del:#fbebe9;
  --code-ink:#24302b; --tk:#7a2f86; --ts:#28663e; --tn:#9a4c0b; --tc:#7b8783; --tt:#1f5d8e;
  --serif: Charter,"Bitstream Charter","Iowan Old Style","Sitka Text",Cambria,Georgia,serif;
  --sans: system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: ui-monospace,"Cascadia Code","SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#141917; --sheet:#1a201e; --ink:#e3e8e5; --soft:#9aa7a1; --rule:#323b37; --rule-2:#262e2b;
  --accent:#93b4e3; --accent-wash:#1f2a38;
  --crit:#f0a39c; --crit-wash:#3a1f1c; --imp:#ecc06f; --imp-wash:#33281a; --min:#a9bccb; --min-wash:#212b33;
  --ok:#94cfa7; --ok-wash:#1b2c22; --add:#1d2b21; --add-mark:#8ccb9b; --del:#33201e;
  --code-ink:#dfe6e2; --tk:#d6a2e0; --ts:#9ed3ab; --tn:#f0b27a; --tc:#7d8a85; --tt:#93c2ec;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 var(--sans)}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
code{font:13.5px/1.5 var(--mono)}
p code,li code,td code,h3 code{background:var(--rule-2);padding:.05em .35em;border-radius:3px;font-size:.88em;overflow-wrap:anywhere}
.layout{max-width:1220px;margin:0 auto;padding:40px 24px 96px;display:grid;grid-template-columns:200px minmax(0,1fr);gap:48px}
nav.rail{position:sticky;top:24px;align-self:start;font-size:14px;line-height:1.45;max-height:calc(100vh - 48px);overflow:auto}
nav.rail h2{font:600 13px/1.4 var(--sans);color:var(--soft);margin:0 0 8px}
nav.rail ol{list-style:none;margin:0 0 20px;padding:0}
nav.rail li{margin:0 0 6px}
nav.rail a{color:var(--ink);text-decoration:none;display:flex;gap:8px;align-items:baseline}
nav.rail a:hover{color:var(--accent);text-decoration:underline}
nav.rail .tag{flex:none;font-weight:600;font-size:12px;min-width:2.2em}
main{min-width:0}
.where-from{font-size:14px;color:var(--soft);margin:0 0 14px}
h1{font:600 clamp(28px,4.2vw,42px)/1.15 var(--serif);letter-spacing:-.01em;margin:0 0 18px;max-width:24ch}
.verdict{display:inline-block;font-weight:600;font-size:15px;padding:3px 12px;border-radius:999px;margin-bottom:12px}
.verdict.crit{background:var(--crit-wash);color:var(--crit)}.verdict.imp{background:var(--imp-wash);color:var(--imp)}.verdict.ok{background:var(--ok-wash);color:var(--ok)}
.lede{font:19px/1.55 var(--serif);max-width:66ch;margin:0 0 22px}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:0 0 8px}
.facts div{padding:12px 16px 12px 0}
.facts dt{font-size:13px;color:var(--soft);margin:0 0 2px}
.facts dd{margin:0;font-weight:600;font-size:15px;overflow-wrap:anywhere}
section{margin-top:64px}
h2.sec{font:600 26px/1.25 var(--serif);margin:0 0 6px}
.sec-note{color:var(--soft);margin:0 0 24px;max-width:66ch}
.narr{font:17px/1.65 var(--serif);max-width:68ch}
.narr p{margin:0 0 .8em}
.narr ul,.narr ol{margin:0 0 .9em;padding-left:1.3em}
.narr li{margin:0 0 .35em}
.context{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:28px;margin:8px 0 0}
.context h3{font:600 15px/1.4 var(--sans);margin:0 0 6px;color:var(--soft)}
.context .narr{font-size:16px}
.step{display:grid;grid-template-columns:44px minmax(0,1fr);gap:0 18px;padding:28px 0;border-top:1px solid var(--rule)}
.step:first-of-type{border-top:0;padding-top:4px}
.step-n{font:600 22px/1 var(--serif);color:var(--accent);width:44px;height:44px;border:1.5px solid var(--accent);border-radius:50%;display:grid;place-items:center;margin-top:2px}
.step h3{font:600 20px/1.3 var(--serif);margin:6px 0 4px}
.step .kind{font-size:13px;color:var(--soft);margin:0 0 12px}
.step .refs{margin:12px 0 0;font-size:14px;color:var(--soft)}
figure.code{margin:16px 0 0;background:var(--sheet);border:1px solid var(--rule);border-radius:6px;overflow:hidden}
figure.code figcaption{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;padding:8px 12px;border-bottom:1px solid var(--rule);color:var(--soft)}
figure.code figcaption .path{font:600 13px/1.4 var(--mono);color:var(--ink)}
.soft{color:var(--soft)}
.src{overflow-x:auto;padding:6px 0;color:var(--code-ink)}
.ln{display:grid;grid-template-columns:3.4em 1.2em max-content;align-items:start;min-height:21px;position:relative}
.ln .no{color:var(--tc);text-align:right;padding-right:10px;font:12.5px/1.5 var(--mono);user-select:none}
.ln .mk{color:var(--add-mark);font:600 13px/1.5 var(--mono);user-select:none}
.ln code{white-space:pre;padding-right:16px}
.tk{color:var(--tk)}.ts{color:var(--ts)}.tn{color:var(--tn)}.tc{color:var(--tc);font-style:italic}.tt{color:var(--tt)}
.ln.add{background:var(--add)}
.ln.gap .no{color:var(--soft)}
.ln.hit-critical{background:var(--crit-wash);box-shadow:inset 3px 0 0 var(--crit)}
.ln.hit-important{background:var(--imp-wash);box-shadow:inset 3px 0 0 var(--imp)}
.ln.hit-minor{background:var(--min-wash);box-shadow:inset 3px 0 0 var(--min)}
.ln.hit-note{box-shadow:inset 3px 0 0 var(--accent);background:var(--accent-wash)}
.pins{grid-column:1/-1;position:sticky;left:0;display:flex;flex-direction:column;gap:4px;padding:4px 12px 8px calc(4.6em);white-space:normal;width:min(84ch,calc(100vw - 340px))}
@media (max-width:980px){.pins{width:calc(100vw - 72px)}}
@media (max-width:560px){.pins{width:calc(100vw - 52px);padding-left:3.2em}}
.pin{font:13.5px/1.45 var(--sans);text-decoration:none;color:var(--ink);border-left:3px solid currentColor;padding:2px 0 2px 9px}
.pin b{font-weight:700;margin-right:4px}
.pin-critical{color:var(--crit)}.pin-important{color:var(--imp)}.pin-minor{color:var(--min)}.pin-note{color:var(--accent)}
.pin span,.pin{overflow-wrap:anywhere}
a.pin:hover b{text-decoration:underline}
.pl{display:grid;grid-template-columns:2em minmax(0,1fr);min-height:21px;padding-left:6px}
.pl code{white-space:pre-wrap;overflow-wrap:anywhere;padding-right:16px}
.pl .mk{text-align:center;font:600 13px/1.5 var(--mono)}
.pl.pa{background:var(--add)}.pl.pa .mk{color:var(--add-mark)}
.pl.pd{background:var(--del)}.pl.pd .mk{color:var(--crit)}
.pl.ph code{color:var(--soft)}
.pl.ph{grid-template-columns:minmax(0,1fr);padding-left:12px}
figure.patch .pl:not(.pa):not(.pd):not(.ph){padding-left:0}
.copy{margin-left:auto;font:600 12px/1 var(--sans);color:var(--accent);background:transparent;border:1px solid var(--rule);border-radius:4px;padding:5px 9px;cursor:pointer}
.copy:hover{background:var(--accent-wash)}
.problem{border-left:4px solid var(--min);padding:4px 0 8px 26px;margin:0 0 56px;scroll-margin-top:20px}
.problem.critical{border-left-color:var(--crit)}.problem.important{border-left-color:var(--imp)}
.problem .sev{font-weight:700;font-size:14px}
.problem.critical .sev{color:var(--crit)}.problem.important .sev{color:var(--imp)}.problem.minor .sev{color:var(--min)}
.problem h3{font:600 23px/1.3 var(--serif);margin:4px 0 6px;max-width:40ch}
.problem .loc{font-size:14px;color:var(--soft);margin:0 0 14px}
.problem .loc code{font-size:13px}
.problem h4{font:600 15px/1.4 var(--sans);margin:26px 0 8px}
.timeline{list-style:none;counter-reset:t;padding:0;margin:0;max-width:70ch}
.timeline li{counter-increment:t;position:relative;padding:0 0 12px 40px;font:16.5px/1.6 var(--serif)}
.timeline li::before{content:counter(t);position:absolute;left:0;top:1px;width:26px;height:26px;border-radius:50%;background:var(--sheet);border:1.5px solid var(--rule);font:600 13px/23px var(--sans);text-align:center;color:var(--soft)}
.timeline li:not(:last-child)::after{content:"";position:absolute;left:12.5px;top:30px;bottom:2px;width:1.5px;background:var(--rule)}
.timeline li.bad::before{border-color:currentColor}
.problem.critical .timeline li.bad::before{color:var(--crit);border-color:var(--crit)}
.problem.important .timeline li.bad::before{color:var(--imp);border-color:var(--imp)}
.twocol{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 36px}
.evidence{font-size:14px;color:var(--soft);margin-top:20px;max-width:72ch}
.evidence p{margin:0 0 4px}
table.req{border-collapse:collapse;width:100%;font-size:15px;max-width:900px}
table.req td,table.req th{padding:10px 12px 10px 0;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
table.req th{font-size:13px;color:var(--soft);font-weight:600}
.st{font-weight:700;white-space:nowrap}
.st-met{color:var(--ok)}.st-missing,.st-misunderstood{color:var(--crit)}.st-cannot_verify{color:var(--imp)}
details{border-top:1px solid var(--rule);padding:14px 0}
details:last-of-type{border-bottom:1px solid var(--rule)}
summary{cursor:pointer;font-weight:600}
details ul{margin:12px 0 0;padding-left:1.2em;max-width:72ch}
details li{margin:0 0 8px}
pre.raw{white-space:pre-wrap;font:13px/1.5 var(--mono);background:var(--sheet);border:1px solid var(--rule);border-radius:6px;padding:12px;overflow-x:auto;margin:12px 0 0}
dl.terms dt{font-weight:600;margin-top:12px}dl.terms dd{margin:2px 0 0;max-width:68ch}
ul.checks{list-style:none;padding:0;max-width:72ch}
ul.checks li{margin:0 0 10px;display:flex;gap:10px;align-items:baseline}
.clean{font:18px/1.6 var(--serif);border-left:4px solid var(--ok);padding:6px 0 6px 20px;max-width:66ch}
footer{margin-top:72px;font-size:13px;color:var(--soft)}
footer code{font-size:12px;overflow-wrap:anywhere}
@media (max-width:980px){
  .layout{grid-template-columns:minmax(0,1fr);gap:0;padding:28px 16px 72px}
  nav.rail{position:static;max-height:none;border:1px solid var(--rule);border-radius:6px;padding:12px 14px;margin:0 0 28px;background:var(--sheet)}
  nav.rail ol{display:flex;flex-wrap:wrap;gap:4px 16px;margin-bottom:12px}
  nav.rail ol li{margin:0}
}
@media (max-width:560px){
  .step{grid-template-columns:minmax(0,1fr)}
  .step-n{width:36px;height:36px;font-size:18px;margin-bottom:6px}
  .problem{padding-left:16px}
  .lede{font-size:17px}
  .ln{grid-template-columns:2.8em 1em max-content}
}
@media print{nav.rail{display:none}.layout{display:block}.copy{display:none}body{background:#fff}}
"""

JS = """
document.querySelectorAll('button.copy').forEach(function(b){
  b.addEventListener('click',function(){
    var t=b.getAttribute('data-copy');
    var done=function(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500)};
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done)}
    else{var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
      try{document.execCommand('copy');done()}catch(x){}document.body.removeChild(a)}
  });
});
"""


def words(s):
    return len(str(s or "").split())


def depth_warnings(findings, details, steps, src):
    """Places where the explainer is too thin to teach the problem. Printed, never fatal."""
    out = []
    if findings and not steps:
        out.append("no walkthrough steps")
    for f in findings:
        fid, d = f["id"], details.get(f["id"])
        if not d:
            out.append(f"{fid}: no entry in problems")
            continue
        if len(d.get("scenario") or []) < 3:
            out.append(f"{fid}: scenario has {len(d.get('scenario') or [])} steps (aim for 4-7 with real values)")
        for key, need in (("summary", 30), ("root_cause", 40), ("impact", 25)):
            if words(d.get(key)) < need:
                out.append(f"{fid}: {key} is {words(d.get(key))} words (aim for {need}+)")
        if not (d.get("fix") or {}).get("patch"):
            out.append(f"{fid}: fix.patch missing")
        code = (d.get("test") or {}).get("code") or ""
        if not code:
            out.append(f"{fid}: test.code missing")
        elif "\n" not in code.strip() and len(code) > 100:
            out.append(f"{fid}: test.code is one {len(code)}-char line; use real newlines")
        pin = d.get("pin_line")
        lines = src.lines(f.get("file"))
        if pin and lines and not 1 <= int(pin) <= len(lines):
            out.append(f"{fid}: pin_line {pin} is outside {f.get('file')}")
    return out


def render(pkg: Path):
    # Never leave a stale clean report at the package path after a failed rerender.
    (pkg / "review.html").unlink(missing_ok=True)
    meta = load_object(pkg / "meta.json")
    fx = validate_review(load_object(pkg / "findings.json"), meta)
    ex = load_object(pkg / "explainer.json", optional=True)
    contract = read(pkg / "contract.md")
    tests = read(pkg / "test-results.md")
    src = Source(pkg, meta)

    status = fx["execution_status"]
    def idnum(f):
        m = re.match(r"F(\d+)$", str(f.get("id", "")))
        return int(m.group(1)) if m else 10**6
    findings = sorted(fx.get("findings", []),
                      key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), idnum(f), -float(f.get("confidence", 0))))
    used = {str(f["id"]) for f in findings if f.get("id")}
    n = 0
    for f in findings:
        if not f.get("id"):
            n += 1
            while f"F{n}" in used:
                n += 1
            f["id"] = f"F{n}"
            used.add(f["id"])
    by_id = {f["id"]: f for f in findings}
    details = ex.get("problems") or {}

    verdict_txt = VERDICT.get(fx.get("verdict"), "Inconclusive")
    verdict_cls = {"dont-ship": "crit", "ship-after-fixes": "imp", "ship": "ok"}.get(fx.get("verdict"), "imp")
    if status != "completed":
        verdict_txt, verdict_cls = f"Review {status.replace('-', ' ')}: no verdict", "imp"
    title = ex.get("title") or meta.get("description", "Code review")
    counts = {k: sum(1 for f in findings if f.get("severity") == k) for k in SEV_ORDER}
    sev_text = ", ".join(f"{v} {k}" for k, v in counts.items() if v) or "none"
    contract_src = ""
    m = re.search(r"source:\s*`?([^\s`,;()]+)", contract, re.I)
    if m:
        contract_src = m.group(1).strip()
    tests_line = "not run"
    m = re.search(r"## Summary\s*\n(.+)", tests)
    if m:
        tests_line = m.group(1).strip()
    elif tests.strip():
        tests_line = "see Test evidence"

    # --- steps (walkthrough), with pins for findings that sit on each step's lines
    steps = []
    for s in ex.get("steps", []):
        path, a, b = s.get("file"), None, None
        if s.get("lines"):
            a, b = (s["lines"] + [s["lines"][0]])[:2] if isinstance(s["lines"], list) else (None, None)
        if not path:
            path, a, b = parse_where(s.get("where"))
        steps.append({**s, "_path": path, "_a": a, "_b": b})
    referenced = {fid for s in steps for fid in s.get("finding_ids", [])}
    orphans = [f["id"] for f in findings if f["id"] not in referenced]

    def finding_pins(path, lo, hi):
        pins = {}
        for f in findings:
            if f.get("file") != path:
                continue
            ls, le = int(f.get("line_start") or 0), int(f.get("line_end") or f.get("line_start") or 0)
            if le < lo or ls > hi:
                continue
            d = details.get(f["id"]) or {}
            anchor = int(d.get("pin_line") or 0) or max(ls, lo)
            if not lo <= anchor <= hi:
                anchor = max(ls, lo)
            note = d.get("line_note") or f.get("title")
            pins.setdefault(anchor, []).append((f.get("severity"), f["id"], note, f"#{f['id']}"))
        return pins

    step_html = []
    for i, s in enumerate(steps, 1):
        pins = {}
        if s["_path"] and s["_a"]:
            pins = finding_pins(s["_path"], s["_a"], s["_b"] or s["_a"])
            for note in s.get("notes", []):
                try:
                    pins.setdefault(int(note.get("line")), []).insert(0, ("note", "Note", note.get("text", ""), ""))
                except (TypeError, ValueError):
                    pass
        block = code_block(src, s["_path"], s["_a"], s["_b"], pins, fallback=s.get("snippet"))
        refs = ""
        if s.get("finding_ids"):
            links = ", ".join(f'<a href="#{e(fid)}">{e(fid)}: {e(by_id[fid]["title"])}</a>'
                              for fid in s["finding_ids"] if fid in by_id)
            refs = f'<p class="refs">Problems in this step: {links}</p>' if links else ""
        step_html.append(f'''
      <article class="step" id="step-{i}">
        <div class="step-n" aria-hidden="true">{i}</div>
        <div>
          <h3>{e(s.get("title"))}</h3>
          <p class="kind">{e(KIND_LABEL.get(s.get("kind"), s.get("kind") or ""))}{(" in " + e(s["_path"])) if s["_path"] else ""}</p>
          <div class="narr">{prose(s.get("explanation") or s.get("what_happens"))}</div>
          {block}
          {refs}
        </div>
      </article>''')

    # --- problems, in depth
    prob_html = []
    for f in findings:
        d = details.get(f["id"]) or {}
        sev = f.get("severity", "minor")
        ls, le = int(f.get("line_start") or 0), int(f.get("line_end") or f.get("line_start") or 0)
        pin_at = int(d.get("pin_line") or 0) or ls
        pins = {pin_at: [(sev, f["id"], d.get("line_note") or "", "")]}
        for t in d.get("trace", []):
            try:
                ln = int(t.get("line"))
            except (TypeError, ValueError):
                continue
            if (t.get("file") or f.get("file")) == f.get("file"):
                pins.setdefault(ln, []).append(("note", str(t.get("step") or "↳"), t.get("note", ""), ""))
        trace_lines = [int(t["line"]) for t in d.get("trace", []) if str(t.get("line", "")).isdigit()
                       and (t.get("file") or f.get("file")) == f.get("file")]
        lo, hi = min([ls, pin_at] + trace_lines), max([le, pin_at] + trace_lines)
        code = code_block(src, f.get("file"), lo, hi, pins, context=2, window=14)
        extra_files = []
        for t in d.get("trace", []):
            if t.get("file") and t.get("file") != f.get("file") and str(t.get("line", "")).isdigit():
                ln = int(t["line"])
                extra_files.append(code_block(src, t["file"], ln, ln, {ln: [("note", str(t.get("step") or "↳"), t.get("note", ""), "")]}, context=1))
        scenario = d.get("scenario") or []
        bad_idx = d.get("failure_step")
        timeline = ""
        if scenario:
            items = []
            for k, stp in enumerate(scenario, 1):
                bad = (bad_idx == k) or (bad_idx is None and k == len(scenario))
                items.append(f'<li class="{"bad" if bad else ""}">{inline_md(stp)}</li>')
            timeline = f'<h4>How it breaks</h4><ol class="timeline">{"".join(items)}</ol>'
        why = d.get("root_cause")
        impact = d.get("impact")
        cause_impact = ""
        if why or impact:
            cause_impact = '<div class="twocol">' + (
                f'<div><h4>Why it happens</h4><div class="narr">{prose(why)}</div></div>' if why else "") + (
                f'<div><h4>What it costs</h4><div class="narr">{prose(impact)}</div></div>' if impact else "") + "</div>"
        fix = d.get("fix") or {}
        fix_html = f'<h4>How to fix it</h4><div class="narr">{prose(fix.get("explanation") or f.get("recommendation"))}</div>'
        fix_html += patch_block(fix.get("patch"), f"Suggested change to {fix.get('file') or f.get('file')}")
        test = d.get("test") or {}
        test_html = ""
        if test.get("code") or test.get("explanation"):
            test_html = (f'<h4>Prove it with a test</h4><div class="narr">{prose(test.get("explanation"))}</div>'
                         + snippet_block(test.get("code"), test.get("name") or "Test that fails today"))
        what = d.get("summary") or f.get("body")
        ev_bits = [f"Confidence {e(f.get('confidence'))} out of 100, {e(STATUS_TEXT.get(f.get('evidence_status'), f.get('evidence_status')))} ({e(f.get('evidence_status'))})."]
        if f.get("lenses"):
            ev_bits.append(f"Raised by: {e(', '.join(f['lenses']))}.")
        if f.get("found_by") and f.get("found_by") != "claude":
            ev_bits.append(f"Found by {e(f['found_by'])}.")
        if f.get("contract_ref"):
            ev_bits.append(f"Breaks requirement {e(f['contract_ref'])}.")
        evidence = f'<div class="evidence"><p>{" ".join(ev_bits)}</p><p>Evidence: {inline_md(f.get("evidence"))}</p></div>'
        prob_html.append(f'''
      <article class="problem {e(sev)}" id="{e(f["id"])}">
        <span class="sev">{e(f["id"])} {e(SEV_LABEL.get(sev, sev))}</span>
        <h3>{inline_md(f.get("title"))}</h3>
        <p class="loc"><code>{e(f.get("file"))}:{ls}{("-" + str(le)) if le != ls else ""}</code></p>
        <div class="narr">{prose(what)}</div>
        {timeline}
        {code}
        {"".join(extra_files)}
        {cause_impact}
        {fix_html}
        {test_html}
        {evidence}
      </article>''')

    # --- remaining sections
    spec_rows = "".join(
        f'<tr><td><strong>{e(s.get("id"))}</strong></td><td class="st st-{e(s.get("status"))}">'
        f'{e({"met": "Met", "missing": "Missing", "misunderstood": "Misunderstood", "cannot_verify": "Can’t verify"}.get(s.get("status"), s.get("status")))}'
        f'</td><td>{inline_md(s.get("evidence", ""))}</td></tr>'
        for s in fx.get("spec_status", []))
    dropped = "".join(f'<li><strong>{inline_md(d.get("title"))}</strong> (score {e(d.get("confidence"))}). {inline_md(d.get("reason", ""))}</li>'
                      for d in fx.get("dropped", []))
    unchecked = "".join(f"<li>{inline_md(x)}</li>" for x in fx.get("not_checked", []) + fx.get("declined", []))
    concepts = "".join(f'<dt>{e(c.get("term"))}</dt><dd>{inline_md(c.get("meaning"))}</dd>' for c in ex.get("key_concepts", []))
    tryit = "".join(f'<li><input type="checkbox" id="try{i}"><label for="try{i}">{inline_md(t)}</label></li>'
                    for i, t in enumerate(ex.get("try_it_yourself", []), 1))
    files_rows = "".join(
        f'<tr><td><code>{e(c.get("path"))}</code></td><td>{e(c.get("change", ""))}</td><td>{inline_md(c.get("role", ""))}</td></tr>'
        for c in ex.get("changed_files", [])) or "".join(
        f'<tr><td><code>{e(f.get("path"))}</code></td><td>{e(f.get("status"))}</td><td>+{f.get("added")} −{f.get("deleted")}</td></tr>'
        for f in meta.get("files", []))

    nav = ['<nav class="rail" aria-label="Contents"><h2>On this page</h2><ol>',
           '<li><a href="#top">Summary</a></li>']
    if steps:
        nav.append('<li><a href="#walkthrough">How the code works</a></li>')
    nav.append('</ol>')
    if steps:
        nav.append('<h2>Walkthrough</h2><ol>' + "".join(
            f'<li><a href="#step-{i}"><span class="tag">{i}</span>{e(s.get("title"))}</a></li>' for i, s in enumerate(steps, 1)) + '</ol>')
    if findings:
        nav.append('<h2>Problems</h2><ol>' + "".join(
            f'<li><a href="#{e(f["id"])}"><span class="tag" style="color:var(--{ {"critical": "crit", "important": "imp"}.get(f.get("severity"), "min")})">{e(f["id"])}</span>{e(f.get("title"))}</a></li>'
            for f in findings) + '</ol>')
    more = [("spec", "Requirements", spec_rows), ("tests", "Test evidence", tests), ("concepts", "Terms", concepts),
            ("try", "Check it yourself", tryit), ("files", "Changed files", files_rows), ("dropped", "Not reported", dropped or unchecked)]
    nav.append('<h2>More</h2><ol>' + "".join(f'<li><a href="#{k}">{t}</a></li>' for k, t, v in more if v) + '</ol></nav>')

    overview = ""
    if ex.get("why") or ex.get("before") or ex.get("after"):
        overview = '<div class="context">' + "".join(
            f'<div><h3>{lbl}</h3><div class="narr">{prose(ex.get(k))}</div></div>'
            for k, lbl in (("why", "Why this change exists"), ("before", "Before"), ("after", "After")) if ex.get(k)) + "</div>"

    walk = ""
    if steps:
        walk = f'''
    <section id="walkthrough">
      <h2 class="sec">How the code works</h2>
      <p class="sec-note">The change in the order it runs, starting at <code>{e(ex.get("entry_point", "the entry point"))}</code>. Code is read from the reviewed commit; highlighted lines carry a problem.</p>
      {"".join(step_html)}
      {(f'<p class="sec-note">Also in this change: ' + ", ".join(f'<a href="#{e(o)}">{e(o)}</a>' for o in orphans) + ".</p>") if orphans else ""}
    </section>'''
    elif findings:
        walk = '<section><p class="sec-note">No walkthrough was written for this run. Problems are explained below.</p></section>'

    if findings:
        probs = f'''
    <section id="problems">
      <h2 class="sec">Problems, in depth</h2>
      <p class="sec-note">Most severe first. Each one shows how it breaks, the code involved, why it happens, what it costs, and how to fix and prove it.</p>
      {"".join(prob_html)}
    </section>'''
    elif status == "completed":
        probs = f'<section id="problems"><h2 class="sec">Problems</h2><p class="clean">No issues found. Nothing survived verification. {inline_md(fx.get("summary", ""))}</p></section>'
    else:
        probs = '<section id="problems"><h2 class="sec">Problems</h2><p class="clean">No clean conclusion: the review did not complete ({e(status)}). See what was not checked below.</p></section>'

    sections = []
    if spec_rows:
        sections.append(f'<section id="spec"><h2 class="sec">Requirements</h2><p class="sec-note">Checked against {inline_md(contract_src or "the stated purpose")}.</p>'
                        f'<table class="req"><thead><tr><th>Requirement</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{spec_rows}</tbody></table>'
                        + (f'<details><summary>The full contract used</summary><pre class="raw">{e(contract)}</pre></details>' if contract else "") + '</section>')
    sections.append(f'<section id="tests"><h2 class="sec">Test evidence</h2>'
                    + (f'<pre class="raw">{e(tests)}</pre>' if tests.strip() else '<p class="sec-note">No tests were run in this review. Findings were confirmed by reading the code.</p>') + '</section>')
    if concepts:
        sections.append(f'<section id="concepts"><h2 class="sec">Terms used here</h2><dl class="terms">{concepts}</dl></section>')
    if tryit:
        sections.append(f'<section id="try"><h2 class="sec">Check it yourself</h2><ul class="checks">{tryit}</ul></section>')
    sections.append(f'<section id="files"><h2 class="sec">Changed files</h2><table class="req"><tbody>{files_rows}</tbody></table></section>')
    if dropped or unchecked:
        sections.append('<section id="dropped"><h2 class="sec">Not reported</h2><p class="sec-note">Raised during the review but dropped after verification, or out of scope. Listed so you can disagree.</p>'
                        + (f'<details><summary>{len(fx.get("dropped", []))} candidates dropped after verification</summary><ul>{dropped}</ul></details>' if dropped else "")
                        + (f'<details><summary>Not checked or set aside</summary><ul>{unchecked}</ul></details>' if unchecked else "") + '</section>')

    facts = [("Verdict basis", f"{sev_text} problem{'s' if len(findings) != 1 else ''}"),
             ("Checked against", contract_src or "commit messages and code"),
             ("Size", f"{len(meta.get('files', []))} files, +{meta.get('added', 0)} −{meta.get('deleted', 0)}"),
             ("Tests", tests_line),
             ("Reviewed commit", (meta.get("reviewed_commit") or "")[:10] or "not recorded")]
    facts_html = '<dl class="facts">' + "".join(f'<div><dt>{e(k)}</dt><dd>{inline_md(v)}</dd></div>' for k, v in facts) + '</dl>'

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}: code review</title>
<style>{CSS}</style></head>
<body><div class="layout">
  {"".join(nav)}
  <main id="top">
    <p class="where-from">{e(meta.get("repo", ""))}, {e(meta.get("description", ""))}</p>
    <span class="verdict {verdict_cls}">{e(verdict_txt)}</span>
    <h1>{e(title)}</h1>
    <p class="lede">{inline_md(ex.get("one_liner") or fx.get("summary", ""))}</p>
    {f'<div class="narr"><p>{inline_md(fx.get("summary"))}</p></div>' if ex.get("one_liner") and fx.get("summary") else ""}
    {facts_html}
    {overview}
    {walk}
    {probs}
    {"".join(sections)}
    <footer><p>Generated by review-kit on {_dt.datetime.now().strftime("%d %b %Y, %H:%M")}. Execution: {e(status)}. Reviewed commit <code>{e(meta.get("reviewed_commit", "not recorded"))}</code>, read from {e(meta.get("source_kind", "not recorded"))}.</p><p>Run folder: <code>{e(pkg)}</code></p></footer>
  </main>
</div>
<script>{JS}</script>
</body></html>'''
    out = pkg / "review.html"
    out.write_text(page)
    for w in depth_warnings(findings, details, steps, src):
        print(f"thin: {w}", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: render_html.py PKG")
    try:
        render(Path(sys.argv[1]))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        sys.exit(f"HTML generation failed: {exc}")
