#!/usr/bin/env python3
"""Render the review-kit HTML walkthrough from a review package.

Reads PKG/meta.json, PKG/findings.json (validated), PKG/explainer.json (optional),
PKG/contract.md, PKG/test-results.md and PKG/diff-numbered.txt. Code shown on the page is
read from the reviewed source (meta.repo_root), never retyped by the model; changed lines are
taken from the diff. Writes PKG/review.html. Self-contained: no network, no external assets.
"""
import datetime as _dt
import html
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_data import load_object, validate_review  # noqa: E402
from collect import validate_source  # noqa: E402
import diagrams  # noqa: E402

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
        if meta.get("source_kind"):
            try:
                validate_source(meta, pkg)
            except (OSError, ValueError, KeyError, RuntimeError):
                # After cleanup or edits, only saved diff lines describe the reviewed revision.
                self.root = None
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
        text = read(self.root / path) if self.root is not None else ""
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
  --paper:#f5f6f8; --sheet:#ffffff; --sunk:#f0f2f5; --ink:#14171c; --soft:#5b6472; --faint:#8a93a1; --rule:#e2e5ea; --rule-2:#eceef2;
  --accent:#3b5bdb; --accent-ink:#2f49b5; --accent-wash:#edf1fd;
  --crit:#c92a2a; --crit-wash:#fdeeee; --imp:#b35c00; --imp-wash:#fff3e3; --min:#506179; --min-wash:#eef2f7;
  --ok:#1f8a52; --ok-wash:#e7f6ee; --add:#e8f7ee; --add-mark:#1f8a52; --del:#fdecec;
  --code-bg:#fbfcfd; --code-ink:#1f2430; --tk:#8a3ab9; --ts:#1b7a46; --tn:#b4540a; --tc:#8a93a1; --tt:#1d63b8;
  --shadow:0 1px 2px rgba(20,23,28,.04),0 2px 8px rgba(20,23,28,.04);
  --sans: Inter,"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: "JetBrains Mono","Cascadia Code","SF Mono",ui-monospace,Menlo,Consolas,"Liberation Mono",monospace;
  color-scheme:light;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#0e1014; --sheet:#161920; --sunk:#12151b; --ink:#e8eaef; --soft:#a0a8b6; --faint:#6f7886; --rule:#272b35; --rule-2:#1f232b;
  --accent:#8da2fb; --accent-ink:#a9b8fc; --accent-wash:#1b2140;
  --crit:#ff8787; --crit-wash:#331a1c; --imp:#ffb45c; --imp-wash:#33240f; --min:#a7b4c8; --min-wash:#1d232d;
  --ok:#63d297; --ok-wash:#12281c; --add:#12261a; --add-mark:#63d297; --del:#321a1b;
  --code-bg:#12151b; --code-ink:#dfe3ea; --tk:#d0a2f7; --ts:#8fd8a8; --tn:#ffb375; --tc:#6f7886; --tt:#8ec5ff;
  --shadow:none; color-scheme:dark;
}}
:root[data-theme="dark"]{
  --paper:#0e1014; --sheet:#161920; --sunk:#12151b; --ink:#e8eaef; --soft:#a0a8b6; --faint:#6f7886; --rule:#272b35; --rule-2:#1f232b;
  --accent:#8da2fb; --accent-ink:#a9b8fc; --accent-wash:#1b2140;
  --crit:#ff8787; --crit-wash:#331a1c; --imp:#ffb45c; --imp-wash:#33240f; --min:#a7b4c8; --min-wash:#1d232d;
  --ok:#63d297; --ok-wash:#12281c; --add:#12261a; --add-mark:#63d297; --del:#321a1b;
  --code-bg:#12151b; --code-ink:#dfe3ea; --tk:#d0a2f7; --ts:#8fd8a8; --tn:#ffb375; --tc:#6f7886; --tt:#8ec5ff;
  --shadow:none; color-scheme:dark;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:72px}
