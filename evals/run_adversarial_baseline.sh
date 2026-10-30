#!/usr/bin/env bash
# Baseline: the Codex plugin's adversarial-review prompt, run verbatim by Claude Code
# (read-only tools, structured JSON), on a fixture branch. Isolates prompt/method from model.
#   ./run_adversarial_baseline.sh <fixture> <branch> <run-name> [base]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; PLUGIN="$(dirname "$HERE")"
FIX=$1; BR=$2; NAME=$3; BASE=${4:-main}
if [ ! -d "$HERE/fixtures" ]; then
  TMPFX=$(mktemp -d "$HERE/.fixtures.XXXXXX"); tar xzf "$HERE/fixtures.tgz" -C "$TMPFX"
  python3 -c 'import os,sys; os.rename(sys.argv[1], sys.argv[2])' "$TMPFX" "$HERE/fixtures" 2>/dev/null || rm -rf "$TMPFX"
fi
OUT="$HERE/runs/$NAME"; [ ! -e "$OUT" ] || { echo "run exists: $OUT" >&2; exit 2; }
mkdir -p "$OUT"; cp -r "$HERE/fixtures/$FIX" "$OUT/$FIX"; cd "$OUT/$FIX"; git checkout -q "$BR"
python3 - "$PLUGIN/skills/review-kit/assets/codex-adversarial-prompt.md" "$BR vs $BASE" "$(git diff -U10 "$BASE"...HEAD)" > "$OUT/prompt.md" <<'PY'
import sys
t=open(sys.argv[1]).read()
t=(t.replace("{{TARGET_LABEL}}",sys.argv[2]).replace("{{USER_FOCUS}}","none")
    .replace("{{REVIEW_COLLECTION_GUIDANCE}}","The repository context below is the branch diff. Inspect the target diff and any other code yourself with read-only commands before finalizing findings.")
    .replace("{{REVIEW_INPUT}}","```diff\n"+sys.argv[3]+"\n```"))
schema=open(sys.argv[1].replace("codex-adversarial-prompt.md","codex-review-schema.json")).read()
print(t+"\n\nOutput: a single JSON object matching this schema, and nothing else:\n```json\n"+schema+"\n```")
PY
date +%s > "$OUT/start"
claude -p "$(cat "$OUT/prompt.md")" --allowedTools "Read,Grep,Glob,Bash(git:*)" --output-format json > "$OUT/result.json" 2> "$OUT/stderr.txt"
date +%s > "$OUT/end"
python3 - "$OUT" <<'PY'
import json,sys,re,pathlib
out=pathlib.Path(sys.argv[1]); r=json.loads((out/'result.json').read_text())
txt=r.get('result','');m=re.search(r'\{.*\}',txt,re.S)
data=json.loads(m.group(0)) if m else {"findings":[]}
lines=[f"## Adversarial baseline · verdict {data.get('verdict')}","",data.get('summary',''),""]
for i,f in enumerate(data.get('findings',[]),1):
    lines+= [f"**{i}. {f.get('severity','').title()}: {f.get('title')}**",f"`{f.get('file')}:{f.get('line_start')}-{f.get('line_end')}`",f.get('body',''),f"**Fix:** {f.get('recommendation','')}",f"<sub>confidence {f.get('confidence')}</sub>",""]
(out/'report.md').write_text("\n".join(lines)); (out/'findings.json').write_text(json.dumps(data,indent=2))
s=int((out/'end').read_text())-int((out/'start').read_text())
json.dump({'execution_status':'completed','cost_usd':r.get('total_cost_usd'),'seconds':s,'findings':len(data.get('findings',[]))},open(out/'status.json','w'))
print(json.dumps({'cost_usd':r.get('total_cost_usd'),'seconds':s,'findings':len(data.get('findings',[]))}))
PY
