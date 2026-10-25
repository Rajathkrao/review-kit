#!/usr/bin/env bash
# Run an independent adversarial review with the Codex CLI, read-only.
# Usage: codex_review.sh PKG [FOCUS]
# Exit codes: 0 ok, 3 codex unavailable, 4 codex run failed.
set -uo pipefail
PKG="${1:?usage: codex_review.sh PKG [FOCUS]}"
FOCUS="${2:-none}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS="$HERE/../assets"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex-unavailable: codex CLI not on PATH" >&2; exit 3
fi
if ! codex --version >/dev/null 2>&1; then
  echo "codex-unavailable: codex --version failed" >&2; exit 3
fi
if codex login status >/dev/null 2>&1; then :; else
  # Older CLIs lack `login status`; only treat an explicit "not logged in" as unavailable.
  if codex login status 2>&1 | grep -qi "not logged in"; then
    echo "codex-unavailable: not logged in (run: codex login)" >&2; exit 3
  fi
fi

ROOT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["repo_root"])' "$PKG/meta.json")"
TARGET="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["description"])' "$PKG/meta.json")"

python3 - "$ASSETS/codex-adversarial-prompt.md" "$PKG" "$TARGET" "$FOCUS" > "$PKG/codex-prompt.md" <<'PY'
import sys, pathlib
tpl, pkg, target, focus = sys.argv[1:5]
pkg = pathlib.Path(pkg)
t = pathlib.Path(tpl).read_text()
contract = (pkg / "contract.md").read_text() if (pkg / "contract.md").exists() else "(no contract written)"
diff = (pkg / "diff.patch").read_text()
if len(diff) > 300_000:
    diff = diff[:300_000] + "\n[diff truncated; inspect the rest with read-only git commands]\n"
guidance = ("The repository context below is the change's contract and its diff. Inspect any other code "
            "you need with read-only commands before finalizing findings. Review only lines this change touched.")
body = f"## Contract (what the change is supposed to do)\n{contract}\n\n## Diff\n```diff\n{diff}\n```\n"
t = (t.replace("{{TARGET_LABEL}}", target).replace("{{USER_FOCUS}}", focus)
      .replace("{{REVIEW_COLLECTION_GUIDANCE}}", guidance).replace("{{REVIEW_INPUT}}", body))
print(t)
PY

OUT="$PKG/codex-output.json"
LOG="$PKG/codex.log"
run_codex() {
  codex exec --sandbox read-only --skip-git-repo-check -C "$ROOT" "$@" -o "$OUT" - < "$PKG/codex-prompt.md" >"$LOG" 2>&1
}
if ! run_codex --output-schema "$ASSETS/codex-review-schema.json"; then
  if grep -qiE "unexpected argument|unknown option|output-schema" "$LOG"; then
    run_codex || { echo "codex-failed: see $LOG" >&2; exit 4; }
  else
    echo "codex-failed: see $LOG" >&2; exit 4
  fi
fi

python3 - "$OUT" "$PKG/candidates/second-model.json" <<'PY'
import json, re, sys, pathlib
src, dst = sys.argv[1:3]
raw = pathlib.Path(src).read_text().strip()
m = re.search(r"\{.*\}", raw, re.S)
data = json.loads(m.group(0)) if m else {"findings": []}
sev = {"critical": "critical", "high": "important", "medium": "minor", "low": "minor"}
cands = []
for f in data.get("findings", []):
    c = f.get("confidence", 0.5)
    cands.append({
        "title": f.get("title", ""), "file": f.get("file", ""),
        "line_start": f.get("line_start", 0), "line_end": f.get("line_end", f.get("line_start", 0)),
        "severity": sev.get(f.get("severity", "medium"), "minor"),
        "body": f.get("body", ""), "evidence": "Reported by Codex (second model).",
        "recommendation": f.get("recommendation", ""),
        "confidence": int(round(c * 100)) if c <= 1 else int(c),
        "found_by": "codex", "needs_test": False})
out = {"lens": "second-model", "found_by": "codex", "verdict": data.get("verdict"),
       "summary": data.get("summary", ""), "candidates": cands, "not_checked": []}
pathlib.Path(dst).write_text(json.dumps(out, indent=2))
print(f"codex: {len(cands)} findings, verdict {data.get('verdict')}")
PY