body{margin:0;background:var(--paper);color:var(--ink);font:15.5px/1.6 var(--sans);-webkit-font-smoothing:antialiased}
a{color:var(--accent-ink);text-underline-offset:2px}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
code{font:12.5px/1.6 var(--mono)}
p code,li code,td code,h3 code,dd code,.narr code{background:var(--rule-2);padding:.08em .38em;border-radius:4px;font-size:.86em;overflow-wrap:anywhere}
.soft{color:var(--soft)}
/* top bar */
.bar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--paper) 86%,transparent);backdrop-filter:saturate(1.4) blur(10px);-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--rule)}
.bar-in{max-width:1360px;margin:0 auto;padding:10px 28px;display:flex;align-items:center;gap:14px}
.logo{flex:none;display:grid;place-items:center;width:26px;height:26px;border-radius:7px;background:var(--ink);color:var(--paper);font:700 11px/1 var(--mono);letter-spacing:-.02em}
.crumbs{flex:1;min-width:0;margin:0;font-size:13.5px;color:var(--soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.crumbs strong{color:var(--ink);font-weight:600}.crumbs .sep{color:var(--faint);margin:0 4px}
.crumbs a{text-decoration:none;font-weight:600}.crumbs a:hover{text-decoration:underline}
.crumbs code{font-size:12px;background:var(--rule-2);padding:1px 6px;border-radius:4px}
.vchip{flex:none;display:inline-flex;align-items:center;gap:7px;font:600 12.5px/1 var(--sans);text-decoration:none;padding:7px 11px;border-radius:999px;border:1px solid var(--rule);background:var(--sheet);color:var(--ink)}
.vchip::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--min)}
.vchip.crit::before{background:var(--crit)}.vchip.imp::before{background:var(--imp)}.vchip.ok::before{background:var(--ok)}
.icon-btn{flex:none;font:600 12.5px/1 var(--sans);color:var(--soft);background:var(--sheet);border:1px solid var(--rule);border-radius:999px;padding:7px 11px;cursor:pointer}
.icon-btn:hover{color:var(--ink)}
/* layout */
.layout{max-width:1360px;margin:0 auto;padding:36px 28px 96px;display:grid;grid-template-columns:252px minmax(0,1fr);gap:56px}
main{min-width:0;position:relative;max-width:1000px}
nav.rail{position:sticky;top:76px;align-self:start;font-size:13.5px;line-height:1.4;max-height:calc(100vh - 96px);overflow:auto;padding:0 8px 24px 0;scrollbar-width:thin}
nav.rail h2{font:600 11px/1.4 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin:0 0 8px 10px}
nav.rail ol{list-style:none;margin:0 0 24px;padding:0}
nav.rail li{margin:0}
nav.rail a{color:var(--soft);text-decoration:none;display:flex;gap:8px;align-items:flex-start;padding:5px 10px;border-radius:7px}
nav.rail a:hover{color:var(--ink);background:var(--rule-2)}
nav.rail a.on{color:var(--ink);background:var(--sheet);box-shadow:var(--shadow),inset 0 0 0 1px var(--rule);font-weight:600}
nav.rail .tag{flex:none;font:600 11.5px/1.55 var(--mono);min-width:1.9em;color:var(--faint)}
nav.rail .rt{min-width:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
nav.rail .dot{flex:none;width:7px;height:7px;border-radius:50%;margin-top:6px;background:var(--min)}
nav.rail .dot.critical{background:var(--crit)}nav.rail .dot.important{background:var(--imp)}
nav.rail .cnt{margin-left:auto;font:600 11px/1.6 var(--sans);color:var(--faint)}
/* heading block */
.eyebrow{font:600 12px/1.4 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--accent-ink);margin:0 0 10px}
h1{font:700 clamp(28px,3.6vw,40px)/1.12 var(--sans);letter-spacing:-.025em;margin:0 0 14px;max-width:34ch;text-wrap:balance}
.lede{font-size:17px;line-height:1.65;color:var(--soft);max-width:72ch;margin:0 0 26px}
.lede code{color:var(--ink)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:12px;overflow:hidden;margin:0 0 28px;box-shadow:var(--shadow)}
.stat{background:var(--sheet);padding:14px 18px;min-width:0}
.stat .k{display:block;font:600 11px/1.4 var(--sans);letter-spacing:.07em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.stat .v{display:block;font:650 20px/1.3 var(--sans);letter-spacing:-.01em}
.stat .v small{font-size:13px;font-weight:500;color:var(--soft)}
.stat .s{display:block;font-size:12.5px;color:var(--soft);margin-top:2px;line-height:1.45}
.stat.note .v{font-size:14.5px;line-height:1.45;color:var(--accent-ink)}
.c-add{color:var(--add-mark);font-weight:600}.c-del{color:var(--crit);font-weight:600}
.effort{display:inline-flex;gap:3px;vertical-align:1px;margin-right:6px}.effort i{width:14px;height:6px;border-radius:2px;background:var(--rule)}.effort i.on{background:var(--accent)}
/* verdict */
.hero{background:var(--sheet);border:1px solid var(--rule);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.hero-top{padding:22px 26px 18px;border-top:4px solid var(--min);background:linear-gradient(180deg,var(--min-wash),var(--sheet) 85%)}
.hero-crit .hero-top{border-top-color:var(--crit);background:linear-gradient(180deg,var(--crit-wash),var(--sheet) 85%)}
.hero-imp .hero-top{border-top-color:var(--imp);background:linear-gradient(180deg,var(--imp-wash),var(--sheet) 85%)}
.hero-ok .hero-top{border-top-color:var(--ok);background:linear-gradient(180deg,var(--ok-wash),var(--sheet) 85%)}
.hero-head{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px}
.v-icon{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font:700 16px/1 var(--sans);color:#fff;background:var(--min)}
.hero-crit .v-icon{background:var(--crit)}.hero-imp .v-icon{background:var(--imp)}.hero-ok .v-icon{background:var(--ok)}
:root[data-theme="dark"] .v-icon{color:var(--paper)}
.v-label{font:700 22px/1.2 var(--sans);letter-spacing:-.015em}
.hero-crit .v-label{color:var(--crit)}.hero-imp .v-label{color:var(--imp)}.hero-ok .v-label{color:var(--ok)}
.v-tally{font-size:13.5px;color:var(--soft);font-weight:500}.v-tally a{color:var(--soft)}
.v-why{font-size:16px;line-height:1.65;margin:10px 0 0;max-width:80ch}
.hero .toolbar{margin:0;padding:12px 26px;border-top:1px solid var(--rule);background:var(--sunk)}
table.glance{width:100%;border-collapse:collapse;font-size:14.5px}
table.glance td{padding:14px 12px;border-top:1px solid var(--rule);vertical-align:top}
table.glance td:first-child{padding-left:26px;width:64px}
table.glance td:last-child{white-space:nowrap;color:var(--soft);padding-right:26px;text-align:right}
table.glance tr:hover td{background:var(--sunk)}
table.glance a{color:var(--ink);text-decoration:none;font-weight:600}table.glance a:hover{text-decoration:underline}
.g-fix{display:block;color:var(--soft);font-size:13.5px;margin-top:3px;line-height:1.5}
.loc-chip{font:12px/1.5 var(--mono);color:var(--soft);background:var(--rule-2);padding:2px 7px;border-radius:5px}
.pill{display:inline-block;min-width:2.6em;text-align:center;padding:2px 8px;border-radius:6px;font:700 11.5px/1.5 var(--mono);background:var(--min-wash);color:var(--min)!important}
.pill.critical{background:var(--crit-wash);color:var(--crit)!important}.pill.important{background:var(--imp-wash);color:var(--imp)!important}
/* sections */
main{counter-reset:sec}
section{margin-top:72px}
section.hero{margin-top:0}
h2.sec{font:700 24px/1.25 var(--sans);letter-spacing:-.02em;margin:0 0 6px;display:flex;align-items:baseline;gap:12px}
h2.sec::before{counter-increment:sec;content:counter(sec,decimal-leading-zero);font:600 13px/1 var(--mono);color:var(--accent-ink);background:var(--accent-wash);padding:5px 7px;border-radius:6px;transform:translateY(-3px)}
.sec-note{color:var(--soft);margin:0 0 24px;max-width:75ch}
.narr{font-size:15.5px;line-height:1.7;max-width:75ch}
.narr p{margin:0 0 .8em}
.narr ul,.narr ol{margin:0 0 .9em;padding-left:1.3em}
.narr li{margin:0 0 .35em}
.why{margin-bottom:18px}
.ba{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:12px;align-items:stretch}
.ba-card{border:1px solid var(--rule);border-radius:12px;padding:16px 20px;background:var(--sheet);box-shadow:var(--shadow)}
.ba-card h3{font:600 11px/1.4 var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--faint);margin:0 0 8px}
.ba-after{border-color:color-mix(in srgb,var(--add-mark) 45%,var(--rule))}.ba-after h3{color:var(--add-mark)}
.ba-card .narr{font-size:15px}.ba-card .narr p:last-child{margin-bottom:0}
.ba-arrow{align-self:center;font:600 20px/1 var(--sans);color:var(--faint)}
@media (max-width:720px){.ba{grid-template-columns:minmax(0,1fr)}.ba-arrow{transform:rotate(90deg);justify-self:center}}
.key-add{background:var(--add);color:var(--add-mark);font-weight:600;padding:0 5px;border-radius:4px}
table.files{border-collapse:separate;border-spacing:0;width:100%;font-size:14px;background:var(--sheet);border:1px solid var(--rule);border-radius:12px;overflow:hidden;box-shadow:var(--shadow)}
table.files td{padding:11px 14px;border-top:1px solid var(--rule);vertical-align:top}
table.files tr:first-child td{border-top:0}
table.files td.f-no{width:2.4em;color:var(--faint);font:600 12px/1.9 var(--mono);text-align:right;padding-right:0}
table.files td:last-child{white-space:nowrap;text-align:right}
table.files code{overflow-wrap:anywhere}
.f-chg{font-size:11px;font-weight:600;color:var(--soft);background:var(--rule-2);border-radius:999px;padding:1px 7px;margin-left:6px;text-transform:uppercase;letter-spacing:.04em}
.f-role{display:block;color:var(--soft);font-size:13.5px;margin-top:2px}
.churn{font:12px/1.4 var(--mono);display:inline-flex;align-items:center;gap:6px}
.bar-s{display:inline-flex;width:64px;height:6px;background:var(--rule-2);border-radius:3px;overflow:hidden}
.bar-s .b-a{background:var(--add-mark);display:block}.bar-s .b-d{background:var(--crit);display:block}
/* walkthrough */
.step{display:grid;grid-template-columns:36px minmax(0,1fr);gap:0 18px;padding:28px 0;border-top:1px solid var(--rule)}
.step:first-of-type{border-top:0;padding-top:4px}
.step-n{font:700 14px/1 var(--mono);color:var(--accent-ink);width:32px;height:32px;background:var(--accent-wash);border-radius:9px;display:grid;place-items:center;margin-top:2px}
.step h3{font:650 18px/1.35 var(--sans);letter-spacing:-.01em;margin:4px 0 2px}
.step .kind{font-size:12.5px;color:var(--faint);margin:0 0 10px;font-family:var(--mono);overflow-wrap:anywhere}
.step .refs{margin:12px 0 0;font-size:13.5px;color:var(--soft)}
/* code */
figure.code{margin:16px 0 0;background:var(--code-bg);border:1px solid var(--rule);border-radius:10px;overflow:hidden}
figure.code figcaption{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12.5px;padding:8px 14px;border-bottom:1px solid var(--rule);color:var(--soft);background:var(--sheet)}
figure.code figcaption .path{font:600 12.5px/1.4 var(--mono);color:var(--ink);overflow-wrap:anywhere}
.src{overflow-x:auto;padding:8px 0;color:var(--code-ink)}
.ln{display:grid;grid-template-columns:3.6em 1.4em max-content;align-items:start;min-height:20px;position:relative}
.ln .no{color:var(--faint);text-align:right;padding-right:10px;font:12px/1.65 var(--mono);user-select:none}
.ln .mk{color:var(--add-mark);font:600 12.5px/1.6 var(--mono);user-select:none}
.ln code{white-space:pre;padding-right:16px}
.tk{color:var(--tk)}.ts{color:var(--ts)}.tn{color:var(--tn)}.tc{color:var(--tc);font-style:italic}.tt{color:var(--tt)}
.ln.add{background:var(--add)}
.ln.gap .no{color:var(--faint)}
.ln.hit-critical{background:var(--crit-wash);box-shadow:inset 3px 0 0 var(--crit)}
.ln.hit-important{background:var(--imp-wash);box-shadow:inset 3px 0 0 var(--imp)}
.ln.hit-minor{background:var(--min-wash);box-shadow:inset 3px 0 0 var(--min)}
.ln.hit-note{box-shadow:inset 3px 0 0 var(--accent);background:var(--accent-wash)}
.pins{grid-column:1/-1;position:sticky;left:0;display:flex;flex-direction:column;gap:6px;padding:6px 14px 10px calc(5em);white-space:normal;width:min(84ch,calc(100vw - 400px))}
@media (max-width:1040px){.pins{width:calc(100vw - 72px)}}
@media (max-width:560px){.pins{width:calc(100vw - 52px);padding-left:3.2em}}
.pin{font:13px/1.5 var(--sans);text-decoration:none;color:var(--ink);background:var(--sheet);border:1px solid var(--rule);border-left:3px solid currentColor;border-radius:6px;padding:5px 10px}
.pin b{font-weight:700;margin-right:5px}
.pin-critical{color:var(--crit)}.pin-important{color:var(--imp)}.pin-minor{color:var(--min)}.pin-note{color:var(--accent-ink)}
.pin span,.pin{overflow-wrap:anywhere}
a.pin:hover b{text-decoration:underline}
.pl{display:grid;grid-template-columns:2em minmax(0,1fr);min-height:20px;padding-left:6px}
.pl code{white-space:pre-wrap;overflow-wrap:anywhere;padding-right:16px}
.pl .mk{text-align:center;font:600 12.5px/1.6 var(--mono)}
.pl.pa{background:var(--add)}.pl.pa .mk{color:var(--add-mark)}
.pl.pd{background:var(--del)}.pl.pd .mk{color:var(--crit)}
.pl.ph code{color:var(--soft)}
.pl.ph{grid-template-columns:minmax(0,1fr);padding-left:12px}
figure.patch .pl:not(.pa):not(.pd):not(.ph){padding-left:0}
.copy{margin-left:auto;font:600 12px/1 var(--sans);color:var(--accent-ink);background:var(--sheet);border:1px solid var(--rule);border-radius:7px;padding:7px 10px;cursor:pointer;white-space:nowrap}
.copy:hover{background:var(--accent-wash);border-color:color-mix(in srgb,var(--accent) 40%,var(--rule))}
/* problems */
.problem{background:var(--sheet);border:1px solid var(--rule);border-radius:14px;box-shadow:var(--shadow);padding:20px 26px 22px;margin:0 0 20px;position:relative;overflow:hidden}
.problem::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--min)}
.problem.critical::before{background:var(--crit)}.problem.important::before{background:var(--imp)}
.p-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.p-head .copy{margin-left:auto}
.sev{font:700 11px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;padding:5px 8px;border-radius:6px;background:var(--min-wash);color:var(--min)}
.problem.critical .sev{background:var(--crit-wash);color:var(--crit)}.problem.important .sev{background:var(--imp-wash);color:var(--imp)}
.pid{font:700 12.5px/1 var(--mono);color:var(--faint)}
.problem h3{font:650 20px/1.35 var(--sans);letter-spacing:-.015em;margin:12px 0 6px;max-width:60ch}
.problem .loc{margin:0 0 12px}
.problem .loc code{font-size:12px;color:var(--soft);overflow-wrap:anywhere}
.problem h4{font:650 14px/1.4 var(--sans);margin:26px 0 10px}
.timeline{list-style:none;counter-reset:t;padding:0;margin:0;max-width:75ch}
.timeline li{counter-increment:t;position:relative;padding:0 0 12px 38px;font-size:15px;line-height:1.6}
.timeline li::before{content:counter(t);position:absolute;left:0;top:0;width:24px;height:24px;border-radius:50%;background:var(--sheet);border:1.5px solid var(--rule);font:600 12px/21px var(--sans);text-align:center;color:var(--soft)}
.timeline li:not(:last-child)::after{content:"";position:absolute;left:11.5px;top:27px;bottom:2px;width:1.5px;background:var(--rule)}
.problem .timeline li.bad::before{color:#fff;background:var(--min);border-color:var(--min)}
.problem.critical .timeline li.bad::before{background:var(--crit);border-color:var(--crit)}
.problem.important .timeline li.bad::before{background:var(--imp);border-color:var(--imp)}
:root[data-theme="dark"] .problem .timeline li.bad::before{color:var(--paper)}
.twocol{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px 36px}
.evidence{font-size:13px;color:var(--soft);margin-top:22px;padding-top:14px;border-top:1px dashed var(--rule);max-width:80ch}
.evidence p{margin:0 0 4px}
.fold-btn,.chip{font:600 12px/1 var(--sans);color:var(--soft);background:var(--sheet);border:1px solid var(--rule);border-radius:999px;padding:7px 12px;cursor:pointer}
.fold-btn:hover,.chip:hover{color:var(--ink)}
.fold-btn::after{content:" ▾"}.problem.shut .fold-btn::after{content:" ▸"}
.problem.shut .p-body{display:none}.problem.shut{padding-bottom:14px}
.chip.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip.critical{color:var(--crit)}.chip.important{color:var(--imp)}.chip.on.critical,.chip.on.important{color:var(--paper)}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0 16px}.toolbar .grow{flex:1}
table.req{border-collapse:collapse;width:100%;font-size:14.5px}
table.req td,table.req th{padding:10px 12px 10px 0;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
table.req th{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--faint);font-weight:600}
.st{font-weight:700;white-space:nowrap}
.st-met{color:var(--ok)}.st-missing,.st-misunderstood{color:var(--crit)}.st-cannot_verify{color:var(--imp)}
details{border-top:1px solid var(--rule);padding:14px 0}
details:last-of-type{border-bottom:1px solid var(--rule)}
summary{cursor:pointer;font-weight:600}
details ul{margin:12px 0 0;padding-left:1.2em;max-width:78ch}
details li{margin:0 0 8px}
pre.raw{white-space:pre-wrap;font:12.5px/1.55 var(--mono);background:var(--code-bg);border:1px solid var(--rule);border-radius:10px;padding:14px;overflow-x:auto;margin:12px 0 0}
dl.terms{display:grid;grid-template-columns:minmax(120px,max-content) minmax(0,1fr);gap:10px 24px;margin:0;max-width:80ch}
dl.terms dt{font-weight:650}dl.terms dd{margin:0;color:var(--soft)}
ul.checks{list-style:none;padding:0;max-width:78ch}
ul.checks li{margin:0 0 10px;display:flex;gap:10px;align-items:baseline}
ul.wal{padding-left:1.2em;max-width:80ch}.wal li{margin:0 0 10px}
.clean{font-size:17px;border-left:4px solid var(--ok);padding:6px 0 6px 20px;max-width:70ch}
.pic-h{font:650 16px/1.4 var(--sans);margin:30px 0 4px}
details.fold{border:0;padding:0;margin-top:26px}
details.fold summary{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;cursor:pointer;list-style:none}
details.fold summary::-webkit-details-marker{display:none}
details.fold summary h4{margin:0}details.fold summary h4::after{content:" ▸";color:var(--faint)}
details.fold[open] summary h4::after{content:" ▾"}
.fold-hint{font:12px/1.4 var(--mono);color:var(--soft);min-width:0;overflow-wrap:anywhere}
kbd{font:11.5px/1 var(--mono);border:1px solid var(--rule);border-bottom-width:2px;border-radius:4px;padding:2px 5px;background:var(--sheet)}
footer{margin-top:80px;padding-top:20px;border-top:1px solid var(--rule);font-size:12.5px;color:var(--faint)}
footer code{font-size:11.5px;overflow-wrap:anywhere}
.hide{display:none!important}
@media (max-width:1040px){
  .layout{grid-template-columns:minmax(0,1fr);gap:0;padding:24px 16px 72px}
  .bar-in{padding:10px 16px}
  nav.rail{position:static;max-height:none;border:1px solid var(--rule);border-radius:12px;padding:12px 10px;margin:0 0 28px;background:var(--sheet)}
  nav.rail ol{display:flex;flex-wrap:wrap;gap:2px 4px;margin-bottom:0}
  nav.rail h2:not(:first-child),nav.rail ol:not(:first-of-type){display:none}
}
@media (max-width:640px){
  .vchip{display:none}
  .step{grid-template-columns:minmax(0,1fr)}
  .step-n{margin-bottom:8px}
  .problem{padding:16px 16px 18px}
  .hero-top{padding:18px 16px 14px}.hero .toolbar{padding:10px 16px}
  table.glance td:first-child{padding-left:16px}table.glance td:last-child{display:none}
  .lede{font-size:16px}
  .ln{grid-template-columns:2.8em 1em max-content}
  dl.terms{grid-template-columns:minmax(0,1fr)}
}
@media print{.bar,.toolbar,.fold-btn,.copy{display:none}.problem.shut .p-body{display:block}.hero,.problem{break-inside:avoid;box-shadow:none}
nav.rail{display:none}.layout{display:block}body{background:#fff}}
"""

JS = """
document.querySelectorAll('button.copy').forEach(function(b){
  var label=b.textContent;
  b.addEventListener('click',function(){
    var t=b.getAttribute('data-copy');
    var done=function(){b.textContent='Copied';setTimeout(function(){b.textContent=label},1500)};
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done)}
    else{var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();
      try{document.execCommand('copy');done()}catch(x){}document.body.removeChild(a)}
  });
});
var probs=[].slice.call(document.querySelectorAll('article.problem'));
function setShut(a,shut){a.classList.toggle('shut',shut);var b=a.querySelector('.fold-btn');if(b)b.setAttribute('aria-expanded',String(!shut))}
probs.forEach(function(a){var b=a.querySelector('.fold-btn');if(b)b.addEventListener('click',function(){setShut(a,!a.classList.contains('shut'))})});
function byId(i){return document.getElementById(i)}
if(byId('fold-all'))byId('fold-all').addEventListener('click',function(){probs.forEach(function(a){setShut(a,true)})});
if(byId('open-all'))byId('open-all').addEventListener('click',function(){probs.forEach(function(a){setShut(a,false)})});
function openTarget(){var a=byId(location.hash.slice(1));if(a&&a.classList&&a.classList.contains('problem'))setShut(a,false)}
window.addEventListener('hashchange',openTarget);openTarget();
document.querySelectorAll('.chip[data-filter]').forEach(function(c){
  c.addEventListener('click',function(){
    var f=c.getAttribute('data-filter');
    document.querySelectorAll('.chip[data-filter]').forEach(function(x){x.classList.toggle('on',x===c)});
    document.querySelectorAll('article.problem,table.glance tr').forEach(function(x){
      x.classList.toggle('hide',f!=='all'&&x.getAttribute('data-sev')!==f)});
  });
});
document.addEventListener('keydown',function(ev){
  if(ev.target.closest('input,textarea,select')||ev.metaKey||ev.ctrlKey||ev.altKey)return;
  if(ev.key!=='j'&&ev.key!=='k')return;
  var vis=probs.filter(function(a){return !a.classList.contains('hide')}),t=null;
  vis.forEach(function(a){var y=a.getBoundingClientRect().top;
    if(ev.key==='j'&&y>30&&!t)t=a;if(ev.key==='k'&&y<-10)t=a});
  if(t)t.scrollIntoView({block:'start'});
});
if('IntersectionObserver' in window){
  var links={};document.querySelectorAll('nav.rail a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a});
  var cur=null,io=new IntersectionObserver(function(es){
    es.forEach(function(en){if(en.isIntersecting&&links[en.target.id]){
      if(cur)cur.classList.remove('on');cur=links[en.target.id];cur.classList.add('on');
      var r=cur.getBoundingClientRect(),nav=cur.closest('nav');
      if(nav&&(r.top<0||r.bottom>window.innerHeight))nav.scrollTop+=r.top-window.innerHeight/2}});
  },{rootMargin:'-10% 0px -80% 0px'});
  Object.keys(links).forEach(function(id){var t=byId(id);if(t)io.observe(t)});
}
var tb=byId('theme');
if(tb){
  try{var saved=localStorage.getItem('rk-theme');if(saved)document.documentElement.setAttribute('data-theme',saved)}catch(x){}
  tb.addEventListener('click',function(){
    var d=document.documentElement,now=d.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
    var next=now==='dark'?'light':'dark';d.setAttribute('data-theme',next);try{localStorage.setItem('rk-theme',next)}catch(x){}
  });
}
"""


FIX_PREFIX_ONE = ("Fix this code review finding. Write the failing test first if the project has tests, make the "
                  "smallest change that removes the root cause, then run the closest tests.\n\n")
FIX_PREFIX_ALL = ("Fix these code review findings one at a time, most severe first. For each: write the failing "
                  "test first if the project has tests, make the smallest change that removes the root cause, then "
                  "run the closest tests. Do not commit.\n\n")


def first_sentence(text, limit=150):
    text = " ".join(str(text or "").split())
    m = re.match(r"(.+?[\w)\]'\"`][.!?])(\s|$)", text)  # not at "..." or "e.g. "
    text = m.group(1) if m else text
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def short_path(path, keep=2):
    """'a/b/c/d/topk.py' -> 'd/topk.py' for tight spots; the full path goes in a title."""
    parts = str(path or "").replace("\\", "/").split("/")
    return "/".join(parts[-keep:]) if len(parts) > keep else str(path or "")


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


EFFORT_TEXT = {1: "under 10 min", 2: "about 15 min", 3: "about 30 min", 4: "about an hour", 5: "half a day or more"}


def where_from(meta):
    """Split meta.description ('PR #52: Title (https://…)', 'branch x vs abc + uncommitted') into parts."""
    desc = " ".join(str(meta.get("description") or "").split())
    url = ""
    m = re.search(r"\s*\((https?://[^\s()]+)\)\s*$", desc)
    if m:
        url, desc = m.group(1), desc[:m.start()]
    m = re.match(r"PR #(\d+):?\s*(.*)$", desc)
    if m:
        return {"label": f"PR #{m.group(1)}", "url": url, "title": m.group(2).strip()}
    return {"label": desc, "url": url, "title": ""}


def render(pkg: Path):
    # Never leave a stale clean report at the package path after a failed rerender.
    (pkg / "review.html").unlink(missing_ok=True)
    meta = load_object(pkg / "meta.json")
    fx = validate_review(load_object(pkg / "findings.json"), meta)
    ex = load_object(pkg / "explainer.json", optional=True)
    contract = read(pkg / "contract.md") or str(ex.get("contract") or "")
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
    details = dict(ex.get("problems") or {})
    # Problem write-ups may come from parallel writers, one file per group of findings.
    for part in sorted(pkg.glob("problems-*.json")):
        extra = load_object(part, optional=True)
        details.update({k: v for k, v in extra.items() if isinstance(v, dict)})
    # Ids given before verification can have gaps or be out of severity order: number them as the
    # report does (F1 = first shown) and carry the new ids into every reference.
    renum = {f["id"]: f"F{i}" for i, f in enumerate(findings, 1)}
    if any(k != v for k, v in renum.items()):
        swap = lambda ids: [renum.get(x, x) for x in ids or []]
        for f in findings:
            f["id"] = renum[f["id"]]
        by_id = {f["id"]: f for f in findings}
        details = {renum.get(k, k): v for k, v in details.items()}
        for s in ex.get("steps") or []:
            s["finding_ids"] = swap(s.get("finding_ids"))
        for node in (ex.get("architecture") or {}).get("nodes") or []:
            node["finding_ids"] = swap(node.get("finding_ids"))
        for q in ex.get("sequences") or []:
            for m in q.get("messages") or []:
                if m.get("finding_id"):
                    m["finding_id"] = renum.get(m["finding_id"], m["finding_id"])

    verdict_txt = VERDICT.get(fx.get("verdict"), "Inconclusive")
    verdict_cls = {"dont-ship": "crit", "ship-after-fixes": "imp", "ship": "ok"}.get(fx.get("verdict"), "imp")
    explain_only = fx.get("mode") == "explain"
    if status != "completed":
        verdict_txt, verdict_cls = f"Review {status.replace('-', ' ')}: no verdict", "imp"
    origin = where_from(meta)
    title = ex.get("title") or origin["title"] or "Code review"
    counts = {k: sum(1 for f in findings if f.get("severity") == k) for k in SEV_ORDER}
    sev_text = " · ".join(f"{v} {k}" for k, v in counts.items() if v)
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
    prob_html, fix_prompts = [], []
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
            test_html = (f'<details class="fold"><summary><h4>Prove it with a test</h4><span class="fold-hint">{e(test.get("name") or "show the test")}</span></summary>'
                         f'<div class="narr">{prose(test.get("explanation"))}</div>'
                         + snippet_block(test.get("code"), test.get("name") or "Test that fails today") + '</details>')
        what = d.get("summary") or f.get("body")
        ev_bits = [f"Confidence {e(f.get('confidence'))} out of 100, {e(STATUS_TEXT.get(f.get('evidence_status'), f.get('evidence_status')))} ({e(f.get('evidence_status'))})."]
        if f.get("lenses"):
            ev_bits.append(f"Raised by: {e(', '.join(f['lenses']))}.")
        if f.get("found_by") and f.get("found_by") != "claude":
            ev_bits.append(f"Found by {e(f['found_by'])}.")
        if f.get("contract_ref"):
            ev_bits.append(f"Breaks requirement {e(f['contract_ref'])}.")
        evidence = f'<div class="evidence"><p>{" ".join(ev_bits)}</p><p>Evidence: {inline_md(f.get("evidence"))}</p></div>'
        where = f'{f.get("file")}:{ls}{("-" + str(le)) if le != ls else ""}'
        prompt_bits = [f'{f["id"]} ({sev}): {f.get("title", "")}', f"Where: {where}", f'Problem: {what or ""}']
        if scenario:
            prompt_bits.append("How it breaks: " + " ".join(f"{k}) {x}" for k, x in enumerate(scenario, 1)))
        prompt_bits.append(f'Fix: {fix.get("explanation") or f.get("recommendation") or ""}')
        if test.get("explanation"):
            prompt_bits.append(f'Test: {test.get("explanation")}')
        fix_prompts.append("\n".join(b for b in prompt_bits if b.split(": ", 1)[-1].strip()))
        one_fix = FIX_PREFIX_ONE + fix_prompts[-1]
        prob_html.append(f'''
      <article class="problem {e(sev)}{" shut" if sev == "minor" else ""}" id="{e(f["id"])}" data-sev="{e(sev)}">
        <div class="p-head"><span class="sev">{e(SEV_LABEL.get(sev, sev))}</span><span class="pid">{e(f["id"])}</span>
          <button class="copy" data-copy="{e(one_fix)}" title="Copy a prompt that asks Claude Code to fix this one">Copy fix prompt</button>
          <button class="fold-btn" aria-expanded="{"false" if sev == "minor" else "true"}" title="Show or hide the details">Details</button></div>
        <h3>{inline_md(f.get("title"))}</h3>
        <p class="loc"><code>{e(where)}</code></p>
        <div class="narr">{prose(what)}</div>
        <div class="p-body">
        {timeline}
        {code}
        {"".join(extra_files)}
        {cause_impact}
        {fix_html}
        {test_html}
        {evidence}
        </div>
      </article>''')

    # --- remaining sections
    spec_rows = "".join(
        f'<tr><td><strong>{e(s.get("id"))}</strong></td><td class="st st-{e(s.get("status"))}">'
        f'{e({"met": "Met", "missing": "Missing", "misunderstood": "Misunderstood", "cannot_verify": "Can’t verify"}.get(s.get("status"), s.get("status")))}'
        f'</td><td>{inline_md(s.get("evidence", ""))}</td></tr>'
        for s in fx.get("spec_status", []))
    dropped = "".join(f'<li><strong>{inline_md(d.get("title"))}</strong>{(" (confidence " + e(d.get("confidence")) + ")") if d.get("confidence") is not None else ""}. {inline_md(d.get("reason", ""))}</li>'
                      for d in fx.get("dropped", []))
    unchecked = "".join(f"<li>{inline_md(x)}</li>" for x in fx.get("not_checked", []) + fx.get("declined", []))
    concepts = "".join(f'<dt>{e(c.get("term"))}</dt><dd>{inline_md(c.get("meaning"))}</dd>' for c in ex.get("key_concepts", []))
    tryit = "".join(f'<li><input type="checkbox" id="try{i}"><label for="try{i}">{inline_md(t)}</label></li>'
                    for i, t in enumerate(ex.get("try_it_yourself", []), 1))
    # Changed files: the writer's roles and reading order joined with the real line counts.
    stats = {f.get("path"): f for f in meta.get("files", []) if isinstance(f, dict)}
    roles = {c.get("path"): c for c in ex.get("changed_files", []) if isinstance(c, dict)}
    paths = sorted(set(stats) | set(roles), key=lambda p: (roles.get(p, {}).get("order") or 999, p or ""))
    biggest = max([int(f.get("added") or 0) + int(f.get("deleted") or 0) for f in stats.values()] + [1])
    def churn(f):
        a, d = int(f.get("added") or 0), int(f.get("deleted") or 0)
        w = lambda n: f"{max(2, round(60 * n / biggest)) if n else 0}px"
        return (f'<span class="churn"><span class="c-add">+{a:,}</span> <span class="c-del">−{d:,}</span>'
                f'<span class="bar-s"><i class="b-a" style="width:{w(a)}"></i><i class="b-d" style="width:{w(d)}"></i></span></span>')
    files_rows = "".join(
        f'<tr><td class="f-no">{e(roles.get(p, {}).get("order") or "")}</td><td><code>{e(p)}</code>'
        f'{(" <span class=f-chg>" + e(roles[p].get("change") or stats.get(p, {}).get("status") or "") + "</span>") if p in roles else ""}'
        f'<span class="f-role">{inline_md(roles.get(p, {}).get("role", ""))}</span></td>'
        f'<td>{churn(stats[p]) if p in stats else ""}</td></tr>'
        for p in paths if p)

    # --- the big picture: architecture, flows, module map (all drawn here, never by the model)
    pics = []
    arch = ex.get("architecture")
    if isinstance(arch, dict):
        svg = diagrams.architecture(arch, by_id)
        if svg:
            pics.append(f'<figure class="dg-wrap">{svg}<figcaption>{inline_md(arch.get("caption") or "How the parts of this change fit together. Arrows show calls and data flow.")}</figcaption>'
                        '<div class="legend"><span class="lg-changed">changed in this change</span>'
                        + ("" if explain_only else '<span class="lg-crit">has a problem (badge links to it)</span>')
                        + '<span class="lg-ext">external system</span></div></figure>')
    seqs = ex.get("sequences") or ([ex["sequence"]] if isinstance(ex.get("sequence"), dict) else [])
    for q in seqs:
        if isinstance(q, dict):
            svg = diagrams.sequence(q, by_id)
            if svg:
                pics.append(f'<h3 class="pic-h">{e(q.get("title") or "What happens, in order")}</h3><figure class="dg-wrap">{svg}'
                            f'<figcaption>{inline_md(q.get("caption") or "Each arrow is one call or message, top to bottom. Dashed arrows are replies or background work.")}</figcaption></figure>')
    if src.root is not None:
        try:
            mod = diagrams.import_graph(src.root, [f.get("path", "") for f in meta.get("files", []) if f.get("status") != "deleted"])
        except (OSError, ValueError, RecursionError):
            mod = {}
        if mod.get("nodes") and len(mod["nodes"]) > 1:
            pics.append('<h3 class="pic-h">Python modules touched</h3><figure class="dg-wrap">' + diagrams.module_map(mod)
                        + '<figcaption>Drawn from the import statements; an arrow means "imports". The middle column is what this change edits, the left is code that uses it (its blast radius), the right is what it builds on.</figcaption></figure>')
    big = ""
    if pics:
        big = f'''
    <section id="picture">
      <h2 class="sec">The big picture</h2>
      <p class="sec-note">The parts this change touches and how a request or job moves through them{"" if explain_only or not findings else ", with each problem badged where it happens"}.</p>
      {"".join(pics)}
    </section>'''

    # --- review effort, 1 (minutes) to 5 (an afternoon), from size, spread and risk
    changed_lines = int(meta.get("added", 0)) + int(meta.get("deleted", 0))
    effort = 1 + (changed_lines > 80) + (changed_lines > 300) + (changed_lines > 800) + (len(meta.get("risk") or []) >= 3)
    effort = max(1, min(5, int(ex.get("review_effort") or effort)))

    plausible_items = [p for p in fx.get("plausible", []) if isinstance(p, dict)]
    plausible = "".join(
        f'<li><strong>{inline_md(p.get("title"))}</strong> <code>{e(p.get("file", ""))}{(":" + str(p["line_start"])) if p.get("line_start") else ""}</code>. '
        f'Check: {inline_md(p.get("check", ""))}</li>' for p in plausible_items)

    # --- context: why, then before and after side by side
    overview = ""
    if ex.get("why") or ex.get("before") or ex.get("after"):
        ba = ""
        if ex.get("before") or ex.get("after"):
            ba = ('<div class="ba">'
                  + (f'<div class="ba-card ba-before"><h3>Before</h3><div class="narr">{prose(ex.get("before"))}</div></div>' if ex.get("before") else "")
                  + ('<div class="ba-arrow" aria-hidden="true">→</div>' if ex.get("before") and ex.get("after") else "")
                  + (f'<div class="ba-card ba-after"><h3>After</h3><div class="narr">{prose(ex.get("after"))}</div></div>' if ex.get("after") else "")
                  + '</div>')
        why_html = f'<div class="narr why">{prose(ex.get("why"))}</div>' if ex.get("why") else ""
        overview = f'''
    <section id="context">
      <h2 class="sec">What changed and why</h2>
      {why_html}
      {ba}
    </section>'''

    walk = ""
    if steps:
        walk = f'''
    <section id="walkthrough">
      <h2 class="sec">How the code works</h2>
      <p class="sec-note">The change in the order it runs, starting at <code>{e(ex.get("entry_point", "the entry point"))}</code>. Code is read from the reviewed commit; <span class="key-add">+ lines</span> are new or edited, and a coloured edge marks a problem.</p>
      {"".join(step_html)}
      {('<p class="sec-note">Also in this change: ' + ", ".join(f'<a href="#{e(o)}">{e(o)}</a>' for o in orphans) + ".</p>") if orphans else ""}
    </section>'''
    elif findings:
        walk = '<section><p class="sec-note">No walkthrough was written for this run. Problems are explained below.</p></section>'

    # --- the verdict card: verdict, why, and every problem with its one-line fix
    hero = ""
    if not explain_only:
        rows = "".join(
            f'<tr data-sev="{e(f.get("severity", "minor"))}"><td><a class="pill {e(f.get("severity", "minor"))}" href="#{e(f["id"])}">{e(f["id"])}</a></td>'
            f'<td><a href="#{e(f["id"])}">{inline_md(f.get("title"))}</a><span class="g-fix">{inline_md(first_sentence(f.get("recommendation") or (details.get(f["id"]) or {}).get("fix", {}).get("explanation")))}</span></td>'
            f'<td><code class="loc-chip" title="{e(f.get("file"))}:{e(f.get("line_start"))}">{e(short_path(f.get("file")))}:{e(f.get("line_start"))}</code></td></tr>' for f in findings)
        tools = ""
        if findings:
            several = sum(1 for v in counts.values() if v) > 1
            chips = ""
            if several:
                chips = f'<button class="chip on" data-filter="all">All {len(findings)}</button>' + "".join(
                    f'<button class="chip {k}" data-filter="{k}">{SEV_LABEL.get(k, k)} {v}</button>' for k, v in counts.items() if v)
            all_fix = FIX_PREFIX_ALL + "\n\n".join(fix_prompts)
            label = "Copy fix prompt" if len(findings) == 1 else f"Copy fix prompt for all {len(findings)}"
            tools = (f'<div class="toolbar">{chips}<span class="grow"></span>'
                     f'<button class="copy" data-copy="{e(all_fix)}" title="Copy one prompt that asks Claude Code to fix every problem listed">{label}</button></div>')
        if findings:
            tally = sev_text + (" problem" if len(findings) == 1 else " problems")
        elif status == "completed":
            tally = "No issues found. Nothing survived verification."
        else:
            tally = f"No clean conclusion: the review did not complete ({status.replace('-', ' ')})."
        extra = []
        if plausible_items:
            extra.append(f'<a href="#plausible">{len(plausible_items)} worth a look</a>')
        if fx.get("dropped"):
            extra.append(f'<a href="#dropped">{len(fx["dropped"])} dismissed</a>')
        table = f'<table class="glance"><tbody>{rows}</tbody></table>' if rows else ""
        hero = f'''
    <section class="hero hero-{verdict_cls}" id="verdict" aria-label="Verdict">
      <div class="hero-top">
        <div class="hero-head"><span class="v-icon" aria-hidden="true">{ {"crit": "!", "imp": "!", "ok": "✓"}.get(verdict_cls, "?") }</span><span class="v-label">{e(verdict_txt)}</span><span class="v-tally">{e(tally)}{(" · " + " · ".join(extra)) if extra else ""}</span></div>
        <p class="v-why">{inline_md(fx.get("summary", ""))}</p>
      </div>
      {tools}
      {table}
    </section>'''

    probs = ""
    if findings:
        probs = f'''
    <section id="problems">
      <h2 class="sec">Problems, in depth</h2>
      <p class="sec-note">Most severe first. Each one shows how it breaks, the code involved, why it happens, what it costs, and how to fix and prove it. Press <kbd>j</kbd> / <kbd>k</kbd> to move between problems.</p>
      <div class="toolbar"><button class="chip" id="fold-all">Collapse all</button><button class="chip" id="open-all">Expand all</button></div>
      {"".join(prob_html)}
    </section>'''

    sections = []
    if plausible:
        sections.append('<section id="plausible"><h2 class="sec">Worth a look</h2><p class="sec-note">Reachable and not disproven, but one fact the review could not see decides each one. Each line says what to check.</p>'
                        f'<ul class="wal">{plausible}</ul></section>')
    if spec_rows:
        sections.append(f'<section id="spec"><h2 class="sec">Requirements</h2><p class="sec-note">Checked against {inline_md(contract_src or "the stated purpose")}.</p>'
                        f'<table class="req"><thead><tr><th>Requirement</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{spec_rows}</tbody></table>'
                        + (f'<details><summary>The full contract used</summary><pre class="raw">{e(contract)}</pre></details>' if contract else "") + '</section>')
    if tests.strip():
        sections.append(f'<section id="tests"><h2 class="sec">Test evidence</h2><pre class="raw">{e(tests)}</pre></section>')
    if files_rows:
        ordered = any(r.get("order") for r in roles.values())
        sections.append('<section id="files"><h2 class="sec">Files in this change</h2>'
                        + ('<p class="sec-note">Numbered in the order to read them: foundations first, tests last.</p>' if ordered else "")
                        + f'<table class="files"><tbody>{files_rows}</tbody></table></section>')
    if concepts:
        sections.append(f'<section id="concepts"><h2 class="sec">Terms used here</h2><dl class="terms">{concepts}</dl></section>')
    if tryit:
        sections.append(f'<section id="try"><h2 class="sec">Check it yourself</h2><ul class="checks">{tryit}</ul></section>')
    if dropped or unchecked:
        sections.append('<section id="dropped"><h2 class="sec">Dismissed</h2><p class="sec-note">Raised during the review and disproved by the code, or out of scope. Each says why, so you can overrule it.</p>'
                        + (f'<details open><summary>{len(fx.get("dropped", []))} candidates dismissed, with the disproof</summary><ul>{dropped}</ul></details>' if dropped else "")
                        + (f'<details><summary>Not checked or set aside</summary><ul>{unchecked}</ul></details>' if unchecked else "") + '</section>')

    # --- navigation
    nav = ['<nav class="rail" aria-label="Contents"><h2>On this page</h2><ol>',
           f'<li><a href="#top">{"Overview" if explain_only else "Verdict"}</a></li>']
    for cond, href, label, cnt in ((overview, "context", "What changed and why", ""), (big, "picture", "The big picture", ""),
                                   (steps, "walkthrough", "How the code works", len(steps)),
                                   (findings, "problems", "Problems, in depth", len(findings)),
                                   (plausible, "plausible", "Worth a look", len(plausible_items))):
        if cond:
            nav.append(f'<li><a href="#{href}"><span class="rt">{label}</span>{f"<span class=cnt>{cnt}</span>" if cnt else ""}</a></li>')
    nav.append('</ol>')
    if findings:
        nav.append('<h2>Problems</h2><ol>' + "".join(
            f'<li><a href="#{e(f["id"])}" title="{e(f.get("title"))}"><span class="dot {e(f.get("severity", "minor"))}"></span>'
            f'<span class="tag">{e(f["id"])}</span><span class="rt">{e(f.get("title"))}</span></a></li>'
            for f in findings) + '</ol>')
    if steps:
        nav.append('<h2>Walkthrough</h2><ol>' + "".join(
            f'<li><a href="#step-{i}" title="{e(s.get("title"))}"><span class="tag">{i:02d}</span><span class="rt">{e(s.get("title"))}</span></a></li>' for i, s in enumerate(steps, 1)) + '</ol>')
    more = [("spec", "Requirements", spec_rows), ("tests", "Test evidence", tests.strip()), ("files", "Files", files_rows),
            ("concepts", "Terms", concepts), ("try", "Check it yourself", tryit), ("dropped", "Dismissed", dropped or unchecked)]
    nav.append('<h2>More</h2><ol>' + "".join(f'<li><a href="#{k}">{t}</a></li>' for k, t, v in more if v) + '</ol></nav>')

    # --- where this came from, and one line of facts under the title
    commit = (meta.get("reviewed_commit") or "")[:7]
    crumbs = [f'<strong>{e(meta.get("repo", ""))}</strong>'] if meta.get("repo") else []
    if origin["label"]:
        crumbs.append(f'<a href="{e(origin["url"])}">{e(origin["label"])} ↗</a>' if origin["url"].startswith("https://")
                      else e(origin["label"]))
    if commit:
        crumbs.append(f'<span title="Reviewed commit">at <code>{e(commit)}</code></span>')
    nfiles = len(meta.get("files", []))
    added, deleted = int(meta.get("added", 0)), int(meta.get("deleted", 0))
    boxes = "".join('<i class="on"></i>' if k < effort else '<i></i>' for k in range(5))
    stats = [("Files", f'{nfiles} <small>changed</small>',
              f'<span class="c-add">+{added:,}</span> <span class="c-del">−{deleted:,}</span> lines', ""),
             ("Review effort", f'<span class="effort" aria-hidden="true">{boxes}</span><small>{effort} of 5</small>',
              f'{EFFORT_TEXT[effort]} to {"read" if explain_only else "review"}', "")]
    if explain_only:
        stats.append(("Mode", "Explainer only, not checked for bugs",
                      "Run /rk:review on the same target to hunt for bugs.", "note"))
    else:
        if findings or status == "completed":
            stats.append(("Problems", f'{len(findings)} <small>confirmed</small>' if findings else '0 <small>found</small>',
                          e(sev_text) if findings else "nothing survived verification", ""))
        stats.append(("Tests", "Ran" if tests_line != "not run" else "Not run",
                      inline_md(tests_line) if tests_line != "not run" else "problems confirmed by reading the code", ""))
        if contract_src:
            stats.append(("Checked against", inline_md(contract_src), "", ""))
    lede = ex.get("one_liner") or ("" if not explain_only else fx.get("summary", ""))
    lede_html = f'<p class="lede">{inline_md(lede)}</p>' if lede else ""
    facts_html = '<div class="stats">' + "".join(
        f'<div class="stat {c}"><span class="k">{k}</span><span class="v">{v}</span>{f"<span class=s>{x}</span>" if x else ""}</div>'
        for k, v, x, c in stats) + '</div>'
    sep = ' <span class="sep">/</span> '

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}: {"walkthrough" if explain_only else "code review"}</title>
<style>{CSS}{diagrams.CSS}</style></head>
<body>
<header class="bar"><div class="bar-in">
  <span class="logo" title="review-kit">rk</span>
  <p class="crumbs">{sep.join(crumbs)}</p>
  {"" if explain_only else f'<a class="vchip {verdict_cls}" href="#verdict">{e(verdict_txt)}</a>'}
  <button id="theme" class="icon-btn" title="Switch between light and dark">Light / dark</button>
</div></header>
<div class="layout">
  {"".join(nav)}
  <main id="top">
    <p class="eyebrow">{"Walkthrough" if explain_only else "Code review"}{(" · " + e(fx.get("mode"))) if fx.get("mode") and not explain_only else ""}</p>
    <h1>{inline_md(title)}</h1>
    {lede_html}
    {facts_html}
    {hero}
    {overview}
    {big}
    {walk}
    {probs}
    {"".join(sections)}
    <footer><p>Generated by review-kit v{e(meta.get("rk_version", "unknown"))} on {_dt.datetime.now().strftime("%d %b %Y, %H:%M")}. Execution: {e(status)}. Reviewed commit <code>{e(meta.get("reviewed_commit", "not recorded"))}</code>, read from {e(meta.get("source_kind", "not recorded"))}.</p><p>Run folder: <code>{e(pkg)}</code></p></footer>
  </main>
</div>
<script>{JS}</script>
</body></html>'''
    out = pkg / "review.html"
    out.write_text(page)
    for w in depth_warnings(findings, details, steps, src):
        print(f"thin: {w}", file=sys.stderr)
    return out, meta


def run_name(meta, pkg):
    """Folder name for a kept review: pr-12-20261122-014000, feature-x-20261122-014000, ..."""
    gh = meta.get("github") if isinstance(meta.get("github"), dict) else {}
    desc = str(meta.get("description", ""))
    if gh.get("pr"):
        label = f"pr-{gh['pr']}"
    elif desc.startswith("branch "):
        label = desc.split()[1]
    elif meta.get("target") and meta["target"] != "(current branch)":
        label = str(meta["target"])
    else:
        return pkg.name
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")[:60] or "review"
    return f"{label}-{meta.get('created') or pkg.name}"


def repo_reviews_dir(meta):
    """<repo>/.review-kit/reviews, ignored by git through its own .gitignore (no tracked file changes)."""
    root = meta.get("original_repo_root") or meta.get("repo_root")
    if not root or not (Path(root) / ".git").exists():
        return None
    reviews = Path(root) / ".review-kit" / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    ignore = reviews / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# review-kit output: kept locally, never committed\n*\n")
    return reviews


def deliver(out: Path, cfg, copy_to=None, open_it=False, meta=None):
    """Keep the page (and findings.json) where the user can find it, print its path, optionally open it.

    Default: <repo>/.review-kit/reviews/<run>/. `--copy-to DIR` or "html_dir" puts it in DIR instead;
    "html_dir": "temp" leaves it only in the scratch folder."""
    meta = meta or {}
    copy_to = copy_to or cfg.get("html_dir")
    if copy_to and str(copy_to) != "temp":
        target = Path(str(copy_to)).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        out = Path(shutil.copy2(out, target / f"{out.parent.name}.html"))
    elif not copy_to:
        try:
            reviews = repo_reviews_dir(meta)
            if reviews:
                dest = reviews / run_name(meta, out.parent)
                dest.mkdir(parents=True, exist_ok=True)
                findings = out.parent / "findings.json"
                if findings.is_file():
                    shutil.copy2(findings, dest / "findings.json")
                out = Path(shutil.copy2(out, dest / "review.html"))
        except OSError as exc:
            print(f"could not keep a copy in the repo ({exc}); the page stays in the scratch folder", file=sys.stderr)
    print(out)
    print(out.resolve().as_uri())
    if open_it or cfg.get("open") is True:
        import webbrowser
        try:
            webbrowser.open(out.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001 - a missing browser must not fail the review
            print(f"could not open a browser: {exc}", file=sys.stderr)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit("usage: render_html.py PKG [--open] [--copy-to DIR]")
    copy_to = args[args.index("--copy-to") + 1] if "--copy-to" in args[:-1] else None
    try:
        page, meta = render(Path(args[0]))
        config = meta.get("config") if isinstance(meta.get("config"), dict) else {}
        deliver(page, config, copy_to, "--open" in args, meta)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        sys.exit(f"HTML generation failed: {exc}")
